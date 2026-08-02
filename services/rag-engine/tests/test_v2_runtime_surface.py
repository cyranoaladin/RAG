"""Contrat de fermeture du runtime Nexus v2 LOT41U."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.ingestor import api_v2

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


def test_v2_application_exposes_only_the_governed_runtime_surface() -> None:
    routes = {route.path for route in api_v2.app.routes}

    assert routes == {
        "/health",
        "/metrics",
        "/search/v2",
        "/chat",
        "/collections/v2",
        "/catalogue/v2",
        "/collections/readiness",
        "/review/v2/queue",
        "/review/v2/decide",
    }
    for forbidden_prefix in ("/ingest", "/admin", "/cache", "/stats", "/rag"):
        assert not any(path.startswith(forbidden_prefix) for path in routes)


def test_health_is_ready_only_for_schema_003_and_canonical_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://reader")
    monkeypatch.setattr(api_v2, "schema_head_003_ready", lambda _dsn: True)
    monkeypatch.setattr(
        api_v2,
        "declared_embedding_model",
        lambda: api_v2.CANONICAL_EMBED_MODEL,
    )
    monkeypatch.setattr(
        api_v2,
        "declared_embedding_dim",
        lambda: api_v2.CANONICAL_EMBED_DIM,
    )
    monkeypatch.setattr(
        api_v2,
        "pgvector_dimension",
        lambda _dsn: api_v2.CANONICAL_EMBED_DIM,
    )

    response = TestClient(api_v2.app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "schema_head": "003_profile_filtering",
        "embedding_model": "intfloat/multilingual-e5-large",
        "embedding_dim_declared": 1024,
        "pgvector_dim": 1024,
    }


@pytest.mark.parametrize("failure", ("missing_dsn", "schema", "dimension", "database"))
def test_health_fails_closed_without_internal_details(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://secret-reader")
    monkeypatch.setattr(api_v2, "schema_head_003_ready", lambda _dsn: True)
    monkeypatch.setattr(
        api_v2,
        "declared_embedding_model",
        lambda: api_v2.CANONICAL_EMBED_MODEL,
    )
    monkeypatch.setattr(
        api_v2,
        "declared_embedding_dim",
        lambda: api_v2.CANONICAL_EMBED_DIM,
    )
    monkeypatch.setattr(
        api_v2,
        "pgvector_dimension",
        lambda _dsn: api_v2.CANONICAL_EMBED_DIM,
    )
    if failure == "missing_dsn":
        monkeypatch.delenv("PG_RAG_DSN")
    elif failure == "schema":
        monkeypatch.setattr(api_v2, "schema_head_003_ready", lambda _dsn: False)
    elif failure == "dimension":
        monkeypatch.setattr(api_v2, "pgvector_dimension", lambda _dsn: 768)
    else:
        monkeypatch.setattr(
            api_v2,
            "schema_head_003_ready",
            lambda _dsn: (_ for _ in ()).throw(RuntimeError("private database failure")),
        )

    response = TestClient(api_v2.app).get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}
    assert "secret-reader" not in response.text
    assert "private database" not in response.text


def test_metrics_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_v2.ingest_metrics, "METRICS_ENABLED", False)

    response = TestClient(api_v2.app).get("/metrics")

    assert response.status_code == 404
