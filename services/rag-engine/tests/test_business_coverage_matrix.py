"""Verifie que le rapport de couverture metier existe et couvre les niveaux,
matieres et statuts attendus.  Ne fabrique aucune collection : il controle
uniquement la transparence de la documentation."""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MATRIX_PATH = REPO_ROOT / "docs" / "reports" / "lot_27_business_coverage_matrix.md"

REQUIRED_TERMS = [
    # Niveaux
    "3e",
    "Seconde",
    "Premiere",
    "Terminale",
    # Examens
    "DNB",
    "EAF",
    "Grand Oral",
    # Matieres
    "Mathematiques",
    "Francais",
    "Physique-Chimie",
    "NSI",
    "SVT",
    "SES",
    "STMG",
    "Quarantaine",
]

STATUT_TERMS = ["declaree", "instanciee", "retrievable"]


def test_matrix_file_exists() -> None:
    assert MATRIX_PATH.exists(), f"Rapport de couverture absent : {MATRIX_PATH}"


@pytest.mark.parametrize("term", REQUIRED_TERMS)
def test_matrix_mentions_term(term: str) -> None:
    content = MATRIX_PATH.read_text(encoding="utf-8")
    assert term in content, f"Terme attendu absent du rapport : {term}"


@pytest.mark.parametrize("statut", STATUT_TERMS)
def test_matrix_distinguishes_statut(statut: str) -> None:
    content = MATRIX_PATH.read_text(encoding="utf-8")
    assert statut in content.lower(), (
        f"Le rapport doit distinguer le statut '{statut}'"
    )
