"""Contrat de fermeture du runtime Nexus v2 LOT41U."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ADR = REPOSITORY_ROOT / "docs" / "adr" / "ADR-0024-runtime-v2-lecture-revue-fail-closed.md"


def test_adr_closes_ungoverned_v2_ingestion() -> None:
    assert ADR.is_file()
    content = ADR.read_text(encoding="utf-8")

    for required in (
        "Statut : Accepté",
        "lecture et revue",
        "quality → gate → review",
        "LOT41A",
        "LOT42",
        "003_profile_filtering",
        "legacy",
    ):
        assert required in content

    assert "aucun writer" in content.casefold()
