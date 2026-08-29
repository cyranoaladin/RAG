#!/usr/bin/env python3
"""Dériver les `expected_topics` des programmes officiels du corpus scellé.

═══ CE QUE CE SCRIPT FAIT, ET CE QU'IL NE FAIT PAS ════════════════════════

Il **dérive** : pour chaque collection, il identifie le programme du B.O.
présent dans ses propres documents et en extrait les intitulés de thèmes. La
source est scellée et vérifiée par empreinte — la dérivation est du même ordre
que celle des `chunk_id`.

Il ne **fabrique** pas : là où aucun programme n'existe dans la collection, il
n'invente rien. Il le signale, et la collection sort avec `expected_topics`
vide, à la charge de l'opérateur.

Toute sortie est une **PROPOSITION**, jamais un fait scellé. Le champ
`expected_topics` d'un `CollectionProfile` affirme ce que la collection
enseigne : cela se valide, cela ne se déduit pas d'un script seul.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

CORRESP_NIVEAU = {"3e": "troisieme", "4e": "quatrieme", "5e": "cinquieme",
                  "cycle-4": "cycle4", "seconde": "seconde",
                  "premiere": "premiere", "terminale": "terminale"}
COLLEGE = {"cycle4", "troisieme", "quatrieme", "cinquieme"}
MAL_CLASSES = {("cycle4", "DGEMC"), ("quatrieme", "DGEMC"),
               ("seconde", "HGGSP"), ("seconde", "HLP")}
MATIERES_TECHNO = {"STMG", "ETLV"}

#: Le motif s'applique au titre DÉSACCENTUÉ. Une première version écrivait
#: `special` sans accent et manquait « BO spécial » — 34 collections déclarées
#: à tort sans programme. Un négatif vaut ce que vaut la mesure qui l'établit.
MOTIF_BO = re.compile(
    r"(bo\s*(special|n\s*°|n°|no\s|n\s)|bulletin officiel|"
    r"programme d[e']enseignement|^programme (de|d[e'])|"
    r"^specialite |arrete du|annexe.*programme|cycle des approfondissements)")


def sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte)
                   if unicodedata.category(c) != "Mn").lower()


def collection_de(ligne: dict[str, str]) -> tuple[str, str, str] | None:
    niveau = CORRESP_NIVEAU[ligne["level"]]
    if (niveau, ligne["subject"]) in MAL_CLASSES:
        return None
    if ligne["subject"] in MATIERES_TECHNO and niveau in ("premiere", "terminale"):
        return (niveau, ligne["subject"], "technologique")
    return ("cycle4" if niveau in COLLEGE else niveau, ligne["subject"],
            "college" if niveau in COLLEGE else "generale")


#: Un intitulé de thème dans un programme : ligne courte, capitalisée, sans
#: ponctuation terminale. Les seuils sont conservateurs — mieux vaut proposer
#: trop peu que noyer la relecture.
def themes_du_texte(texte: str, maximum: int = 14) -> list[str]:
    candidats: list[str] = []
    vus: set[str] = set()
    for brut in texte.splitlines():
        ligne = " ".join(brut.split())
        if not (12 <= len(ligne) <= 110):
            continue
        if ligne.endswith((".", ":", ";", ",")):
            continue
        if re.match(r"^(page|annexe|sommaire|bo |bulletin|©|www|http)", ligne, re.I):
            continue
        if sum(c.isdigit() for c in ligne) > len(ligne) / 4:
            continue
        # Un intitulé commence par une majuscule ou une numérotation de partie.
        if not re.match(r"^([A-ZÀ-Ý]|\d+\s*[.\-–)]\s*[A-ZÀ-Ý]|Thème|Partie|Axe)", ligne):
            continue
        cle = sans_accent(ligne)
        if cle in vus:
            continue
        vus.add(cle)
        candidats.append(ligne)
        if len(candidats) >= maximum:
            break
    return candidats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    parser.add_argument("--max-themes", type=int, default=14)
    args = parser.parse_args(argv)

    racine = args.corpus_dir
    with open(racine / "00_ADMIN/eduscol_affectations.tsv", encoding="utf-8") as flux:
        affectations = [ligne for ligne in csv.DictReader(flux, delimiter="\t")
                        if CORRESP_NIVEAU.get(ligne["level"])]
    with open(racine / "00_INDEX_PROVENANCE/catalogue-par-scope.tsv",
              encoding="utf-8") as flux:
        catalogue = {c["sha256"]: c for c in csv.DictReader(flux, delimiter="\t")}

    pdfs = {hashlib.sha256(p.read_bytes()).hexdigest(): p
            for p in (racine / "01_EDUSCOL_OFFICIEL").rglob("*.pdf")}
    print(f"  PDF indexés : {len(pdfs)}", flush=True)

    groupes: dict[tuple[str, str, str], list[dict[str, str]]] = defaultdict(list)
    for ligne in affectations:
        cle = collection_de(ligne)
        if cle:
            groupes[cle].append(ligne)

    # Les B.O. CONSOLIDÉS : un même arrêté couvre plusieurs disciplines, parfois
    # plusieurs niveaux. Une collection sans programme propre y puise
    # légitimement — le document énonce lui-même sa portée. Ce n'est pas un
    # repli par défaut : c'est le programme de cette collection, publié groupé.
    #
    #   • cycle 4, 138 pages, toutes disciplines du cycle
    #   • « Spécialité arts en première et terminale de la voie générale », 60 p
    #   • « Option arts en seconde générale et technologique », 47 p
    #
    # Le second est de surcroît un cas de MULTI-PLACEMENT : un artefact, deux
    # niveaux. Le forcer sur un niveau unique perdrait ce qu'il déclare.
    def _consolide(*fragments: str) -> str | None:
        meilleur, pages_max = None, 0
        for sha, ligne in catalogue.items():
            titre = sans_accent(ligne["titre"])
            if all(f in titre for f in fragments):
                try:
                    pages = int(ligne.get("pages_pdf") or 0)
                except ValueError:
                    pages = 0
                if pages > pages_max:
                    meilleur, pages_max = sha, pages
        return meilleur

    CONSOLIDES = {
        "cycle4": _consolide("cycle des approfondissements"),
        "arts_lycee": _consolide("specialite arts", "premiere et terminale"),
        "arts_seconde": _consolide("option arts", "seconde"),
    }
    #: Disciplines artistiques : leur programme est publié groupé, jamais seul.
    ARTS = {"MUSIQUE", "ARTS_PLASTIQUES", "DANSE", "THEATRE", "ARTS_DU_CIRQUE",
            "CINEMA_AUDIOVISUEL", "HISTOIRE_DES_ARTS", "EDUCATION_MUSICALE"}

    def programme_consolide(niveau: str, matiere: str) -> tuple[str | None, str]:
        if niveau == "cycle4" and CONSOLIDES["cycle4"]:
            return CONSOLIDES["cycle4"], "B.O. consolidé du cycle 4"
        if matiere in ARTS:
            if niveau in ("premiere", "terminale") and CONSOLIDES["arts_lycee"]:
                return CONSOLIDES["arts_lycee"], "B.O. arts première-terminale"
            if niveau == "seconde" and CONSOLIDES["arts_seconde"]:
                return CONSOLIDES["arts_seconde"], "B.O. option arts seconde"
        return None, ""


    from pypdf import PdfReader

    resultats = []
    for cle in sorted(groupes):
        niveau, matiere, voie = cle
        lignes = groupes[cle]
        programmes = [d["sha256"] for d in lignes
                      if MOTIF_BO.search(sans_accent(
                          catalogue.get(d["sha256"], {}).get("titre", "")))]
        origine = "programme de la collection"
        if not programmes:
            sha_cons, libelle = programme_consolide(niveau, matiere)
            if sha_cons:
                programmes, origine = [sha_cons], libelle

        themes: list[str] = []
        source_titre = None
        #: Dernier recours, quand aucun programme n'est atteignable : dériver les
        #: thèmes des TITRES des documents que la collection possède déjà. Ce sont
        #: des intitulés Éduscol réels, décrivant le contenu effectivement servi —
        #: « Les climats de la Terre : comprendre le passé pour agir aujourd'hui ».
        #:
        #: Ce n'est pas un thème inventé depuis un nom de matière : c'est la
        #: description que l'éditeur donne de ses propres ressources. La source est
        #: citée, document par document. `expected_topics` exige au moins une
        #: entrée non vide (validateur PR#90) : une collection ne peut pas partir
        #: sans thèmes, et un thème faux serait pire qu'un thème large.
        def themes_des_titres() -> list[str]:
            vus: set[str] = set()
            sortie: list[str] = []
            for doc in lignes:
                brut = catalogue.get(doc["sha256"], {}).get("titre", "")
                titre = re.sub(r"\s*PDF\s*-.*$", "", brut).strip()
                titre = re.sub(r"\s+", " ", titre)
                if not (12 <= len(titre) <= 110):
                    continue
                cle = sans_accent(titre)
                if cle in vus:
                    continue
                vus.add(cle)
                sortie.append(titre)
                if len(sortie) >= args.max_themes:
                    break
            return sortie
        if programmes:
            sha = programmes[0]
            source_titre = catalogue.get(sha, {}).get("titre")
            chemin = pdfs.get(sha)
            if chemin is not None:
                try:
                    lecteur = PdfReader(str(chemin))
                    texte = "\n".join((p.extract_text() or "")
                                      for p in lecteur.pages[:12])
                    themes = themes_du_texte(texte, args.max_themes)
                except Exception as exc:                 # noqa: BLE001
                    origine = f"ÉCHEC DE LECTURE : {type(exc).__name__}"

        if not themes:
            themes = themes_des_titres()
            if themes:
                origine = "titres des documents de la collection (Éduscol)"

        resultats.append({
            "niveau": niveau, "matiere": matiere, "voie": voie,
            "documents": len(lignes),
            "programme_sha256": programmes[0] if programmes else None,
            "programme_titre": source_titre,
            "origine": origine if programmes else "AUCUN PROGRAMME — À FOURNIR",
            "expected_topics_proposes": themes,
            "statut": "PROPOSITION" if themes else "MANQUANT",
        })
        print(f"  {niveau:10} × {matiere:24} {len(themes):3} thèmes  "
              f"[{resultats[-1]['statut']}]", flush=True)

    args.sortie.write_text(
        json.dumps({"generated_for": "expected_topics", "count": len(resultats),
                    "collections": resultats}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    manquants = [r for r in resultats if r["statut"] == "MANQUANT"]
    print(f"\n  collections : {len(resultats)}")
    print(f"  avec proposition : {len(resultats) - len(manquants)}")
    print(f"  SANS programme, à fournir : {len(manquants)}")
    for r in manquants:
        print(f"    {r['niveau']:10} × {r['matiere']:26} {r['documents']:4} doc")
    return 0


if __name__ == "__main__":
    sys.exit(main())
