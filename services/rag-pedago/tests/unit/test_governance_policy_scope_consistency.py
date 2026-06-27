from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
PEDAGO_INTERFACE = ROOT / "configs/pedago_interface_contract.yml"
SOURCE_ADMISSION = ROOT / "configs/source_admission_policy.yml"
TRANSITION_AUTHORIZATION = ROOT / "configs/transition_authorization.yml"

SCOPED_ALLOWED_FLAGS = {
    "pdf_allowed",
    "parsing_allowed",
    "network_allowed",
    "data_staging_allowed",
    "chunking_allowed",
    "embeddings_allowed",
    "ingestion_allowed",
    "server_start_allowed",   # ADR-0011 — lecture seule
    "runtime_api_allowed",    # ADR-0011 — lecture seule
}
RUNTIME_AND_INGESTION_FLAGS = {
    "real_documents_allowed",
    "qdrant_allowed",
    "curated_ingestion_allowed",
}


def _load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def test_governance_related_locks_have_explicit_scope_boundaries() -> None:
    pedago = _load(PEDAGO_INTERFACE)
    admission = _load(SOURCE_ADMISSION)
    transition = _load(TRANSITION_AUTHORIZATION)

    for flag in RUNTIME_AND_INGESTION_FLAGS:
        assert pedago[flag] is False, f"{flag} should be False in pedago"
        assert admission[flag] is False, f"{flag} should be False in admission"
        assert transition[flag] is False, f"{flag} should be False in transition"

    for flag in SCOPED_ALLOWED_FLAGS:
        assert pedago[flag] is True
        assert transition[flag] is True
        assert admission[flag] is False

    assert admission["status"] == "metadata_only_source_admission_policy"
    assert admission["pedago_interface_ref"] == pedago["contract_id"]
    assert transition["source_admission_policy_ref"] == admission["policy_id"]
    assert transition["pedago_interface_ref"] == pedago["contract_id"]
    assert any(
        case.get("authorization_case_id") == "network_fetch_authorized_adr_0004"
        and case.get("real_corpus_authorized") is False
        and case.get("pipeline_authorized") is False
        for case in transition["authorization_cases"]
    )
