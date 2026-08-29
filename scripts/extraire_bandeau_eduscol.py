#!/usr/bin/env python3
"""P0 — le bandeau éditeur d'Éduscol, palier primaire.

═══ POURQUOI LE BANDEAU REMPLACE LE CATALOGUE ════════════════════════════

Le champ `level` du catalogue est produit par le moissonneur. Le bandeau
« VOIE GÉNÉRALE · Sciences de la vie et de la Terre · Tle » est apposé par
**l'éditeur du document**. Ce n'est pas une source de plus à concilier : c'est
la source, et le catalogue en est une lecture dérivée.

La nuit du 29/08 a établi que ces deux vues divergent, et que c'est le catalogue
qui a tort — dix documents de terminale y étaient étiquetés `seconde`, chacun
portant `Tle` dans son propre bandeau. Mesurer un classifieur contre le catalogue
mesurait la cohérence d'une source en croyant mesurer l'exactitude d'un
classement.

**Là où le bandeau existe, il fait foi. Là où le catalogue le contredit, c'est le
catalogue qui est corrigé**, avec l'extrait en preuve.

═══ ÉLARGIR PLUTÔT QUE DEVINER ═══════════════════════════════════════════

Quand la preuve ne donne pas le niveau exact, la portée s'élargit — elle ne se
devine jamais étroite :

    année inconnue, cycle établi   → le cycle
    lycée établi, niveau inconnu   → transversal lycée
    discipline établie seule       → transversal de la discipline

Un document servi sous une portée large est trouvable ; un document servi sous un
niveau faux est trompeur ; un document absent ne sert personne.
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


#: Le bandeau lycée : « VOIE GÉNÉRALE <discipline><niveau> », le niveau étant
#: collé au nom de la discipline dans le texte extrait.
_BANDEAU_LYCEE = re.compile(
    r"voie\s+(generale|technologique)\s+(.{2,60}?)\s*(2de|1re|tle)\b")

#: Le bandeau collège : « CYCLE 4 <discipline> », ou la barre de navigation.
_BANDEAU_COLLEGE = re.compile(r"\bcycle\s*([34])\b")

_NIVEAU_BANDEAU = {"2de": "seconde", "1re": "premiere", "tle": "terminale"}

#: Barre de navigation « 2DE 1RE TLE » : elle liste les niveaux du cycle, pas
#: celui du document. Elle établit le LYCÉE sans établir l'année — c'est
#: exactement un cas d'élargissement de portée, pas un cas de doute.
_NAV_LYCEE = re.compile(r"\b2de\s+1re\s+tle\b")


def lire_bandeau(chemin: Path) -> dict[str, object] | None:
    """Extraire voie, discipline et portée depuis le bandeau éditeur."""
    try:
        from pypdf import PdfReader
        page = PdfReader(str(chemin)).pages[0]
        texte = page.extract_text() or ""
    except Exception:                                        # noqa: BLE001
        return None
    if not texte.strip():
        return None
    plat = " ".join(sans_accent(texte).split())

    m = _BANDEAU_LYCEE.search(plat)
    if m:
        debut = max(0, m.start() - 20)
        return {
            "voie": "generale" if m.group(1) == "generale" else "technologique",
            "discipline": " ".join(m.group(2).split()),
            "niveaux": [_NIVEAU_BANDEAU[m.group(3)]],
            "granularite": "niveau_exact",
            "palier": "P0_bandeau_editeur",
            "extrait": plat[debut:m.end() + 20],
        }

    # Le cycle 3 est presque toujours cité en PRÉREQUIS par un document de
    # cycle 4 : « prérequis (programme du cycle 3) », « dans le prolongement du
    # cycle 3, l'apprentissage au cycle 4 porte… ». Prendre la première
    # correspondance plaçait 53 documents de cycle 4 au cycle 3 — le défaut de
    # prérequis, pour la troisième fois, ici de ma main.
    #
    # Règle : si le cycle 4 apparaît, il l'emporte. Le corpus ne porte aucun
    # contenu de cycle 3 (COVERAGE_GAP établi), et une mention isolée de cycle 3
    # n'est donc pas une déclaration de portée.
    cycles = {m.group(1) for m in _BANDEAU_COLLEGE.finditer(plat)}
    if cycles:
        if "4" in cycles:
            c = next(m for m in _BANDEAU_COLLEGE.finditer(plat) if m.group(1) == "4")
            niveaux = ["cycle4"]
        else:
            c = next(_BANDEAU_COLLEGE.finditer(plat))
            niveaux = ["cycle3"]
        return {
            "voie": "college",
            "discipline": None,
            "niveaux": niveaux,
            "granularite": "cycle",
            "palier": "P0_bandeau_editeur",
            "extrait": plat[max(0, c.start() - 60):c.end() + 60],
        }

    if _NAV_LYCEE.search(plat):
        # Le lycée est établi, l'année ne l'est pas : la portée s'élargit.
        return {
            "voie": None,
            "discipline": None,
            "niveaux": ["seconde", "premiere", "terminale"],
            "granularite": "transversal_lycee",
            "palier": "P0_bandeau_editeur",
            "extrait": plat[:160],
        }
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus-dir", type=Path, required=True)
    parser.add_argument("--sortie", type=Path, required=True)
    args = parser.parse_args(argv)

    racine = args.corpus_dir
    with open(racine / "00_INDEX_PROVENANCE/catalogue-par-scope.tsv",
              encoding="utf-8") as flux:
        catalogue = {c["sha256"]: c for c in csv.DictReader(flux, delimiter="\t")}

    pdfs = sorted((racine / "01_EDUSCOL_OFFICIEL").rglob("*.pdf"))
    print(f"  PDF à lire : {len(pdfs)}", flush=True)

    resultats, sans_bandeau = [], 0
    for n, chemin in enumerate(pdfs, 1):
        sha = hashlib.sha256(chemin.read_bytes()).hexdigest()
        bandeau = lire_bandeau(chemin)
        ligne = catalogue.get(sha, {})
        if bandeau is None:
            sans_bandeau += 1
            resultats.append({"sha256": sha, "titre": ligne.get("titre", "")[:110],
                              "bandeau": None,
                              "niveau_catalogue": ligne.get("niveau")})
        else:
            bandeau["sha256"] = sha
            bandeau["titre"] = ligne.get("titre", "")[:110]
            bandeau["niveau_catalogue"] = ligne.get("niveau")
            resultats.append(bandeau)
        if n % 300 == 0:
            print(f"    {n}/{len(pdfs)} — sans bandeau : {sans_bandeau}", flush=True)

    args.sortie.write_text(json.dumps(resultats, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    avec = len(resultats) - sans_bandeau
    print("\n  ── COUVERTURE DU BANDEAU ──")
    print(f"  documents      : {len(resultats)}")
    print(f"  AVEC bandeau   : {avec} ({100 * avec / len(resultats):.1f} %)")
    print(f"  sans bandeau   : {sans_bandeau}")
    par = {}
    for r in resultats:
        if r.get("bandeau") is None and "granularite" not in r:
            par["aucun"] = par.get("aucun", 0) + 1
        else:
            g = r.get("granularite", "?")
            par[g] = par.get(g, 0) + 1
    print("  ── par granularité de portée ──")
    for g, c in sorted(par.items(), key=lambda x: -x[1]):
        print(f"    {g:22} {c:5}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
