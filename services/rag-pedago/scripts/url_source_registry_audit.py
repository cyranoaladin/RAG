#!/usr/bin/env python3
"""Audit hors ligne du registre des URL sources versionné.

Recalcule les compteurs depuis les entrées et refuse le registre si une
affirmation n'est pas soutenue. Les compteurs publiés dans le fichier ne
sont jamais crus : ils sont comparés au recalcul, pour qu'un chiffre ne
puisse pas être édité à la main sans que l'audit le voie.

Aucun accès réseau, aucune racine machine-locale : le chemin par défaut
est dérivé de l'emplacement de ce fichier.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

RACINE_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE_SERVICE))

from rag_pedago.governance.url_source_registry import (  # noqa: E402
    RegistreUrlSource,
    RegistreUrlSourceError,
    charger_registre,
    verifier_registre,
)

CHEMIN_EVIDENCE = (
    RACINE_SERVICE
    / "configs"
    / "prerentree_2026_2027"
    / "multilevel_currentness_evidence.yml"
)

CHEMIN_PAR_DEFAUT = (
    RACINE_SERVICE
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "multilevel"
    / "url_source_registry.json"
)


def _artefacts_sans_provenance(registre: RegistreUrlSource) -> set[str]:
    """Artefacts scellés du périmètre qu'aucune entrée du registre ne couvre."""
    couverts = {
        artefact for entree in registre.entrees for artefact in entree.artefacts_perimetre
    }
    evidence = json.loads(CHEMIN_EVIDENCE.read_text(encoding="utf-8"))["artifacts"]
    return {a["content_sha256"] for a in evidence} - couverts


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__)
    analyseur.add_argument("--registre", type=Path, default=CHEMIN_PAR_DEFAUT)
    args = analyseur.parse_args()

    if not args.registre.exists():
        print(f"REGISTRE_ABSENT {args.registre}")
        return 1

    registre = charger_registre(args.registre)
    try:
        compteurs = verifier_registre(registre)
    except RegistreUrlSourceError as refus:
        print(f"REGISTRE_REFUSE {refus}")
        return 1

    publies = json.loads(args.registre.read_text(encoding="utf-8")).get("compteurs")
    if publies != compteurs:
        print(f"COMPTEURS_PUBLIES_DIVERGENTS publiés={publies} recalculés={compteurs}")
        return 1

    # Une URL bien comptée qui ne porte plus la provenance d'aucun artefact
    # laisserait le corpus scellé sans origine : le registre serait cohérent
    # avec lui-même et muet sur ce qu'il est censé documenter.
    orphelins = _artefacts_sans_provenance(registre)
    if orphelins:
        print(
            f"ARTEFACTS_SANS_PROVENANCE {len(orphelins)} "
            f"(premier : {sorted(orphelins)[0]})"
        )
        return 1

    for cle in sorted(compteurs):
        print(f"{cle:24s}: {compteurs[cle]}")
    print("VERDICT : REGISTRE DES URL SOURCES COHÉRENT, AUCUNE URL NON COMPTÉE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
