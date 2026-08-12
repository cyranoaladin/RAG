"""Contrat statique du principal E2E d'ingestion multi-collections."""

from __future__ import annotations

from pathlib import Path

SERVICE_ROOT = Path(__file__).resolve().parents[1]
E2E = SERVICE_ROOT / "tests" / "integration" / "test_multilevel_real_ingestion.py"


def test_multilevel_e2e_uses_real_governed_runtime() -> None:
    source = E2E.read_text(encoding="utf-8")

    assert "TARGET_COLLECTIONS = 10" in source
    assert "EXPECTED_ARTIFACTS = 11" in source
    assert "EXPECTED_CHUNKS = 359" in source
    assert "VerifiedE5EmbeddingProvider.from_artifact" in source
    assert "run_worker_iteration" in source
    assert "run_publication_resume_iteration" in source
    assert "authorize_scope_main" in source
    assert "attest_main" in source
    assert "validate_release_readiness" in source
    assert "embedded is False" in source
    assert "publish_governed_artifact" not in source
    assert "CallableEmbeddingProvider" not in source
    assert "debug/deterministic" not in source


def test_multilevel_e2e_is_opt_in_and_uses_real_postgresql() -> None:
    source = E2E.read_text(encoding="utf-8")

    assert "NEXUS_MULTILEVEL_PDF_MIRROR" in source
    assert "NEXUS_REQUIRE_DOCKER" in source
    assert "start_ingestion_control_postgres" in source
    assert "docker" in source
    assert "pgvector" in source.lower()
