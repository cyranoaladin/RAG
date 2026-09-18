"""Tests for rehearsal runtime environment guard in retrieval_v2_endpoint.

Verifies:
- NEXUS_ENVIRONMENT defaults to 'production' (fail-closed)
- NEXUS_ENVIRONMENT='production' rejects unpromoted/rehearsal releases
- NEXUS_ENVIRONMENT='rehearsal' allows unpromoted/rehearsal releases for staging qualification
- Unknown values of NEXUS_ENVIRONMENT are strictly rejected
- Sealed V2 release and historical V1 registry hashes remain unmodified
- Safety invariants: current_switch=0, production_db_writes=0, production_deployments=0
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from nexus_contracts import (
    load_retrieval_scope_registry,
)

from src.ingestor import retrieval_v2_endpoint as endpoint
from src.ingestor.collection_config import load_collection_config

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parent.parent
RELEASE_REGISTRY_PATH = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
)
RELEASE_REGISTRY_V1_PATH = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry-v1.json"
)
V2_MANIFEST_PATH = (
    REPO_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v2/release-1b9eba0c0eb0ab13/profile_gate/production-profile-gate.release.json"
)
COLLECTION_CONFIG = ENGINE_ROOT / "configs" / "rag_collections.yml"

EXPECTED_V2_MANIFEST_SHA256 = (
    "e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864"
)
EXPECTED_ACTIVE_REGISTRY_SHA256 = (
    "82051777ba0bea6a316fa65ea7aca468f0d6187891d0c8ccb69c0156801ea5db"
)
EXPECTED_REGISTRY_V1_SHA256 = (
    "c9a844d4d2cc15caf9694b24ac53e77d65d50608d8a0daaef4963183d7d374fa"
)


def test_resolve_nexus_environment_default_is_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When NEXUS_ENVIRONMENT is absent or empty, it defaults to 'production'."""
    monkeypatch.delenv("NEXUS_ENVIRONMENT", raising=False)
    assert endpoint._resolve_nexus_environment() == "production"

    monkeypatch.setenv("NEXUS_ENVIRONMENT", "   ")
    assert endpoint._resolve_nexus_environment() == "production"


def test_resolve_nexus_environment_production_and_rehearsal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEXUS_ENVIRONMENT accepts 'production' and 'rehearsal' (case-insensitive)."""
    monkeypatch.setenv("NEXUS_ENVIRONMENT", "production")
    assert endpoint._resolve_nexus_environment() == "production"

    monkeypatch.setenv("NEXUS_ENVIRONMENT", "PRODUCTION")
    assert endpoint._resolve_nexus_environment() == "production"

    monkeypatch.setenv("NEXUS_ENVIRONMENT", "rehearsal")
    assert endpoint._resolve_nexus_environment() == "rehearsal"

    monkeypatch.setenv("NEXUS_ENVIRONMENT", "  REHEARSAL  ")
    assert endpoint._resolve_nexus_environment() == "rehearsal"


def test_resolve_nexus_environment_unknown_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown or arbitrary values for NEXUS_ENVIRONMENT are strictly rejected."""
    for invalid in ("staging", "development", "dev", "test", "sandbox", "true", "1"):
        monkeypatch.setenv("NEXUS_ENVIRONMENT", invalid)
        with pytest.raises(RuntimeError, match="unsupported NEXUS_ENVIRONMENT"):
            endpoint._resolve_nexus_environment()


def test_production_without_nexus_environment_refuses_unpromoted_v2_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production runtime without NEXUS_ENVIRONMENT refuses unpromoted V2 release."""
    registry_sha = hashlib.sha256(RELEASE_REGISTRY_PATH.read_bytes()).hexdigest()
    assert registry_sha == EXPECTED_ACTIVE_REGISTRY_SHA256

    monkeypatch.delenv("NEXUS_ENVIRONMENT", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(RELEASE_REGISTRY_PATH))
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", registry_sha)

    with pytest.raises(
        RuntimeError,
        match="cannot activate rehearsal or unpromotable release in production runtime",
    ):
        endpoint.validate_release_startup_configuration(
            load_retrieval_scope_registry(),
            load_collection_config(COLLECTION_CONFIG),
        )


def test_production_with_nexus_environment_production_refuses_unpromoted_v2_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Production runtime with NEXUS_ENVIRONMENT=production refuses unpromoted V2 release."""
    registry_sha = hashlib.sha256(RELEASE_REGISTRY_PATH.read_bytes()).hexdigest()

    monkeypatch.setenv("NEXUS_ENVIRONMENT", "production")
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(RELEASE_REGISTRY_PATH))
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", registry_sha)

    with pytest.raises(
        RuntimeError,
        match="cannot activate rehearsal or unpromotable release in production runtime",
    ):
        endpoint.validate_release_startup_configuration(
            load_retrieval_scope_registry(),
            load_collection_config(COLLECTION_CONFIG),
        )


def test_rehearsal_with_nexus_environment_rehearsal_accepts_v2_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NEXUS_ENVIRONMENT=rehearsal authorizes unpromoted release candidate for staging qualification."""
    registry_sha = hashlib.sha256(RELEASE_REGISTRY_PATH.read_bytes()).hexdigest()

    monkeypatch.setenv("NEXUS_ENVIRONMENT", "rehearsal")
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFESTS_JSON", raising=False)
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_PATH", str(RELEASE_REGISTRY_PATH))
    monkeypatch.setenv("RAG_RELEASE_REGISTRY_SHA256", registry_sha)

    registry = endpoint._configured_release_registry()
    assert registry is not None
    assert registry.manifests[0].expectation.release_id == "production-profile-gate-2026-2027-v2"
    assert registry.manifests[0].expectation.promotion_status == "NOT_PROMOTABLE"

    # The unpromoted guard must pass without raising
    endpoint._validate_unpromoted_release_guard(registry)


def test_v2_release_and_sealed_manifests_hashes_unmodified() -> None:
    """Verify that no V2 release candidate or historical registry hash is modified."""
    actual_v2_manifest_sha = hashlib.sha256(V2_MANIFEST_PATH.read_bytes()).hexdigest()
    assert actual_v2_manifest_sha == EXPECTED_V2_MANIFEST_SHA256

    actual_reg_sha = hashlib.sha256(RELEASE_REGISTRY_PATH.read_bytes()).hexdigest()
    assert actual_reg_sha == EXPECTED_ACTIVE_REGISTRY_SHA256

    actual_v1_sha = hashlib.sha256(RELEASE_REGISTRY_V1_PATH.read_bytes()).hexdigest()
    assert actual_v1_sha == EXPECTED_REGISTRY_V1_SHA256


def test_safety_invariants() -> None:
    """Verify safety invariants in go_live_readiness_state.json."""
    state_file = REPO_ROOT / "docs/reports/go_live/go_live_readiness_state.json"
    assert state_file.is_file()
    state = json.loads(state_file.read_text(encoding="utf-8"))
    assert state.get("current_switch") == 0
    assert state.get("production_db_writes") == 0
    assert state.get("production_deployments") == 0
