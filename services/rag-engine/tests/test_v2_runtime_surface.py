"""Contrat de fermeture du runtime Nexus v2 LOT41U."""

from __future__ import annotations

import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.ingestor import api_v2

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
ADR = REPOSITORY_ROOT / "docs" / "adr" / "ADR-0024-runtime-v2-lecture-revue-fail-closed.md"
ENGINE_ROOT = REPOSITORY_ROOT / "services" / "rag-engine"
V2_DOCKERFILE = ENGINE_ROOT / "infra" / "Dockerfile.ingestor-v2"
DOCKERIGNORE = REPOSITORY_ROOT / ".dockerignore"
GO_LIVE_RUNBOOK = REPOSITORY_ROOT / "docs" / "runbooks" / "go_live.md"
ROOT_README = REPOSITORY_ROOT / "README.md"
ENGINE_PROD_README = ENGINE_ROOT / "README-PROD.md"
ENGINE_AGENTS = ENGINE_ROOT / "AGENTS.md"
V2_ENV_EXAMPLE = ENGINE_ROOT / "infra" / ".env.example"
MAKEFILE = ENGINE_ROOT / "Makefile"


@pytest.fixture(autouse=True)
def _clear_database_readiness_cache() -> None:
    api_v2._reset_database_readiness_cache()
    yield
    api_v2._reset_database_readiness_cache()


def _docker_context_copy_sources(instruction: str) -> set[str]:
    """Retourner uniquement les sources COPY venant du contexte de build."""
    tokens = shlex.split(instruction)
    if not tokens or tokens[0].upper() != "COPY":
        return set()

    operands: list[str] = []
    from_stage = False
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token.startswith("--from="):
            from_stage = True
        elif token == "--from":
            from_stage = True
            index += 1
        elif token in {"--chown", "--chmod", "--exclude"}:
            index += 1
        elif token.startswith(("--chown=", "--chmod=", "--exclude=")):
            pass
        elif token.startswith("--"):
            pass
        else:
            operands.append(token)
        index += 1

    if from_stage or len(operands) < 2:
        return set()
    return {source.rstrip("/") for source in operands[:-1]}


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
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://reviewer")
    monkeypatch.setattr(api_v2, "schema_head_003_ready", lambda _dsn: True)
    monkeypatch.setattr(api_v2, "retrieval_database_ready", lambda _dsn: True)
    monkeypatch.setattr(api_v2, "review_database_ready", lambda _dsn: True)
    monkeypatch.setattr(api_v2, "_model_artifacts_ready", lambda: True)
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


@pytest.mark.parametrize(
    ("variable", "value"),
    (
        ("PG_POOL_MIN_SIZE", "not-an-int"),
        ("PG_POOL_MAX_SIZE", "0"),
        ("PG_POOL_TIMEOUT_S", "nan"),
    ),
)
def test_health_rejects_invalid_pool_configuration(
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    value: str,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://reviewer")
    monkeypatch.setenv(variable, value)
    monkeypatch.setattr(
        api_v2,
        "_cached_database_readiness",
        lambda _rag_dsn, _review_dsn: (
            api_v2.CANONICAL_EMBED_DIM,
            True,
            True,
            True,
        ),
    )
    monkeypatch.setattr(api_v2, "_model_artifacts_ready", lambda: True)
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

    response = TestClient(api_v2.app).get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}


def test_health_caches_deep_database_readiness_for_a_bounded_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une rafale de sondes ne doit ouvrir qu'un cycle de connexions profond."""
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://reviewer")
    calls: list[str] = []
    now = [100.0]
    monkeypatch.setattr(api_v2.time, "monotonic", lambda: now[0])
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
        lambda _dsn: calls.append("dimension") or api_v2.CANONICAL_EMBED_DIM,
    )
    monkeypatch.setattr(
        api_v2,
        "schema_head_003_ready",
        lambda _dsn: calls.append("schema") or True,
    )
    monkeypatch.setattr(
        api_v2,
        "retrieval_database_ready",
        lambda _dsn: calls.append("retrieval") or True,
    )
    monkeypatch.setattr(
        api_v2,
        "review_database_ready",
        lambda _dsn: calls.append("review") or True,
    )
    monkeypatch.setattr(api_v2, "_model_artifacts_ready", lambda: True)

    client = TestClient(api_v2.app)
    assert client.get("/health").status_code == 200
    assert client.get("/health").status_code == 200
    assert calls == ["dimension", "schema", "retrieval", "review"]

    now[0] += api_v2._READINESS_CACHE_TTL_S + 0.001
    assert client.get("/health").status_code == 200
    assert calls == [
        "dimension",
        "schema",
        "retrieval",
        "review",
        "dimension",
        "schema",
        "retrieval",
        "review",
    ]


def test_health_cache_ttl_starts_after_a_slow_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une sonde plus longue que le TTL reste coalescée après son résultat."""
    now = [100.0]
    calls = [0]
    monkeypatch.setattr(api_v2.time, "monotonic", lambda: now[0])

    def slow_probe(_rag_dsn: str, _review_dsn: str) -> tuple[int, bool, bool, bool]:
        calls[0] += 1
        now[0] += api_v2._READINESS_CACHE_TTL_S * 2
        return (api_v2.CANONICAL_EMBED_DIM, True, True, True)

    monkeypatch.setattr(api_v2, "_probe_database_readiness", slow_probe)
    api_v2._reset_database_readiness_cache()

    first = api_v2._cached_database_readiness(
        "postgresql://reader", "postgresql://review"
    )
    second = api_v2._cached_database_readiness(
        "postgresql://reader", "postgresql://review"
    )

    assert first == second
    assert calls == [1]


@pytest.mark.parametrize(
    "failure",
    (
        "missing_rag_dsn",
        "missing_review_dsn",
        "schema",
        "dimension",
        "rag_database",
        "retrieval_privileges",
        "review_database",
        "model_artifacts",
    ),
)
def test_health_fails_closed_without_internal_details(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://secret-reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://secret-reviewer")
    monkeypatch.setattr(api_v2, "schema_head_003_ready", lambda _dsn: True)
    monkeypatch.setattr(api_v2, "retrieval_database_ready", lambda _dsn: True)
    monkeypatch.setattr(api_v2, "review_database_ready", lambda _dsn: True)
    monkeypatch.setattr(api_v2, "_model_artifacts_ready", lambda: True)
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
    if failure == "missing_rag_dsn":
        monkeypatch.delenv("PG_RAG_DSN")
    elif failure == "missing_review_dsn":
        monkeypatch.delenv("PG_REVIEW_DSN")
    elif failure == "schema":
        monkeypatch.setattr(api_v2, "schema_head_003_ready", lambda _dsn: False)
    elif failure == "dimension":
        monkeypatch.setattr(api_v2, "pgvector_dimension", lambda _dsn: 768)
    elif failure == "rag_database":
        monkeypatch.setattr(
            api_v2,
            "schema_head_003_ready",
            lambda _dsn: (_ for _ in ()).throw(RuntimeError("private database failure")),
        )
    elif failure == "retrieval_privileges":
        monkeypatch.setattr(api_v2, "retrieval_database_ready", lambda _dsn: False)
    elif failure == "review_database":
        monkeypatch.setattr(api_v2, "review_database_ready", lambda _dsn: False)
    else:
        monkeypatch.setattr(api_v2, "_model_artifacts_ready", lambda: False)

    response = TestClient(api_v2.app).get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}
    assert "secret-reader" not in response.text
    assert "secret-reviewer" not in response.text
    assert "private database" not in response.text
    assert "private artifact" not in response.text


def test_model_artifacts_are_fully_hashed_at_startup_not_on_public_health(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    embedding_root = Path("/models/e5-large")
    reranker_root = Path("/models/reranker")
    embedding_attestation = object()
    reranker_attestation = object()
    monkeypatch.setenv("RAG_EMBEDDING_MODEL_INVENTORY_SHA256", "1" * 64)
    monkeypatch.setenv("RAG_RERANKER_MODEL_INVENTORY_SHA256", "2" * 64)
    monkeypatch.setattr(
        api_v2,
        "verify_configured_embedding_artifact",
        lambda: calls.append("hash_embedding") or embedding_root,
    )
    monkeypatch.setattr(
        api_v2,
        "verify_configured_reranker_artifact",
        lambda: calls.append("hash_reranker") or reranker_root,
    )

    def attest(root: Path, *, expected_inventory_sha256: str) -> object:
        calls.append(f"attest:{root}:{expected_inventory_sha256}")
        return (
            embedding_attestation
            if root == embedding_root
            else reranker_attestation
        )

    monkeypatch.setattr(api_v2, "attest_verified_model_artifact", attest)

    assert api_v2._initialize_model_artifacts() == (
        embedding_attestation,
        reranker_attestation,
    )
    assert calls == [
        "hash_embedding",
        "hash_reranker",
        f"attest:{embedding_root}:{'1' * 64}",
        f"attest:{reranker_root}:{'2' * 64}",
    ]


def test_lifespan_installs_then_clears_the_startup_attestations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding_attestation = SimpleNamespace(root=Path("/models/e5-large"))
    reranker_attestation = SimpleNamespace(root=Path("/models/reranker"))
    attestations = (embedding_attestation, reranker_attestation)
    lifecycle_events: list[tuple[Path, Path] | str | None] = []
    monkeypatch.setattr(
        api_v2,
        "_initialize_model_artifacts",
        lambda: attestations,
    )
    monkeypatch.setattr(api_v2, "close_pool", lambda: None)
    monkeypatch.setattr(api_v2, "_model_artifacts_ready", lambda: True)
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "configure_verified_model_artifacts",
        lambda *, embedding_root, reranker_root: lifecycle_events.append(
            (embedding_root, reranker_root)
        ),
    )
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "preload_runtime_models",
        lambda: lifecycle_events.append("preload"),
        raising=False,
    )
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "reset_runtime_model_state",
        lambda: lifecycle_events.append(None),
    )

    with TestClient(api_v2.app):
        assert api_v2._model_artifact_attestations == attestations

    assert api_v2._model_artifact_attestations is None
    assert lifecycle_events == [
        (embedding_attestation.root, reranker_attestation.root),
        "preload",
        None,
    ]


def test_v2_middleware_records_bounded_request_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[tuple[str, str, int, float]] = []
    monkeypatch.setattr(api_v2.ingest_metrics, "METRICS_ENABLED", True)
    monkeypatch.setattr(
        api_v2.ingest_metrics,
        "record_http_request",
        lambda path, method, code, seconds: observations.append(
            (path, method, code, seconds)
        ),
    )

    response = TestClient(api_v2.app).get("/unmounted-user-controlled-path")

    assert response.status_code == 404
    assert len(observations) == 1
    path, method, code, seconds = observations[0]
    assert (path, method, code) == ("unmatched", "GET", 404)
    assert seconds >= 0


def test_v2_middleware_normalizes_custom_http_methods(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observations: list[tuple[str, str, int, float]] = []
    monkeypatch.setattr(api_v2.ingest_metrics, "METRICS_ENABLED", True)
    monkeypatch.setattr(
        api_v2.ingest_metrics,
        "record_http_request",
        lambda path, method, code, seconds: observations.append(
            (path, method, code, seconds)
        ),
    )

    response = TestClient(api_v2.app).request(
        "UNBOUNDED-CUSTOM-METHOD",
        "/health",
    )

    assert response.status_code == 405
    assert len(observations) == 1
    assert observations[0][:3] == ("/health", "other", 405)


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
        "model_artifact.py",
        "pg_pool.py",
        "readiness_db.py",
        "retrieval_hybrid_v2.py",
        "retrieval_pg_v2.py",
        "retrieval_readiness_v2.py",
        "retrieval_scope_v2.py",
        "retrieval_v2_endpoint.py",
        "review_readiness_v2.py",
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


def test_v2_docker_context_allowlist_contains_every_explicit_copy_source() -> None:
    allowlist = {
        line[1:].rstrip("/")
        for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
        if line.startswith("!")
    }
    copy_sources: set[str] = set()
    for line in V2_DOCKERFILE.read_text(encoding="utf-8").splitlines():
        if not line.lstrip().upper().startswith("COPY "):
            continue
        copy_sources.update(_docker_context_copy_sources(line))

    assert copy_sources
    assert copy_sources <= allowlist


def test_v2_docker_context_keeps_signed_scope_artifact_after_hard_denies() -> None:
    rules = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    artifact_rule = (
        "!packages/contracts/src/nexus_contracts/artifacts/"
        "pilot-retrieval-scope-v1.json"
    )

    assert artifact_rule in rules
    assert rules.index(artifact_rule) > rules.index("**/artifacts/**")


@pytest.mark.parametrize(
    ("instruction", "expected"),
    (
        ("COPY --chown=1000:1000 src/a.py src/b.py /app/", {"src/a.py", "src/b.py"}),
        ("COPY --chmod 0444 src/config.yml /app/config.yml", {"src/config.yml"}),
        ("COPY --link src/package /app/package", {"src/package"}),
        ("COPY --parents src/package /app/package", {"src/package"}),
        ("COPY --from=builder /wheel.whl /tmp/wheel.whl", set()),
        ("COPY --from builder /wheel.whl /tmp/wheel.whl", set()),
    ),
)
def test_docker_copy_parser_ignores_flags_and_stage_sources(
    instruction: str,
    expected: set[str],
) -> None:
    assert _docker_context_copy_sources(instruction) == expected


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
        "RAG_EMBEDDING_MODEL_INVENTORY_SHA256=",
        "RAG_RERANKER_MODEL_ARTIFACT_HOST_DIR=",
        "RAG_RERANKER_MODEL_INVENTORY_SHA256=",
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
