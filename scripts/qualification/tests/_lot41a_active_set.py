"""Quelles autorisations LOT41A sont ACTIVES, et lesquelles sont remplacées.

Avant ADR-0058, le répertoire `governance/authorizations/` ne contenait que
des autorisations en vigueur : compter les fichiers suffisait.

Depuis le renouvellement, il en contient deux séries. Les onze d'origine ne
sont ni supprimées ni modifiées — la base a enregistré leur chemin canonique,
et le déplacer rendrait l'historique invérifiable. Elles sont **remplacées**,
ce qui n'est pas la même chose qu'absentes.

La carte de renouvellement est le seul endroit qui dit laquelle remplace
laquelle. Ce module la lit, plutôt que de laisser chaque épreuve deviner par
un suffixe.
"""

from __future__ import annotations

import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[3]
AUTORISATIONS = RACINE / "governance/authorizations"
CARTE = RACINE / "docs/governance/lot41a_staging_v2_renewal_map.json"


def identifiants_remplaces() -> frozenset[str]:
    """Les identifiants qu'un renouvellement a éteints. Vide s'il n'y en a pas."""
    if not CARTE.is_file():
        return frozenset()
    document = json.loads(CARTE.read_text(encoding="utf-8"))
    return frozenset(
        entree["ancien"]["authorization_id"] for entree in document["mapping"]
    )


def artefacts_actifs(prefixe: str) -> list[Path]:
    """Les artefacts en vigueur, remplacés exclus, triés."""
    remplaces = identifiants_remplaces()
    return sorted(
        chemin
        for chemin in AUTORISATIONS.glob(f"{prefixe}*.json")
        if chemin.stem not in remplaces
    )


__all__ = ["artefacts_actifs", "identifiants_remplaces"]
