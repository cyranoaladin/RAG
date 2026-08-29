#!/usr/bin/env python3
"""Résoudre le placement de chaque document : l'éditeur d'abord, la portée large ensuite.

RÈGLE DE GRANULARITÉ, sans exception :

    bandeau présent            → ce qu'il porte : niveau exact, cycle, ou
                                 transversal lycée. L'éditeur fait foi.
    bandeau absent, catalogue  → ÉLARGIR. Le catalogue est faux sur 72,3 % des
                                 documents où l'éditeur s'est prononcé ; un niveau
                                 exact issu d'une source dont on connaît le défaut
                                 est une précision non fondée. Cycle ou transversal
                                 de discipline, jamais l'année.
    ni bandeau ni discipline   → COVERAGE_GAP.

On n'élargit jamais vers le faux, on n'affine jamais sans preuve. Un élève de
terminale trouvera un document transversal de sa discipline ; il ne recevra pas
un document de seconde présenté comme le sien.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

CORRESP = {"3e": "troisieme", "4e": "quatrieme", "5e": "cinquieme",
           "cycle-4": "cycle4", "seconde": "seconde",
           "premiere": "premiere", "terminale": "terminale"}
COLLEGE_ANNEES = {"troisieme", "quatrieme", "cinquieme"}
LYCEE = {"seconde", "premiere", "terminale"}


#: MOTIF « un document cite d'autres niveaux que le sien ».
#:
#: Quatre occurrences dans ce dépôt, toutes coûteuses : P1 lisant « la notion de
#: marché étudiée en classe de seconde » dans un document de première ; la portée
#: des programmes lue dans le corps du texte, attribuant 1 377 thèmes à `seconde` ;
#: le bandeau collège lisant « prérequis (programme du cycle 3) » comme une
#: déclaration ; et ici, un élargissement qui ignorait le titre.
#:
#: RÈGLE DE CONSTRUCTION : tout extracteur de niveau lit d'abord une DÉCLARATION
#: — titre, bandeau, en-tête — et ne descend au corps du texte qu'ensuite, en
#: écartant les contextes de renvoi. Un titre ne cite jamais de prérequis : c'est
#: ce qui en fait une source sûre.
_NIVEAUX_TITRE = (
    # La forme COORDONNÉE compte autant que la forme simple : « première et
    # terminale » porte les deux niveaux, et n'en retenir qu'un priverait les
    # élèves de terminale d'un programme qui les vise nommément.
    ("terminale", re.compile(r"\bde terminale\b|\ben terminale\b|\bet terminale\b|"
                             r"terminale generale|terminale technologique|"
                             r"classe terminale")),
    ("premiere", re.compile(r"\bde premiere\b|\ben premiere\b|\bet premiere\b|"
                            r"premiere generale|premiere technologique|"
                            r"classe de premiere")),
    ("seconde", re.compile(r"\bde seconde\b|\ben seconde\b|\bet seconde\b|"
                           r"seconde generale|classe de seconde")),
    ("cycle4", re.compile(r"\bcycle\s*4\b|cycle des approfondissements")),
)


def _sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte)
                   if unicodedata.category(c) != "Mn").lower()


def niveaux_du_titre(titre: str) -> list[str]:
    """Lire la portée déclarée par le TITRE — déclaration d'éditeur, jamais un renvoi."""
    plat = " ".join(_sans_accent(titre).split())
    trouves = [niveau for niveau, motif in _NIVEAUX_TITRE if motif.search(plat)]
    # `cycle4` avec une année de lycée : titre trop ambigu pour trancher.
    if "cycle4" in trouves and len(trouves) > 1:
        return []
    return trouves


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--bandeaux", type=Path, required=True)
    parser.add_argument("--hors-perimetre", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args(argv)

    racine = args.corpus_dir
    with open(racine / "00_ADMIN/eduscol_affectations.tsv", encoding="utf-8") as flux:
        affectations = list(csv.DictReader(flux, delimiter="\t"))
    with open(racine / "00_INDEX_PROVENANCE/catalogue-par-scope.tsv",
              encoding="utf-8") as flux:
        catalogue = {c["sha256"]: c for c in csv.DictReader(flux, delimiter="\t")}

    bandeaux = {b["sha256"]: b for b in json.loads(
        args.bandeaux.read_text(encoding="utf-8")) if b.get("granularite")}
    exclus = {h["sha256"] for h in json.loads(
        args.hors_perimetre.read_text(encoding="utf-8"))}

    # Disciplines déclarées par le catalogue, par document.
    disciplines: dict[str, set[str]] = {}
    niveaux_catalogue: dict[str, set[str]] = {}
    for ligne in affectations:
        disciplines.setdefault(ligne["sha256"], set()).add(ligne["subject"])
        niveau = CORRESP.get(ligne["level"])
        if niveau:
            niveaux_catalogue.setdefault(ligne["sha256"], set()).add(niveau)

    resultats = []
    corrections = 0
    for sha in sorted(disciplines):
        if sha in exclus:
            resultats.append({"sha256": sha, "statut": "HORS_PERIMETRE_ASSUME",
                              "niveaux": [], "granularite": None})
            continue

        matieres = sorted(disciplines[sha])
        catalogue_niveaux = sorted(niveaux_catalogue.get(sha, ()))
        bandeau = bandeaux.get(sha)

        if bandeau:
            # L'éditeur fait foi. Le catalogue est corrigé s'il diverge.
            niveaux = list(bandeau["niveaux"])
            granularite = bandeau["granularite"]
            replie = {"troisieme": "cycle4", "quatrieme": "cycle4",
                      "cinquieme": "cycle4"}
            diverge = bool(catalogue_niveaux) and not (
                {replie.get(n, n) for n in catalogue_niveaux}
                & {replie.get(n, n) for n in niveaux})
            if diverge:
                corrections += 1
            resultats.append({
                "sha256": sha, "statut": "PLACE", "niveaux": niveaux,
                "granularite": granularite, "matieres": matieres,
                "autorite": "P0_bandeau_editeur",
                "extrait": bandeau.get("extrait", "")[:200],
                "niveaux_catalogue": catalogue_niveaux,
                "catalogue_corrige": diverge,
            })
            continue

        if catalogue_niveaux:
            # Le catalogue seul : on élargit, on n'affine jamais.
            annees_college = {n for n in catalogue_niveaux if n in COLLEGE_ANNEES
                              or n == "cycle4"}
            annees_lycee = {n for n in catalogue_niveaux if n in LYCEE}
            if annees_college and not annees_lycee:
                niveaux, granularite = ["cycle4"], "cycle"
            elif annees_lycee and not annees_college:
                niveaux, granularite = sorted(LYCEE), "transversal_lycee"
            else:
                niveaux, granularite = ["cycle4", *sorted(LYCEE)], "transversal_discipline"
            resultats.append({
                "sha256": sha, "statut": "PLACE", "niveaux": niveaux,
                "granularite": granularite, "matieres": matieres,
                "autorite": "catalogue_elargi",
                "extrait": f"catalogue : {catalogue_niveaux} — élargi, "
                           f"le niveau exact n'est pas fondé",
                "niveaux_catalogue": catalogue_niveaux,
                "catalogue_corrige": False,
            })
            continue

        titre = catalogue.get(sha, {}).get("titre", "")
        niveaux_titre = niveaux_du_titre(titre)
        if niveaux_titre:
            # Le TITRE déclare la portée : c'est une source d'éditeur, du même
            # rang que le bandeau. On ne l'élargit pas — « Spécialité arts en
            # première et terminale » ne va pas au cycle 4.
            resultats.append({
                "sha256": sha, "statut": "PLACE", "niveaux": sorted(niveaux_titre),
                "granularite": ("niveau_exact" if len(niveaux_titre) == 1
                                else "multi_niveaux_declare"),
                "matieres": matieres, "autorite": "P0bis_titre_editeur",
                "extrait": titre[:200],
                "niveaux_catalogue": catalogue_niveaux, "catalogue_corrige": False,
            })
            continue

        if matieres:
            # Discipline seule : transversal de la discipline.
            resultats.append({
                "sha256": sha, "statut": "PLACE",
                "niveaux": ["cycle4", *sorted(LYCEE)],
                "granularite": "transversal_discipline", "matieres": matieres,
                "autorite": "discipline_seule",
                "extrait": f"discipline déclarée : {matieres}",
                "niveaux_catalogue": [], "catalogue_corrige": False,
            })
            continue

        resultats.append({"sha256": sha, "statut": "COVERAGE_GAP",
                          "niveaux": [], "granularite": None})

    args.sortie.write_text(json.dumps(resultats, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    statuts = Counter(r["statut"] for r in resultats)
    granularites = Counter(r["granularite"] for r in resultats if r["granularite"])
    autorites = Counter(r.get("autorite") for r in resultats if r.get("autorite"))
    print("  ── PLACEMENTS RÉSOLUS ──")
    for s, c in statuts.most_common():
        print(f"    {s:24} {c:5}")
    print("  ── par granularité ──")
    for g, c in granularites.most_common():
        print(f"    {g:24} {c:5}")
    print("  ── par autorité ──")
    for a, c in autorites.most_common():
        print(f"    {a:24} {c:5}")
    print(f"\n  CATALOGUE CORRIGÉ PAR L'ÉDITEUR : {corrections}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
