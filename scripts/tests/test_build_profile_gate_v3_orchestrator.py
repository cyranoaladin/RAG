"""L'orchestrateur V3 transmet la matrice de servabilité, il ne la lit jamais."""

from __future__ import annotations

import re
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "go_live" / "build_profile_gate_v3.sh"


def test_l_orchestrateur_ne_lit_aucun_verdict_de_la_matrice() -> None:
    """Seul le producteur la charge, vérifiée par son empreinte (ADR-0059).

    Toute mention de la matrice est sa déclaration épinglée, son contrôle
    d'existence, ou son passage au producteur avec l'empreinte attendue."""
    lignes = SCRIPT.read_text(encoding="utf-8").splitlines()
    usages = [ligne.strip() for ligne in lignes if re.search(r"\$MATRIX\b|\bMATRIX=", ligne)]
    permis = (
        'MATRIX="docs/reports/handoff/servability_matrix_v1.json"',
        'for required in "$DECISION_SET" "$RECEIPT" "$ANCHOR" "$INDEX" "$EXCLUSION" "$MATRIX" \\',
        '--servability-matrix "$MATRIX" --servability-matrix-sha256 "$MATRIX_SHA"',
    )
    assert usages and all(u in permis for u in usages), usages
    assert re.search(r'MATRIX_SHA="[0-9a-f]{64}"', SCRIPT.read_text(encoding="utf-8"))
