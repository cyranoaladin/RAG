"""Contrat de fermeture du runtime Nexus v2 LOT41U."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.ingestor import api_v2

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ADR = REPOSITORY_ROOT / "docs" / "adr" / "ADR-0024-runtime-v2-lecture-revue-fail-closed.md"
ENGINE_ROOT = REPOSITORY_ROOT / "services" / "rag-engine"
V2_DOCKERFILE = ENGINE_ROOT / "infra" / "Dockerfile.ingestor-v2"
GO_LIVE_RUNBOOK = REPOSITORY_ROOT / "docs" / "runbooks" / "go_live.md"
ROOT_README = REPOSITORY_ROOT / "README.md"
ENGINE_PROD_README = ENGINE_ROOT / "README-PROD.md"
ENGINE_AGENTS = ENGINE_ROOT / "AGENTS.md"
V2_ENV_EXAMPLE = ENGINE_ROOT / "infra" / ".env.example"
MAKEFILE = ENGINE_ROOT / "Makefile"


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
    documentation_routes = {"/docs", "/redoc", "/openapi.json"}
    routes = {
        route.path for route in api_v2.app.routes if route.path not in documentation_routes
    }

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


def test_lot41u_plan_contains_no_machine_local_absolute_path() -> None:
    plan = (
        REPOSITORY_ROOT
        / "docs"
        / "superpowers"
        / "plans"
        / "2026-08-02-lot41u-ingestion-runtime-hardening.md"
    ).read_text(encoding="utf-8")

    assert "/home/" not in plan
    assert "/Users/" not in plan


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


def test_v2_dockerfile_copies_only_the_read_review_runtime() -> None:
    content = V2_DOCKERFILE.read_text(encoding="utf-8")

    assert content.startswith(
        "FROM python:3.11-slim@sha256:"
        "db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93"
    )
    assert "pip install --upgrade pip==26.2" in content
    assert 'CMD ["uvicorn", "api_v2:app"' in content
    assert "requirements.runtime-v2.txt" in content
    assert "requirements.txt" not in content.replace("requirements.runtime-v2.txt", "")
    assert "requirements.v2.txt" not in content
    assert "COPY services/rag-engine/src/ingestor/ ./" not in content
    for required_module in (
        "api_v2.py",
        "collection_config.py",
        "embedding_contract.py",
        "identity_v2.py",
        "metrics.py",
        "pg_pool.py",
        "readiness_db.py",
        "retrieval_hybrid_v2.py",
        "retrieval_pg_v2.py",
        "retrieval_scope_v2.py",
        "retrieval_v2_endpoint.py",
        "review_v2_endpoint.py",
        "reranker_contract.py",
        "schema_readiness_v2.py",
        "security_v2.py",
    ):
        assert f"services/rag-engine/src/ingestor/{required_module}" in content
    assert "infra/postgres/migrations/ /app/migrations/" in content
    assert (
        "infra/postgres/schema_head_003_fingerprints.env "
        "/app/schema_head_003_fingerprints.env" in content
    )
    for forbidden_module in (
        "api.py",
        "admin_api.py",
        "ingest_v2.py",
        "ingest_v2_endpoint.py",
        "tasks.py",
        "database.py",
    ):
        assert f"src/ingestor/{forbidden_module}" not in content


def test_v2_runtime_dependencies_exclude_writer_and_remote_source_stacks() -> None:
    requirements = (
        ENGINE_ROOT / "src" / "ingestor" / "requirements.runtime-v2.txt"
    ).read_text(encoding="utf-8").casefold()

    for forbidden in (
        "chromadb",
        "celery",
        "redis",
        "ollama",
        "requests",
        "httpx",
        "unstructured",
        "pypdf",
        "python-docx",
        "beautifulsoup",
        "langchain",
        "python-multipart",
    ):
        assert forbidden not in requirements

    assert "--extra-index-url https://download.pytorch.org/whl/cpu" in requirements
    assert "torch==2.4.1+cpu" in requirements
    assert "transformers==4.44.2" in requirements


def test_canonical_operations_docs_describe_the_closed_v2_runtime() -> None:
    runbook = GO_LIVE_RUNBOOK.read_text(encoding="utf-8")
    root_current = ROOT_README.read_text(encoding="utf-8").split(
        "## Sommaire", maxsplit=1
    )[0]
    engine_current = ENGINE_PROD_README.read_text(encoding="utf-8").split(
        "## Archive LOT19", maxsplit=1
    )[0]
    agents = ENGINE_AGENTS.read_text(encoding="utf-8")
    env_example = V2_ENV_EXAMPLE.read_text(encoding="utf-8")

    for required in (
        "GO_LIVE: NO_GO",
        "Cockpit BFF",
        "LOT41A",
        "LOT42",
        "003_profile_filtering",
        "quality → gate → review",
        "PG_RAG_DSN",
        "PG_REVIEW_DSN",
    ):
        assert required in runbook

    for forbidden in (
        "/ingest/v2",
        "docker-compose.prod.yml",
        "RAG_ADMIN_TOKEN",
        "RAG_REVIEWER_TOKEN",
        "ollama pull",
        "Chroma",
    ):
        assert forbidden not in runbook

    for current in (root_current, engine_current, agents):
        assert "runtime v2" in current
        assert "lecture/revue" in current
        assert "api_v2:app" in current
        assert "Cockpit BFF" in current

    assert "ChromaDB (`docker-compose.yml` / `docker-compose.prod.yml`)" not in agents
    assert "Ollama (`nomic-embed-text`), 768 dimensions" not in agents
    for required_env in (
        "PGVECTOR_PASSWORD=",
        "PG_RAG_DSN=",
        "PG_REVIEW_DSN=",
        "RAG_BFF_SERVICE_TOKEN=",
        "NEXUS_INTERNAL_TOKEN_SECRET=",
        "RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR=",
        "RAG_RERANKER_MODEL_ARTIFACT_HOST_DIR=",
    ):
        assert required_env in env_example
    for forbidden_env in (
        "LEGACY_ADMIN_API_TOKEN=",
        "RAG_ADMIN_TOKEN=",
        "RAG_INGEST_AGENT_TOKEN=",
        "INGESTOR_API_TOKEN=",
    ):
        assert forbidden_env not in env_example

    assert "envsubst '${RAG_API_EXTERNAL_DOMAIN} ${NGINX_API_PORT}'" in runbook
    assert "envsubst < infra/nginx/rag-api.conf.template" not in runbook


def test_integration_make_target_exposes_the_ingestor_package() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert (
        "test-integration: install-dev\n"
        "\tPYTHONPATH=src $(PYTEST) tests/integration -q"
    ) in makefile
