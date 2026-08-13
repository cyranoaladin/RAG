"""Contrat d'activation canonique Wave 0 après readiness exacte."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL = REPO_ROOT / "services" / "rag-engine" / "configs" / "rag_collections.yml"
ADR = REPO_ROOT / "docs" / "adr" / "ADR-0039-activation-wave0-apres-release-readiness.md"
WAVE0 = {
    "rag_nexus_maths_troisieme_tc",
    "rag_nexus_francais_troisieme_tc",
}


def _config() -> dict[str, object]:
    payload = yaml.safe_load(CANONICAL.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_only_the_two_wave0_collections_are_newly_activated() -> None:
    collections = _config()["collections"]
    assert isinstance(collections, dict)
    wave0_active = {
        name
        for name, definition in collections.items()
        if name in WAVE0
        and isinstance(definition, dict)
        and definition.get("instanciee") is True
    }

    assert wave0_active == WAVE0
    assert len(wave0_active) == 2


def test_activation_adr_binds_manifest_database_and_models() -> None:
    text = ADR.read_text(encoding="utf-8")

    assert re.search(r"Statut\s*:\s*Acceptée", text, re.IGNORECASE)
    assert "RAG_RELEASE_MANIFEST_SHA256" in text
    assert "transition_authorization.yml" in text
    assert "real_documents_allowed=false" in text
    assert "MISSING_ARTIFACTS=0" in text
    assert "MISSING_PLACEMENTS=0" in text
    assert "MISSING_CHUNKS=0" in text
    assert "FAKE_VECTOR_ROWS=0" in text
    assert "rag_nexus_maths_troisieme_tc" in text
    assert "rag_nexus_francais_troisieme_tc" in text
