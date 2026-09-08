#!/usr/bin/env python3
"""Réconcilie les relations d'URL depuis les autorités de provenance Drive.

Le sens de la jointure, et il n'y en a qu'un d'admissible :

    identité de contenu  →  ligne de provenance  →  ligne de catalogue  →  URL

Jamais ``nom de fichier → URL devinée``. Une URL dérivée lexicalement d'un slug
aurait la forme d'une preuve sans en être une : un lecteur ne pourrait plus
distinguer une URL relevée d'une URL fabriquée, et la citation d'un document
pointerait vers une page que personne n'a confrontée à ses octets.

Cet importeur n'invente rien. Il ne suppose pas non plus la forme des fichiers
Drive : il DÉCOUVRE ses colonnes par leur en-tête et REFUSE en nommant ce
qu'il a cherché et ce qu'il a vu. Un importeur qui devine une colonne produit
une réconciliation dont personne ne peut dire sur quoi elle porte.

Il ne prononce jamais ``VERIFIED_CURRENT`` : le catalogue prouve qu'un SHA
était lié à une URL, pas que cette URL est encore actuelle. La vérification
d'actualité est un second gate, sur le réseau, hors de ce script.

Un contenu peut légitimement avoir PLUSIEURS provenances : le même document
publié sous deux scopes, ou référencé par deux pages institutionnelles. Réduire
à une URL par artefact perdrait cette information et la remplacerait par un
choix arbitraire. La sortie porte donc ``1..N`` relations de preuve, chacune
avec son scope, son objet source, son statut de catalogue et sa ligne d'origine.

``AMBIGUOUS_URL_EVIDENCE`` est réservé à une CONTRADICTION : deux lignes qui
décrivent la même relation source — même scope, même objet — et lui attribuent
des URL différentes. Plusieurs URL ne sont pas une ambiguïté ; deux URL pour la
même relation en sont une.

Le statut de catalogue n'est jamais écrasé : il reste porté par la relation.
Un contenu peut apparaître sous plusieurs statuts, et choisir par précédence
arbitraire ferait décider ici ce qui relève de l'autorité de servabilité.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path

KIND = "NEXUS-URL-PROVENANCE-RECONCILIATION-V1"

#: Les seules dispositions que cette passe peut prononcer. `VERIFIED_CURRENT`
#: n'en fait volontairement PAS partie.
DISPOSITION_TROUVEE = "URL_EVIDENCE_FOUND"
DISPOSITION_ABSENTE = "NO_URL_EVIDENCE"
DISPOSITION_AMBIGUE = "AMBIGUOUS_URL_EVIDENCE"
DISPOSITION_SANS_OBJET = "NOT_APPLICABLE"
DISPOSITION_ERREUR = "ERROR"
DISPOSITIONS = (
    DISPOSITION_TROUVEE,
    DISPOSITION_ABSENTE,
    DISPOSITION_AMBIGUE,
    DISPOSITION_SANS_OBJET,
    DISPOSITION_ERREUR,
)

#: D'où vient la preuve, nommément. Sans ce champ, « URL trouvée » ne dit pas
#: si elle a été jointe sur une empreinte ou sur un chemin.
SOURCE_JOINTURE_SHA = "CATALOGUE_SHA256_JOIN"
SOURCE_JOINTURE_CHEMIN = "MANIFEST_PATH_JOIN"
SOURCE_MANIFESTE_LOCAL = "LOCAL_RELEASE_MANIFEST"
SOURCE_AUCUNE = "NONE"

#: En-têtes acceptés, par rôle. Une liste explicite plutôt qu'une heuristique :
#: on veut pouvoir dire au refus CE QUI a été cherché.
COLONNES_EMPREINTE = ("sha256", "content_sha256", "empreinte", "checksum", "hash")
COLONNES_CHEMIN = (
    "chemin_technique_existant", "objet_source", "chemin", "path",
    "relative_path", "fichier", "file", "filename", "nom_fichier",
)
COLONNES_URL_NAVIGATION = (
    "url_source", "url", "page_url", "url_page", "source_url", "lien", "url_navigation",
)
COLONNES_URL_DIRECTE = ("download_url", "url_download", "url_directe", "direct_url", "url_fichier")
COLONNES_IDENTIFIANT = ("id", "row_id", "identifiant", "doc_id", "document_id")
#: Le contexte d'une relation de provenance : sans lui, deux lignes du même
#: contenu deviennent indiscernables et « plusieurs URL » se confond avec
#: « contradiction ».
COLONNES_SCOPE = ("scope", "perimetre", "scope_source")
COLONNES_OBJET = ("objet_source", "objet", "cas_locator")
COLONNES_STATUT = ("statut", "statut_source", "status")

_LIGNE_SHA256 = re.compile(r"\A([0-9a-fA-F]{64})[ \t]+\*?(.+)\Z")


class ReconciliationError(RuntimeError):
    """L'entrée ne permet pas de réconcilier — refus, jamais une supposition."""


def charger_manifeste_empreintes(chemin: Path) -> dict[str, list[str]]:
    """Lit un fichier au format ``sha256sum`` : ``<empreinte>  <chemin>``.

    Rend ``{empreinte: [chemins]}``. Une empreinte peut désigner plusieurs
    chemins — le même contenu publié à deux endroits — et c'est une
    information, pas une anomalie : la taire rendrait une ambiguïté invisible.
    """
    par_empreinte: dict[str, list[str]] = defaultdict(list)
    for numero, ligne in enumerate(
        chemin.read_text(encoding="utf-8", errors="strict").splitlines(), start=1
    ):
        if not ligne.strip():
            continue
        correspondance = _LIGNE_SHA256.match(ligne)
        if correspondance is None:
            raise ReconciliationError(
                f"{chemin.name} ligne {numero} : format inattendu — attendu "
                "« <sha256> <chemin> ». Un manifeste qu'on lit de travers "
                "produirait des jointures fausses au lieu d'un refus"
            )
        par_empreinte[correspondance.group(1).lower()].append(
            correspondance.group(2).strip()
        )
    if not par_empreinte:
        raise ReconciliationError(f"{chemin.name} : aucun enregistrement")
    return dict(par_empreinte)


def _delimiteur(chemin: Path, entete: str) -> str:
    """Le séparateur, déduit de l'extension puis CONFIRMÉ par l'en-tête."""
    # L'extension propose, l'en-tête dispose. Le catalogue réel est un « CSV »
    # séparé par `;` : croire l'extension produirait une seule colonne portant
    # toute la ligne, et un refus « aucune colonne d'URL » trompeur.
    ordre = (
        ["\t", ";", ","]
        if chemin.suffix.lower() in (".tsv", ".tab")
        else [";", ",", "\t"]
    )
    for candidat in ordre:
        if candidat in entete:
            return candidat
    raise ReconciliationError(
        f"{chemin.name} : l'en-tête ne porte ni tabulation, ni point-virgule, "
        "ni virgule — ce fichier n'est pas la table attendue"
    )


def _colonne(entetes: Sequence[str], candidats: Sequence[str]) -> str | None:
    """Le premier en-tête qui correspond, comparé sans casse ni ponctuation."""
    normalises = {
        re.sub(r"[^a-z0-9]", "", entete.lower()): entete for entete in entetes
    }
    for candidat in candidats:
        cle = re.sub(r"[^a-z0-9]", "", candidat.lower())
        if cle in normalises:
            return normalises[cle]
    return None


class Catalogue:
    """Une table de provenance, dont les colonnes ont été RELEVÉES."""

    def __init__(self, chemin: Path, lignes: list[dict[str, str]], colonnes: dict[str, str | None]):
        self.chemin = chemin
        self.lignes = lignes
        self.colonnes = colonnes
        self.par_empreinte: dict[str, list[int]] = defaultdict(list)
        self.par_chemin: dict[str, list[int]] = defaultdict(list)
        colonne_sha = colonnes["empreinte"]
        colonne_chemin = colonnes["chemin"]
        for index, ligne in enumerate(lignes):
            if colonne_sha:
                valeur = (ligne.get(colonne_sha) or "").strip().lower()
                if len(valeur) == 64:
                    self.par_empreinte[valeur].append(index)
            if colonne_chemin:
                valeur = (ligne.get(colonne_chemin) or "").strip()
                if valeur:
                    self.par_chemin[valeur].append(index)
                    # Le nom seul aussi : un catalogue peut porter le chemin
                    # complet là où le manifeste porte un chemin relatif.
                    self.par_chemin[valeur.rsplit("/", 1)[-1]].append(index)

    def identifiant(self, index: int) -> str:
        colonne = self.colonnes["identifiant"]
        if colonne:
            valeur = (self.lignes[index].get(colonne) or "").strip()
            if valeur:
                return valeur
        # À défaut d'identifiant déclaré, le NUMÉRO DE LIGNE — nommé comme tel,
        # pour qu'on sache que c'est une position et non une clé.
        return f"{self.chemin.name}#row{index + 1}"

    def _champ(self, index: int, role: str) -> str | None:
        colonne = self.colonnes.get(role)
        if not colonne:
            return None
        return (self.lignes[index].get(colonne) or "").strip() or None

    def relation(self, index: int) -> dict[str, object]:
        """Une relation de provenance ENTIÈRE.

        Le scope et l'objet source ne sont pas décoratifs : sans eux, deux
        lignes du même contenu deviennent indiscernables, et « plusieurs
        provenances légitimes » se confond avec « contradiction »."""
        return {
            # L'empreinte que porte la LIGNE, distincte de celle qu'on
            # cherchait : c'est elle qui révèle une jointure par chemin qui a
            # ramené un autre document.
            "row_content_sha256": (self._champ(index, "empreinte") or "").lower() or None,
            "url_source": self._champ(index, "url_navigation"),
            "direct_url": self._champ(index, "url_directe"),
            "scope": self._champ(index, "scope"),
            "objet_source": self._champ(index, "objet"),
            "catalogue_status": self._champ(index, "statut"),
            "evidence_file": self.chemin.name,
            "evidence_row": self.identifiant(index),
        }


def charger_catalogue(chemin: Path) -> Catalogue:
    """Lit une table de provenance en RELEVANT ses colonnes.

    Refuse si aucune colonne d'URL n'est présente, en nommant ce qui a été
    cherché et ce qui a été vu : un catalogue sans URL n'est pas un catalogue
    d'URL, et le lire quand même ne produirait que des lignes vides.
    """
    # `utf-8-sig` : le catalogue réel porte une marque d'ordre d'octets, qui
    # collerait au premier en-tête et le rendrait introuvable.
    texte = chemin.read_text(encoding="utf-8-sig", errors="strict")
    premiere = texte.split("\n", 1)[0]
    lecteur = csv.DictReader(texte.splitlines(), delimiter=_delimiteur(chemin, premiere))
    entetes = list(lecteur.fieldnames or [])
    if not entetes:
        raise ReconciliationError(f"{chemin.name} : aucun en-tête")
    colonnes = {
        "empreinte": _colonne(entetes, COLONNES_EMPREINTE),
        "chemin": _colonne(entetes, COLONNES_CHEMIN),
        "url_navigation": _colonne(entetes, COLONNES_URL_NAVIGATION),
        "url_directe": _colonne(entetes, COLONNES_URL_DIRECTE),
        "identifiant": _colonne(entetes, COLONNES_IDENTIFIANT),
        "scope": _colonne(entetes, COLONNES_SCOPE),
        "objet": _colonne(entetes, COLONNES_OBJET),
        "statut": _colonne(entetes, COLONNES_STATUT),
    }
    if not colonnes["url_navigation"] and not colonnes["url_directe"]:
        raise ReconciliationError(
            f"{chemin.name} : aucune colonne d'URL. Cherché "
            f"{list(COLONNES_URL_NAVIGATION) + list(COLONNES_URL_DIRECTE)}, "
            f"vu {entetes}"
        )
    if not colonnes["empreinte"] and not colonnes["chemin"]:
        raise ReconciliationError(
            f"{chemin.name} : ni empreinte ni chemin — rien sur quoi joindre. "
            f"Cherché {list(COLONNES_EMPREINTE) + list(COLONNES_CHEMIN)}, vu {entetes}"
        )
    return Catalogue(chemin, list(lecteur), colonnes)


def reconcilier(
    relations: Iterable[Mapping[str, object]],
    *,
    catalogues: Sequence[Catalogue],
    manifestes: Mapping[str, list[str]],
) -> dict[str, object]:
    """Rend, par relation du handoff, ses 1..N preuves d'URL et sa disposition."""
    resultats: list[dict[str, object]] = []
    comptes: dict[str, int] = dict.fromkeys(DISPOSITIONS, 0)
    urls_distinctes: set[str] = set()
    paires: set[tuple[str, str]] = set()
    multi_statut: list[dict[str, object]] = []
    non_indexables_en_attente = 0

    for relation in relations:
        empreinte = str(relation.get("content_sha256") or "")
        sortie: dict[str, object] = {
            "artifact_id": relation.get("artifact_id"),
            "drive_file_id": relation.get("drive_file_id"),
            "content_sha256": relation.get("content_sha256"),
            "source_role": relation.get("source_role"),
            "serving_relevance": relation.get("serving_relevance"),
            "catalogue_match": False,
            "manifest_match": False,
            "url_evidence": [],
            "distinct_urls": 0,
            "catalogue_statuses": [],
            "evidence_source": SOURCE_AUCUNE,
            "disposition": DISPOSITION_ABSENTE,
        }

        if len(empreinte) != 64:
            sortie["disposition"] = DISPOSITION_ERREUR
            sortie["error_detail"] = "content_sha256 absente ou malformée"
            comptes[DISPOSITION_ERREUR] += 1
            resultats.append(sortie)
            continue

        chemins = manifestes.get(empreinte, [])
        sortie["manifest_match"] = bool(chemins)

        # 1. La jointure la plus forte : l'empreinte, portée par le catalogue.
        trouvees: list[tuple[Catalogue, int, str]] = []
        for catalogue in catalogues:
            for index in catalogue.par_empreinte.get(empreinte, []):
                trouvees.append((catalogue, index, SOURCE_JOINTURE_SHA))
        # 2. À défaut, le chemin — mais SEULEMENT celui que le manifeste
        #    d'empreintes a rendu. Partir du nom de fichier de la relation
        #    serait une jointure lexicale, exactement ce qui est interdit.
        if not trouvees:
            for chemin in chemins:
                for catalogue in catalogues:
                    for index in catalogue.par_chemin.get(chemin, []):
                        trouvees.append((catalogue, index, SOURCE_JOINTURE_CHEMIN))
                    nom = chemin.rsplit("/", 1)[-1]
                    for index in catalogue.par_chemin.get(nom, []):
                        trouvees.append((catalogue, index, SOURCE_JOINTURE_CHEMIN))

        if not trouvees:
            if relation.get("serving_relevance") == "NON_INDEXABLE":
                # NON_INDEXABLE n'est PAS NOT_APPLICABLE : un objet non
                # indexable peut quand même exiger provenance, droits et
                # actualité. Sans autorité métier déclarant sa classe sans URL
                # pertinente, il reste en attente de preuve.
                sortie["non_indexable_pending_url_evidence"] = True
                non_indexables_en_attente += 1
            comptes[DISPOSITION_ABSENTE] += 1
            resultats.append(sortie)
            continue

        # Deux lignes identiques ne sont pas deux preuves.
        vues: dict[tuple, dict[str, object]] = {}
        source_jointure = SOURCE_AUCUNE
        for catalogue, index, source in trouvees:
            preuve = catalogue.relation(index)
            cle = (
                preuve["row_content_sha256"],
                preuve["url_source"],
                preuve["direct_url"],
                preuve["scope"],
                preuve["objet_source"],
                preuve["catalogue_status"],
            )
            vues.setdefault(cle, preuve)
            source_jointure = source if source_jointure == SOURCE_AUCUNE else source_jointure
        preuves = sorted(
            vues.values(),
            key=lambda p: (str(p["scope"] or ""), str(p["url_source"] or ""), str(p["evidence_row"])),
        )
        sortie["catalogue_match"] = True
        sortie["evidence_source"] = source_jointure
        sortie["url_evidence"] = preuves

        urls = {str(p["url_source"]) for p in preuves if p["url_source"]}
        sortie["distinct_urls"] = len(urls)
        urls_distinctes |= urls
        paires |= {(empreinte, u) for u in urls}

        statuts = sorted({str(p["catalogue_status"]) for p in preuves if p["catalogue_status"]})
        sortie["catalogue_statuses"] = statuts
        if len(statuts) > 1:
            # Le statut reste porté par la RELATION. Choisir par précédence
            # arbitraire ferait décider ici ce qui relève de l'autorité de
            # servabilité.
            multi_statut.append(
                {
                    "content_sha256": empreinte,
                    "status_set": statuts,
                    "source_relation_ids": [str(p["evidence_row"]) for p in preuves],
                    "url_evidence_ids": sorted(urls),
                }
            )

        # Ce qui est une AMBIGUÏTÉ, et ce qui n'en est pas une.
        #
        # Un même contenu référencé par deux pages institutionnelles — la page
        # de programme et une page thématique, ou `eduscol` et `sti.eduscol` —
        # a deux provenances également vraies. Les marquer ambiguës effacerait
        # une information et forcerait un choix arbitraire entre deux faits
        # établis. Un premier critère les attrapait à tort : `objet_source`
        # étant dérivé de l'empreinte, « même scope, même objet » ne veut dire
        # que « même contenu », et la règle revenait à interdire la
        # multi-provenance qu'on venait d'admettre.
        #
        # L'ambiguïté RÉELLE est une preuve qu'on ne peut pas attribuer : une
        # jointure par CHEMIN qui ramène des lignes portant une AUTRE empreinte.
        # Le chemin a alors désigné un autre document, et rien ne dit laquelle
        # de ces lignes parle du nôtre.
        etrangeres = sorted(
            {
                str(preuve["row_content_sha256"])
                for preuve in preuves
                if preuve.get("row_content_sha256")
                and str(preuve["row_content_sha256"]).lower() != empreinte
            }
        )
        if etrangeres:
            sortie["disposition"] = DISPOSITION_AMBIGUE
            sortie["unattributable_reason"] = "PATH_JOIN_MATCHED_OTHER_CONTENT"
            sortie["foreign_content_sha256"] = etrangeres
            comptes[DISPOSITION_AMBIGUE] += 1
        elif urls:
            sortie["disposition"] = DISPOSITION_TROUVEE
            comptes[DISPOSITION_TROUVEE] += 1
        else:
            # Des lignes existent mais aucune ne porte d'URL : absence de
            # preuve, pas preuve trouvée.
            comptes[DISPOSITION_ABSENTE] += 1
        resultats.append(sortie)

    total = len(resultats)
    rendu: dict[str, object] = {
        "kind": KIND,
        "URL_RELATIONS_TOTAL": total,
        "URL_PROVENANCE_FOUND": comptes[DISPOSITION_TROUVEE],
        "URL_NO_EVIDENCE": comptes[DISPOSITION_ABSENTE],
        "URL_AMBIGUOUS": comptes[DISPOSITION_AMBIGUE],
        "URL_NOT_APPLICABLE": comptes[DISPOSITION_SANS_OBJET],
        "URL_ERRORS": comptes[DISPOSITION_ERREUR],
        # Deux dénominateurs, jamais confondus : une page institutionnelle
        # partagée par cent documents est UNE url et cent relations.
        "FULL_DISTINCT_URLS": len(urls_distinctes),
        "FULL_ARTIFACT_URL_RELATIONS": len(paires),
        "NEEDS_URL_EVIDENCE_BUT_NON_INDEXABLE": non_indexables_en_attente,
        "TRUE_NOT_APPLICABLE": comptes[DISPOSITION_SANS_OBJET],
        "MULTI_STATUS_CONTENT_SHA": len(multi_statut),
        # Une relation sans URL est NO_URL_EVIDENCE, jamais « non comptée ».
        "URL_RELATIONS_ACCOUNTED": sum(comptes.values()),
        "URL_UNACCOUNTED": total - sum(comptes.values()),
        # La provenance n'est PAS l'actualité. Ce script ferme la première.
        "URL_PROVENANCE_ACCOUNTING": "PASS" if total == sum(comptes.values()) else "FAIL",
        "URL_CURRENTNESS_VERIFICATION": "NOT_STARTED",
        "multi_status_ledger": sorted(
            multi_statut, key=lambda e: str(e["content_sha256"])
        ),
        "relations": resultats,
    }
    return rendu


def verifier_egalite_des_ensembles(
    handoff: Sequence[Mapping[str, object]], reconciliees: Sequence[Mapping[str, object]]
) -> None:
    """Le compte ne suffit pas : ce sont les ENSEMBLES qui doivent coïncider.

    Deux populations de même taille et de contenus différents passeraient un
    contrôle de compte sans que rien ne le dise."""
    attendu = {str(r.get("content_sha256")) for r in handoff}
    obtenu = {str(r.get("content_sha256")) for r in reconciliees}
    if attendu != obtenu:
        raise ReconciliationError(
            f"ensembles disjoints : {len(attendu - obtenu)} relation(s) du "
            f"handoff absentes du résultat, {len(obtenu - attendu)} en trop"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff", required=True, type=Path)
    parser.add_argument(
        "--catalogue", action="append", default=[], type=Path,
        help="copie EXACTE d'un catalogue Drive (répétable)",
    )
    parser.add_argument(
        "--sha256-manifest", action="append", default=[], type=Path,
        help="copie EXACTE d'un manifeste d'empreintes (répétable)",
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)

    if not args.catalogue:
        parser.error("au moins un --catalogue est requis")

    handoff = json.loads(args.handoff.read_text(encoding="utf-8"))
    relations = handoff["relations"]

    empreintes: dict[str, list[str]] = defaultdict(list)
    for chemin in args.sha256_manifest:
        for empreinte, chemins in charger_manifeste_empreintes(chemin).items():
            empreintes[empreinte].extend(chemins)

    catalogues = [charger_catalogue(chemin) for chemin in args.catalogue]
    rendu = reconcilier(relations, catalogues=catalogues, manifestes=dict(empreintes))
    verifier_egalite_des_ensembles(relations, rendu["relations"])  # type: ignore[arg-type]

    rendu["inputs"] = {
        "handoff": args.handoff.name,
        "catalogues": [c.chemin.name for c in catalogues],
        "sha256_manifests": [p.name for p in args.sha256_manifest],
        "catalogue_columns": [
            {"file": c.chemin.name, **{k: v for k, v in c.colonnes.items()}}
            for c in catalogues
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(rendu, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for cle in (
        "URL_RELATIONS_TOTAL", "URL_PROVENANCE_FOUND", "URL_NO_EVIDENCE",
        "URL_AMBIGUOUS", "URL_NOT_APPLICABLE", "URL_ERRORS",
        "FULL_DISTINCT_URLS", "FULL_ARTIFACT_URL_RELATIONS",
        "NEEDS_URL_EVIDENCE_BUT_NON_INDEXABLE", "TRUE_NOT_APPLICABLE",
        "MULTI_STATUS_CONTENT_SHA",
        "URL_RELATIONS_ACCOUNTED", "URL_UNACCOUNTED",
        "URL_PROVENANCE_ACCOUNTING", "URL_CURRENTNESS_VERIFICATION",
    ):
        print(f"{cle}={rendu[cle]}")
    return 0 if rendu["URL_UNACCOUNTED"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
