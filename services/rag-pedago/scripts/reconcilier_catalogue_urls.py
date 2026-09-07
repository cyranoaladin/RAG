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
COLONNES_CHEMIN = ("chemin", "path", "relative_path", "fichier", "file", "filename", "nom_fichier")
COLONNES_URL_NAVIGATION = ("url", "page_url", "url_page", "source_url", "lien", "url_navigation")
COLONNES_URL_DIRECTE = ("download_url", "url_download", "url_directe", "direct_url", "url_fichier")
COLONNES_IDENTIFIANT = ("id", "row_id", "identifiant", "doc_id", "document_id")

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
    attendu = "\t" if chemin.suffix.lower() in (".tsv", ".tab") else ","
    if attendu in entete:
        return attendu
    autre = "," if attendu == "\t" else "\t"
    if autre in entete:
        return autre
    raise ReconciliationError(
        f"{chemin.name} : l'en-tête ne porte ni tabulation ni virgule — "
        "ce fichier n'est pas la table attendue"
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

    def urls(self, index: int) -> tuple[str | None, str | None]:
        ligne = self.lignes[index]
        navigation = self.colonnes["url_navigation"]
        directe = self.colonnes["url_directe"]
        return (
            (ligne.get(navigation) or "").strip() or None if navigation else None,
            (ligne.get(directe) or "").strip() or None if directe else None,
        )


def charger_catalogue(chemin: Path) -> Catalogue:
    """Lit une table de provenance en RELEVANT ses colonnes.

    Refuse si aucune colonne d'URL n'est présente, en nommant ce qui a été
    cherché et ce qui a été vu : un catalogue sans URL n'est pas un catalogue
    d'URL, et le lire quand même ne produirait que des lignes vides.
    """
    texte = chemin.read_text(encoding="utf-8", errors="strict")
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
    """Rend une disposition par relation, et le compte de chacune."""
    resultats: list[dict[str, object]] = []
    comptes: dict[str, int] = dict.fromkeys(DISPOSITIONS, 0)

    for relation in relations:
        empreinte = str(relation.get("content_sha256") or "")
        sortie: dict[str, object] = {
            "artifact_id": relation.get("artifact_id"),
            "drive_file_id": relation.get("drive_file_id"),
            "content_sha256": relation.get("content_sha256"),
            "catalogue_match": False,
            "manifest_match": False,
            "navigation_url": None,
            "direct_url": None,
            "evidence_source": SOURCE_AUCUNE,
            "evidence_row_id": None,
            "disposition": DISPOSITION_ABSENTE,
        }

        if relation.get("serving_relevance") == "NON_INDEXABLE":
            # Un document non indexable n'aura aucune citation à porter. C'est
            # une disposition assumée, pas une absence de preuve.
            sortie["disposition"] = DISPOSITION_SANS_OBJET
            comptes[DISPOSITION_SANS_OBJET] += 1
            resultats.append(sortie)
            continue

        if len(empreinte) != 64:
            sortie["disposition"] = DISPOSITION_ERREUR
            sortie["evidence_row_id"] = "content_sha256 absente ou malformée"
            comptes[DISPOSITION_ERREUR] += 1
            resultats.append(sortie)
            continue

        chemins = manifestes.get(empreinte, [])
        sortie["manifest_match"] = bool(chemins)

        # 1. La jointure la plus forte : l'empreinte, portée par le catalogue.
        candidats: list[tuple[Catalogue, int, str]] = []
        for catalogue in catalogues:
            for index in catalogue.par_empreinte.get(empreinte, []):
                candidats.append((catalogue, index, SOURCE_JOINTURE_SHA))
        # 2. À défaut, le chemin — mais SEULEMENT celui que le manifeste
        #    d'empreintes a rendu. Partir du nom de fichier de la relation
        #    serait une jointure lexicale, exactement ce qui est interdit.
        if not candidats:
            for chemin in chemins:
                for catalogue in catalogues:
                    for index in catalogue.par_chemin.get(chemin, []):
                        candidats.append((catalogue, index, SOURCE_JOINTURE_CHEMIN))
                    nom = chemin.rsplit("/", 1)[-1]
                    for index in catalogue.par_chemin.get(nom, []):
                        candidats.append((catalogue, index, SOURCE_JOINTURE_CHEMIN))

        # Deux lignes qui rendent la MÊME url ne sont pas une ambiguïté.
        distinctes = {}
        for catalogue, index, source in candidats:
            distinctes.setdefault(catalogue.urls(index), (catalogue, index, source))

        if not distinctes:
            comptes[DISPOSITION_ABSENTE] += 1
            resultats.append(sortie)
            continue

        sortie["catalogue_match"] = True
        if len(distinctes) > 1:
            sortie["disposition"] = DISPOSITION_AMBIGUE
            sortie["evidence_row_id"] = sorted(
                catalogue.identifiant(index) for catalogue, index, _ in distinctes.values()
            )
            comptes[DISPOSITION_AMBIGUE] += 1
            resultats.append(sortie)
            continue

        (navigation, directe), (catalogue, index, source) = next(iter(distinctes.items()))
        if not navigation and not directe:
            # La ligne existe mais ne porte aucune URL : c'est une absence de
            # preuve, pas une preuve trouvée.
            comptes[DISPOSITION_ABSENTE] += 1
            resultats.append(sortie)
            continue
        sortie.update(
            {
                "navigation_url": navigation,
                "direct_url": directe,
                "evidence_source": source,
                "evidence_row_id": catalogue.identifiant(index),
                "disposition": DISPOSITION_TROUVEE,
            }
        )
        comptes[DISPOSITION_TROUVEE] += 1
        resultats.append(sortie)

    total = len(resultats)
    rendu = {
        "kind": KIND,
        "URL_RELATIONS_TOTAL": total,
        "URL_PROVENANCE_FOUND": comptes[DISPOSITION_TROUVEE],
        "URL_NO_EVIDENCE": comptes[DISPOSITION_ABSENTE],
        "URL_AMBIGUOUS": comptes[DISPOSITION_AMBIGUE],
        "URL_NOT_APPLICABLE": comptes[DISPOSITION_SANS_OBJET],
        "URL_ERRORS": comptes[DISPOSITION_ERREUR],
        # Une relation sans URL est NO_URL_EVIDENCE, jamais « non comptée ».
        "URL_RELATIONS_ACCOUNTED": sum(comptes.values()),
        "URL_UNACCOUNTED": total - sum(comptes.values()),
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
        "URL_RELATIONS_ACCOUNTED", "URL_UNACCOUNTED",
    ):
        print(f"{cle}={rendu[cle]}")
    return 0 if rendu["URL_UNACCOUNTED"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
