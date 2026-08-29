#!/usr/bin/env python3
"""Dériver une table « thème de programme → cycle » depuis les programmes du corpus.

═══ AUCUNE ENTRÉE SANS SOURCE ════════════════════════════════════════════

Chaque entrée de la table est adossée à un document de programme du corpus, avec
son `sha256`, son titre et l'extrait qui l'établit. **Une entrée sans source ne
rentre pas dans la table** — ni depuis une connaissance générale, ni depuis une
plausibilité.

C'est la validation elle-même : une table dont 100 % des entrées sont sourcées
vaut mieux que n'importe quel pourcentage mesuré contre une référence dont nous
avons établi qu'elle est fausse.

═══ CE QU'UN THÈME DONNE, ET CE QU'IL NE DONNE PAS ═══════════════════════

« Se chercher, se construire » est une des quatre entrées du programme de
français du cycle 4. Elle couvre le cycle entier sans distinguer 5e, 4e et 3e.
**Un thème donne donc le CYCLE, jamais l'année.** Affiner au-delà serait affiner
sans preuve.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path


def sans_accent(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texte)
                   if unicodedata.category(c) != "Mn").lower()


#: Un document de programme déclare sa portée. On ne retient que ceux qui la
#: déclarent explicitement : un thème tiré d'un document de portée incertaine
#: propagerait cette incertitude à toute la table.
_PORTEE = (
    ("cycle4", re.compile(r"\bcycle\s*4\b|cycle des approfondissements")),
    ("cycle3", re.compile(r"\bcycle\s*3\b|cycle de consolidation")),
    ("seconde", re.compile(r"\bde seconde\b|\ben seconde\b|seconde generale")),
    ("premiere", re.compile(r"\bde premiere\b|\ben premiere\b|premiere generale|"
                            r"premiere technologique")),
    ("terminale", re.compile(r"\bde terminale\b|\ben terminale\b|terminale generale|"
                             r"terminale technologique|\bterminale stmg\b")),
)

#: Un intitulé de thème : ligne autonome, capitalisée, sans ponctuation
#: terminale, ni numérotation de page. Les seuils sont serrés : une table
#: bruitée ferait de faux rattachements.
_LONGUEUR = (18, 85)


def portee_du_programme(titre: str) -> tuple[list[str], str] | None:
    """Lire la portée dans le TITRE, jamais dans le corps du texte.

    Le corps d'un programme de terminale cite « les enseignements scientifiques
    communs en classe de seconde » : c'est un prérequis, pas sa portée. Prendre
    la première correspondance dans le corps attribuait 1 377 thèmes à `seconde`,
    dont ceux du programme de spécialité de première ET terminale — le même
    défaut de prérequis que P1, réintroduit ici par moi.

    Le titre, lui, est la déclaration de portée de l'éditeur : « Spécialité de
    sciences de l'ingénieur **de première et terminale** », « Programme
    d'enseignement du **cycle des approfondissements (cycle 4)** ». Il ne cite
    pas de prérequis.

    Une portée multiple est conservée telle quelle : un programme de première ET
    terminale porte les deux, et forcer un niveau unique serait affiner sans
    preuve.
    """
    plat = " ".join(sans_accent(titre).split())
    trouves: list[str] = []
    for niveau, motif in _PORTEE:
        if motif.search(plat):
            trouves.append(niveau)
    if not trouves:
        return None
    # `cycle4` et une année de lycée sont incompatibles : titre trop ambigu.
    if "cycle4" in trouves and len(trouves) > 1:
        return None
    return trouves, plat[:180]


def themes_du_programme(texte: str, maximum: int = 40) -> list[str]:
    """Les intitulés d'entrées / thèmes énoncés par un programme."""
    trouves: list[str] = []
    vus: set[str] = set()
    for brut in texte.splitlines():
        ligne = " ".join(brut.split())
        if not (_LONGUEUR[0] <= len(ligne) <= _LONGUEUR[1]):
            continue
        if ligne.endswith((".", ":", ";", ",", "?", "!")):
            continue
        if re.search(r"\d{2,}", ligne) or "http" in ligne.lower():
            continue
        if not re.match(r"^[A-ZÀ-Ý«]", ligne):
            continue
        # Un thème de programme se lit comme un titre : pas de verbe conjugué
        # en tête, pas de mention d'éditeur.
        if re.search(r"(eduscol|ministere|retrouvez|informer et accompagner|"
                     r"page|sommaire|annexe)", ligne, re.I):
            continue
        cle = sans_accent(ligne)
        if cle in vus:
            continue
        vus.add(cle)
        trouves.append(ligne)
        if len(trouves) >= maximum:
            break
    return trouves


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args(argv)

    racine = args.corpus_dir
    with open(racine / "00_INDEX_PROVENANCE/catalogue-par-scope.tsv",
              encoding="utf-8") as flux:
        catalogue = {c["sha256"]: c for c in csv.DictReader(flux, delimiter="\t")}

    # Les documents de programme : leur titre le déclare.
    _PROGRAMME = re.compile(
        r"(programme d[e']enseignement|^programme (de|d[e'])|^specialite |"
        r"bo\s*(special|n\s*°)|bulletin officiel|arrete du)")
    candidats = [sha for sha, c in catalogue.items()
                 if _PROGRAMME.search(sans_accent(c["titre"]))]
    print(f"  documents de programme au catalogue : {len(candidats)}", flush=True)

    pdfs = {hashlib.sha256(p.read_bytes()).hexdigest(): p
            for p in (racine / "01_EDUSCOL_OFFICIEL").rglob("*.pdf")}
    from pypdf import PdfReader

    table: dict[str, dict[str, object]] = {}
    sans_portee = 0
    for n, sha in enumerate(sorted(candidats), 1):
        chemin = pdfs.get(sha)
        if chemin is None:
            continue
        try:
            lecteur = PdfReader(str(chemin))
            # Lire le document ENTIER : les entrées du programme de français du
            # cycle 4 sont page 27 d'un document de 138 pages. Une fenêtre de
            # 20 pages les rendait inatteignables — le thème le plus canonique
            # du corpus était absent de la table censée le contenir.
            texte = "\n".join((p.extract_text() or "") for p in lecteur.pages)
        except Exception:                                    # noqa: BLE001
            continue
        titre = catalogue[sha]["titre"]
        portee = portee_du_programme(titre)
        if portee is None:
            sans_portee += 1
            continue                       # portée incertaine : rien n'entre
        niveaux, extrait_portee = portee
        for theme in themes_du_programme(texte):
            cle = sans_accent(theme)
            existant = table.get(cle)
            if existant and existant["cycle"] != niveaux:
                existant["ambigu"] = True   # deux programmes, deux portées
                continue
            table.setdefault(cle, {
                "theme": theme, "cycle": niveaux, "ambigu": False,
                "source_sha256": sha, "source_titre": titre[:110],
                "extrait_portee": extrait_portee[:200],
            })
        if n % 60 == 0:
            print(f"    {n}/{len(candidats)} — entrées : {len(table)}", flush=True)

    ambigus = [v for v in table.values() if v["ambigu"]]
    retenues = {k: v for k, v in table.items() if not v["ambigu"]}
    args.sortie.write_text(json.dumps(
        {"entrees": list(retenues.values()), "ambigues": len(ambigus)},
        ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n  ── TABLE THÈME → CYCLE ──")
    print(f"  programmes exploités        : {len(candidats) - sans_portee}")
    print(f"  programmes sans portée sûre : {sans_portee} (écartés)")
    print(f"  entrées retenues            : {len(retenues)}")
    print(f"  entrées écartées, ambiguës  : {len(ambigus)}")
    sourcees = sum(1 for v in retenues.values()
                   if v["source_sha256"] and v["extrait_portee"])
    print(f"  ENTRÉES SOURCÉES            : {sourcees}/{len(retenues)} "
          f"= {100 * sourcees / max(1, len(retenues)):.1f} %")
    par = {}
    for v in retenues.values():
        par[", ".join(v["cycle"])] = par.get(", ".join(v["cycle"]), 0) + 1
    for c, k in sorted(par.items(), key=lambda x: -x[1]):
        print(f"    {c:12} {k:5} thèmes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
