"""Contrat de fermeture du runtime Nexus v2 LOT41U."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shlex
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from src.ingestor import api_v2, pg_pool, readiness_db

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
V2_COMPOSE = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"
MAKEFILE = ENGINE_ROOT / "Makefile"

#: Clé porteuse de test. Le runtime v2 exige désormais un registre de clés
#: (``ingestor.api_scopes``) : sans lui, il se ferme au démarrage. La valeur
#: n'existe que dans ce fichier de test et ne configure aucun déploiement.
API_CLIENT_KEY = "surface-v2-cle-porteuse-de-test-0123456789"
API_CLIENT_REGISTRY = json.dumps(
    [
        {
            "client_id": "surface-v2",
            "token_sha256": hashlib.sha256(API_CLIENT_KEY.encode("utf-8")).hexdigest(),
            "scopes": ["rag:search", "rag:read-source", "rag:admin"],
        }
    ]
)
API_CLIENT_HEADER = {"X-RAG-API-Key": API_CLIENT_KEY}


@pytest.fixture(autouse=True)
def _clear_database_readiness_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        api_v2,
        "validate_bff_service_configuration",
        lambda: None,
        raising=False,
    )
    monkeypatch.setattr(
        api_v2,
        "load_identity_verifier_config",
        lambda: SimpleNamespace(artifacts={"test-scope": object()}),
        raising=False,
    )
    monkeypatch.setattr(
        api_v2,
        "validate_collection_catalogue_v2",
        lambda: None,
        raising=False,
    )
    monkeypatch.setattr(
        api_v2,
        "validate_pilot_scope_catalogue_alignment",
        lambda _artifact, _catalogue: None,
        raising=False,
    )
    monkeypatch.setattr(
        api_v2,
        "validate_scope_registry_catalogue_alignment",
        lambda _artifacts, _catalogue: None,
        raising=False,
    )
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "validate_release_startup_configuration",
        lambda _artifacts, _catalogue: None,
    )
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "validate_configured_release_database",
        lambda: None,
    )
    monkeypatch.setattr(
        api_v2,
        "postgres_database_authorities_share_instance",
        lambda _rag_dsn, _review_dsn: True,
        raising=False,
    )
    monkeypatch.delenv("RAG_API_CLIENTS_FILE", raising=False)
    monkeypatch.setenv("RAG_API_CLIENTS", API_CLIENT_REGISTRY)
    api_v2._reset_database_readiness_cache()
    yield
    api_v2._reset_database_readiness_cache()


def _api_key_registry(scopes: list[str]) -> str:
    return json.dumps(
        [
            {
                "client_id": "surface-v2",
                "token_sha256": hashlib.sha256(
                    API_CLIENT_KEY.encode("utf-8")
                ).hexdigest(),
                "scopes": scopes,
            }
        ]
    )


def test_une_route_metier_sans_cle_porteuse_est_refusee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le credential BFF seul ne suffit plus : la portee est une seconde porte."""
    service_token = "lot41u-runtime-bff-service-token-32-bytes"
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", service_token)
    monkeypatch.setattr(
        api_v2,
        "_cached_database_readiness",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("une requete non autorisee ne doit pas sonder PostgreSQL")
        ),
    )

    response = TestClient(api_v2.app).get(
        "/taxonomy/v2",
        headers={"Authorization": f"Bearer {service_token}"},
    )

    assert response.status_code == 401


def test_une_cle_sans_la_portee_exigee_est_refusee(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`rag:ingest` n'ouvre pas le retrieval : les portees sont disjointes."""
    service_token = "lot41u-runtime-bff-service-token-32-bytes"
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", service_token)
    monkeypatch.setenv("RAG_API_CLIENTS", _api_key_registry(["rag:ingest"]))
    monkeypatch.setattr(
        api_v2,
        "_cached_database_readiness",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("une requete non autorisee ne doit pas sonder PostgreSQL")
        ),
    )

    response = TestClient(api_v2.app).get(
        "/taxonomy/v2",
        headers={"Authorization": f"Bearer {service_token}", **API_CLIENT_HEADER},
    )

    assert response.status_code == 403


def test_le_client_authentifie_est_depose_pour_le_journal_d_acces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le journal d'accès attribue une requête à un client, pas à un jeton.

    Le middleware résout la clé porteuse une seule fois et dépose le client
    sur la requête ; la route le relit. Sans ce relais, chaque ligne de
    journal serait anonyme — ou pire, exigerait de relire le jeton.
    """
    from src.ingestor import retrieval_v2_endpoint

    service_token = "lot41u-runtime-bff-service-token-32-bytes"
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", service_token)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)
    observed: dict[str, object] = {}

    async def route(request: Request) -> JSONResponse:
        observed["client_id"] = retrieval_v2_endpoint._calling_client_id(request)
        observed["scopes"] = retrieval_v2_endpoint._calling_client_scopes(request)
        return JSONResponse({"ok": True})

    scope = dict(_business_request("/search/v2").scope)
    scope["headers"] = [
        (b"authorization", f"Bearer {service_token}".encode()),
        (b"x-rag-api-key", API_CLIENT_KEY.encode()),
    ]

    response = asyncio.run(api_v2._metrics_middleware(Request(scope), route))

    assert response.status_code == 200
    assert observed["client_id"] == "surface-v2"
    assert observed["scopes"] == ("rag:admin", "rag:read-source", "rag:search")


def test_chaque_route_metier_montee_declare_une_portee_d_api() -> None:
    """Une route exposée sans portée déclarée serait une route sans porte."""
    for route in api_v2._ALLOWED_BUSINESS_ROUTES:
        assert api_v2.required_scope_for_route(route) is not None, route


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
        "/taxonomy/v2",
        "/corpora/servable/v1",
        "/corpora/servable/v1/{manifest_sha256}",
        "/chat",
        "/collections/v2",
        "/catalogue/v2",
        "/collections/readiness",
        "/review/v2/queue",
        "/review/v2/decide",
    }
    for forbidden_prefix in ("/ingest", "/admin", "/cache", "/stats", "/rag"):
        assert not any(path.startswith(forbidden_prefix) for path in routes)


def test_v2_image_packages_release_readiness_runtime() -> None:
    """L'image aplatie doit embarquer chaque import de l'API activée."""
    dockerfile = V2_DOCKERFILE.read_text(encoding="utf-8")

    assert (
        "COPY services/rag-engine/src/ingestor/release_readiness.py "
        "/app/release_readiness.py"
    ) in dockerfile


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


def test_health_is_ready_only_for_schema_004_and_canonical_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://reviewer")
    monkeypatch.setattr(api_v2, "schema_head_004_ready", lambda _dsn: True)
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
        "schema_head": "004_artifact_placements",
        "embedding_model": "intfloat/multilingual-e5-large",
        "embedding_dim_declared": 1024,
        "pgvector_dim": 1024,
    }


def test_health_binds_the_identity_registry_to_the_mounted_catalogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://reviewer")
    artifacts = {"scope-a": object(), "scope-b": object()}
    catalogue = object()
    calls: list[tuple[object, object]] = []
    monkeypatch.setattr(
        api_v2,
        "load_identity_verifier_config",
        lambda: SimpleNamespace(artifacts=artifacts),
    )
    monkeypatch.setattr(
        api_v2,
        "validate_collection_catalogue_v2",
        lambda: catalogue,
    )
    monkeypatch.setattr(
        api_v2,
        "validate_scope_registry_catalogue_alignment",
        lambda loaded_artifacts, loaded_catalogue: calls.append(
            (loaded_artifacts, loaded_catalogue)
        ),
        raising=False,
    )
    monkeypatch.setattr(
        api_v2,
        "_cached_database_readiness",
        lambda _rag_dsn, _review_dsn: (
            api_v2.CANONICAL_EMBED_DIM,
            True,
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

    assert response.status_code == 200
    assert calls == [(artifacts, catalogue)]


@pytest.mark.parametrize(
    ("variable", "value"),
    (
        ("PG_POOL_MIN_SIZE", "not-an-int"),
        ("PG_POOL_MAX_SIZE", "0"),
        ("PG_POOL_TIMEOUT_S", "nan"),
        ("PG_CONNECT_TIMEOUT_S", "0"),
        ("PG_STATEMENT_TIMEOUT_MS", "0"),
        ("PG_LOCK_TIMEOUT_MS", "7001"),
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


@pytest.mark.parametrize(
    "authority_probe",
    (
        "validate_bff_service_configuration",
        "load_identity_verifier_config",
        "validate_collection_catalogue_v2",
    ),
)
def test_health_rejects_invalid_runtime_authorities_and_catalogue(
    monkeypatch: pytest.MonkeyPatch,
    authority_probe: str,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://reviewer")
    monkeypatch.setattr(
        api_v2,
        "_cached_database_readiness",
        lambda _rag_dsn, _review_dsn: (
            api_v2.CANONICAL_EMBED_DIM,
            True,
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
    monkeypatch.setattr(
        api_v2,
        authority_probe,
        lambda: (_ for _ in ()).throw(RuntimeError("private configuration")),
    )

    response = TestClient(api_v2.app).get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}
    assert "private configuration" not in response.text


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
        "schema_head_004_ready",
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

    def slow_probe(
        _rag_dsn: str,
        _review_dsn: str,
    ) -> tuple[int, bool, bool, bool, bool]:
        calls[0] += 1
        now[0] += api_v2._READINESS_CACHE_TTL_S * 2
        return (api_v2.CANONICAL_EMBED_DIM, True, True, True, True)

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


def test_deep_database_readiness_uses_one_budget_below_health_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[object] = []

    class _Budget:
        def __init__(self, outer_deadline: float | None) -> None:
            observed.append(outer_deadline)

        def __enter__(self) -> None:
            observed.append("enter")

        def __exit__(self, *_args: object) -> None:
            observed.append("exit")

    monkeypatch.setattr(api_v2, "readiness_database_budget", _Budget, raising=False)
    monkeypatch.setattr(
        api_v2,
        "postgres_database_authorities_share_instance",
        lambda _rag_dsn, _review_dsn: True,
        raising=False,
    )
    monkeypatch.setattr(api_v2, "pgvector_dimension", lambda _dsn: 1024)
    monkeypatch.setattr(api_v2, "schema_head_004_ready", lambda _dsn: True)
    monkeypatch.setattr(api_v2, "retrieval_database_ready", lambda _dsn: True)
    monkeypatch.setattr(api_v2, "review_database_ready", lambda _dsn: True)

    assert api_v2._probe_database_readiness("reader", "reviewer") == (
        1024,
        True,
        True,
        True,
        True,
    )
    assert observed == [None, "enter", "exit"]
    assert api_v2.READINESS_AGGREGATE_BUDGET_MS < 10_000
    assert api_v2._READINESS_LOCK_TIMEOUT_S < 10.0


def test_health_follower_wait_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[float] = []

    class _BusyLock:
        def acquire(self, *, timeout: float) -> bool:
            observed.append(timeout)
            return False

        def release(self) -> None:
            raise AssertionError("unacquired lock must not be released")

    original_lock = api_v2._database_readiness_cache_lock
    api_v2._database_readiness_cache_lock = _BusyLock()  # type: ignore[assignment]
    try:
        with pytest.raises(RuntimeError, match="database readiness unavailable"):
            api_v2._cached_database_readiness("reader", "reviewer")
    finally:
        api_v2._database_readiness_cache_lock = original_lock

    assert observed == [api_v2._READINESS_LOCK_TIMEOUT_S]


def test_business_readiness_follower_wait_uses_the_request_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    observed: list[float] = []
    monkeypatch.setattr(pg_pool.time, "monotonic", lambda: now[0])

    class _BusyLock:
        def acquire(self, *, timeout: float) -> bool:
            observed.append(timeout)
            return False

        def release(self) -> None:
            raise AssertionError("unacquired lock must not be released")

    original_lock = api_v2._database_readiness_cache_lock
    api_v2._database_readiness_cache_lock = _BusyLock()  # type: ignore[assignment]
    try:
        with pg_pool.runtime_request_budget(1_000):
            with pytest.raises(RuntimeError, match="database readiness unavailable"):
                api_v2._cached_database_readiness("reader", "reviewer")
    finally:
        api_v2._database_readiness_cache_lock = original_lock

    assert observed == [1.0]


def test_deep_readiness_inherits_the_runtime_request_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    observed: list[int] = []
    monkeypatch.setattr(pg_pool.time, "monotonic", lambda: now[0])

    def ready(*_args: object) -> bool:
        observed.append(readiness_db.remaining_readiness_budget_ms())
        return True

    monkeypatch.setattr(
        api_v2,
        "postgres_database_authorities_share_instance",
        ready,
    )
    monkeypatch.setattr(
        api_v2,
        "pgvector_dimension",
        lambda _dsn: observed.append(readiness_db.remaining_readiness_budget_ms())
        or api_v2.CANONICAL_EMBED_DIM,
    )
    monkeypatch.setattr(api_v2, "schema_head_004_ready", ready)
    monkeypatch.setattr(api_v2, "retrieval_database_ready", ready)
    monkeypatch.setattr(api_v2, "review_database_ready", ready)

    with pg_pool.runtime_request_budget(1_000) as request_deadline:
        assert request_deadline == 101.0
        assert api_v2._probe_database_readiness("reader", "reviewer") == (
            api_v2.CANONICAL_EMBED_DIM,
            True,
            True,
            True,
            True,
        )

    assert observed == [1_000, 1_000, 1_000, 1_000, 1_000]


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
        "database_identity",
        "model_artifacts",
    ),
)
def test_health_fails_closed_without_internal_details(
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://secret-reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://secret-reviewer")
    monkeypatch.setattr(api_v2, "schema_head_004_ready", lambda _dsn: True)
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
        monkeypatch.setattr(api_v2, "schema_head_004_ready", lambda _dsn: False)
    elif failure == "dimension":
        monkeypatch.setattr(api_v2, "pgvector_dimension", lambda _dsn: 768)
    elif failure == "rag_database":
        monkeypatch.setattr(
            api_v2,
            "schema_head_004_ready",
            lambda _dsn: (_ for _ in ()).throw(RuntimeError("private database failure")),
        )
    elif failure == "retrieval_privileges":
        monkeypatch.setattr(api_v2, "retrieval_database_ready", lambda _dsn: False)
    elif failure == "review_database":
        monkeypatch.setattr(api_v2, "review_database_ready", lambda _dsn: False)
    elif failure == "database_identity":
        monkeypatch.setattr(
            api_v2,
            "postgres_database_authorities_share_instance",
            lambda _rag_dsn, _review_dsn: False,
        )
    else:
        monkeypatch.setattr(api_v2, "_model_artifacts_ready", lambda: False)

    response = TestClient(api_v2.app).get("/health")

    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}
    assert "secret-reader" not in response.text
    assert "secret-reviewer" not in response.text
    assert "private database" not in response.text
    assert "private artifact" not in response.text


def test_business_route_rejects_a_cached_unhealthy_database_proof(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_token = "lot41u-runtime-bff-service-token-32-bytes"
    monkeypatch.setenv("RAG_BFF_SERVICE_TOKEN", service_token)
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://reviewer")
    monkeypatch.setattr(
        api_v2,
        "_cached_database_readiness",
        lambda _rag_dsn, _review_dsn: (
            api_v2.CANONICAL_EMBED_DIM,
            False,
            True,
            True,
            True,
        ),
    )

    response = TestClient(api_v2.app).post(
        "/review/v2/decide",
        json={},
        headers={"Authorization": f"Bearer {service_token}", **API_CLIENT_HEADER},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}


def test_untrusted_business_request_does_not_trigger_database_readiness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "RAG_BFF_SERVICE_TOKEN",
        "lot41u-runtime-bff-service-token-32-bytes",
    )
    monkeypatch.setattr(
        api_v2,
        "_cached_database_readiness",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("an untrusted request must not probe PostgreSQL")
        ),
    )

    response = TestClient(api_v2.app).get("/collections/v2")

    assert response.status_code == 401


def _business_request(path: str = "/collections/v2") -> Request:
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
        }
    )


def test_business_readiness_and_route_share_one_runtime_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    observed: dict[str, float | int | None] = {}
    monkeypatch.setenv("PG_DATABASE_BUDGET_MS", "6000")
    monkeypatch.setattr(pg_pool.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_v2, "require_api_scope", lambda *_args, **_kwargs: None)

    def readiness() -> bool:
        observed["readiness_deadline"] = pg_pool.current_runtime_request_deadline()
        observed["readiness_remaining_ms"] = pg_pool.remaining_request_budget_ms()
        now[0] += 5.5
        return True

    async def route(_request: Request) -> JSONResponse:
        observed["route_deadline"] = pg_pool.current_runtime_request_deadline()
        observed["route_remaining_ms"] = pg_pool.remaining_request_budget_ms()
        return JSONResponse({"ok": True})

    monkeypatch.setattr(api_v2, "_database_runtime_ready", readiness)

    response = asyncio.run(api_v2._metrics_middleware(_business_request(), route))

    assert response.status_code == 200
    assert observed == {
        "readiness_deadline": 106.0,
        "readiness_remaining_ms": 6000,
        "route_deadline": 106.0,
        "route_remaining_ms": 500,
    }
    assert pg_pool.current_runtime_request_deadline() is None


def test_business_route_does_not_start_after_readiness_exhausts_shared_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = [100.0]
    route_calls: list[bool] = []
    monkeypatch.setenv("PG_DATABASE_BUDGET_MS", "6000")
    monkeypatch.setattr(pg_pool.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(api_v2, "require_bff_service", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(api_v2, "require_api_scope", lambda *_args, **_kwargs: None)

    def readiness() -> bool:
        now[0] += 6.001
        return True

    async def route(_request: Request) -> JSONResponse:
        route_calls.append(True)
        return JSONResponse({"ok": True})

    monkeypatch.setattr(api_v2, "_database_runtime_ready", readiness)

    response = asyncio.run(api_v2._metrics_middleware(_business_request(), route))

    assert response.status_code == 503
    assert response.body == b'{"detail":"service unavailable"}'
    assert route_calls == []


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


def test_release_model_inventory_mismatch_refuses_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "configured_release_model_contract",
        lambda: (
            api_v2.CANONICAL_EMBED_MODEL,
            "1" * 64,
            api_v2.CANONICAL_EMBED_DIM,
            api_v2.CANONICAL_RERANK_MODEL,
            "2" * 64,
        ),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="release model inventory mismatch"):
        api_v2._validate_release_model_attestations(
            SimpleNamespace(inventory_sha256="9" * 64),
            SimpleNamespace(inventory_sha256="2" * 64),
        )


def test_lifespan_installs_then_clears_the_startup_attestations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding_attestation = SimpleNamespace(root=Path("/models/e5-large"))
    reranker_attestation = SimpleNamespace(root=Path("/models/reranker"))
    attestations = (embedding_attestation, reranker_attestation)
    pool_settings = object()
    artifacts = {"scope-a": object(), "scope-b": object()}
    catalogue = object()
    lifecycle_events: list[tuple[Path, Path] | str | None] = []
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://reviewer")
    monkeypatch.setattr(
        api_v2,
        "_cached_database_readiness",
        lambda _rag_dsn, _review_dsn: (
            api_v2.CANONICAL_EMBED_DIM,
            True,
            True,
            True,
            True,
        ),
    )
    monkeypatch.setattr(
        api_v2,
        "_initialize_model_artifacts",
        lambda: attestations,
    )
    monkeypatch.setattr(
        api_v2,
        "validate_bff_service_configuration",
        lambda: lifecycle_events.append("bff"),
    )
    monkeypatch.setattr(
        api_v2,
        "load_identity_verifier_config",
        lambda: lifecycle_events.append("identity")
        or SimpleNamespace(artifacts=artifacts),
    )
    monkeypatch.setattr(
        api_v2,
        "validate_collection_catalogue_v2",
        lambda: lifecycle_events.append("catalogue") or catalogue,
    )
    monkeypatch.setattr(
        api_v2,
        "validate_scope_registry_catalogue_alignment",
        lambda loaded_artifacts, loaded_catalogue: lifecycle_events.append(
            "registry_alignment"
        )
        if (loaded_artifacts, loaded_catalogue) == (artifacts, catalogue)
        else pytest.fail("lifespan authority binding drifted"),
        raising=False,
    )
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "validate_release_startup_configuration",
        lambda loaded_artifacts, loaded_catalogue: lifecycle_events.append(
            "release_configuration"
        )
        if (loaded_artifacts, loaded_catalogue) == (artifacts, catalogue)
        else pytest.fail("release startup authority binding drifted"),
    )
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "validate_configured_release_database",
        lambda: lifecycle_events.append("release_database"),
    )
    monkeypatch.setattr(api_v2, "close_pool", lambda: None)
    monkeypatch.setattr(
        api_v2.PoolSettings,
        "from_env",
        classmethod(lambda _cls: pool_settings),
    )
    monkeypatch.setattr(
        api_v2,
        "get_pool",
        lambda settings: lifecycle_events.append("pool")
        if settings is pool_settings
        else None,
        raising=False,
    )
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
        "bff",
        "identity",
        "catalogue",
        "registry_alignment",
        "release_configuration",
        "pool",
        "release_database",
        (embedding_attestation.root, reranker_attestation.root),
        "preload",
        None,
    ]


def test_lifespan_refuses_startup_when_database_readiness_is_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool_settings = object()
    closed: list[bool] = []
    model_initialization_calls: list[bool] = []
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://reader")
    monkeypatch.setenv("PG_REVIEW_DSN", "postgresql://reviewer")
    monkeypatch.setattr(
        api_v2.PoolSettings,
        "from_env",
        classmethod(lambda _cls: pool_settings),
    )
    monkeypatch.setattr(api_v2, "get_pool", lambda _settings: object())
    monkeypatch.setattr(api_v2, "close_pool", lambda: closed.append(True))
    monkeypatch.setattr(
        api_v2,
        "_cached_database_readiness",
        lambda _rag_dsn, _review_dsn: (
            api_v2.CANONICAL_EMBED_DIM,
            True,
            True,
            False,
            True,
        ),
    )
    monkeypatch.setattr(
        api_v2,
        "_initialize_model_artifacts",
        lambda: model_initialization_calls.append(True),
    )

    with pytest.raises(RuntimeError, match="database readiness unavailable"):
        with TestClient(api_v2.app):
            pytest.fail("le runtime ne doit pas accepter du trafic")

    assert model_initialization_calls == []
    assert closed == [True]


def test_lifespan_refuses_startup_when_release_database_is_not_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool_settings = object()
    model_initialization_calls: list[bool] = []
    monkeypatch.setattr(
        api_v2.PoolSettings,
        "from_env",
        classmethod(lambda _cls: pool_settings),
    )
    monkeypatch.setattr(api_v2, "get_pool", lambda _settings: object())
    monkeypatch.setattr(api_v2, "close_pool", lambda: None)
    monkeypatch.setattr(api_v2, "_database_runtime_ready", lambda: True)
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "validate_configured_release_database",
        lambda: (_ for _ in ()).throw(RuntimeError("release database reconciliation unavailable")),
    )
    monkeypatch.setattr(
        api_v2,
        "_initialize_model_artifacts",
        lambda: model_initialization_calls.append(True),
    )

    with pytest.raises(RuntimeError, match="release database reconciliation unavailable"):
        with TestClient(api_v2.app):
            pytest.fail("le runtime ne doit pas accepter une release partielle")

    assert model_initialization_calls == []


def test_lifespan_refuses_startup_when_the_real_retrieval_pool_cannot_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pool_settings = object()
    closed: list[bool] = []
    monkeypatch.setattr(
        api_v2.PoolSettings,
        "from_env",
        classmethod(lambda _cls: pool_settings),
    )
    monkeypatch.setattr(
        api_v2,
        "get_pool",
        lambda settings: (_ for _ in ()).throw(RuntimeError("pool unavailable"))
        if settings is pool_settings
        else None,
        raising=False,
    )
    monkeypatch.setattr(api_v2, "close_pool", lambda: closed.append(True))

    with pytest.raises(RuntimeError, match="pool unavailable"):
        with TestClient(api_v2.app):
            pytest.fail("le runtime ne doit pas accepter du trafic")

    assert closed == [True]


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
        "inference_runtime.py",
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
        "servable_corpus_api.py",
        "servable_corpus_index.py",
    ):
        assert f"services/rag-engine/src/ingestor/{required_module}" in content
    assert "infra/postgres/migrations/ /app/migrations/" in content
    assert (
        "infra/postgres/schema_head_004_fingerprints.env "
        "/app/schema_head_004_fingerprints.env" in content
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
        "RAG_SERVABLE_CORPUS_HOST_DIR=",
        "RAG_SERVABLE_CORPUS_INDEX_SHA256=",
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


def test_v2_runtime_mounts_the_externally_pinned_servable_corpus_read_only() -> None:
    compose = V2_COMPOSE.read_text(encoding="utf-8")

    assert (
        "RAG_SERVABLE_CORPUS_DIRECTORY: /app/servable-corpus" in compose
    )
    assert (
        'RAG_SERVABLE_CORPUS_INDEX_SHA256: "${RAG_SERVABLE_CORPUS_INDEX_SHA256:'
        "?empreinte SHA-256 externe du registre de corpus servables requise}"
    ) in compose
    assert (
        "${RAG_SERVABLE_CORPUS_HOST_DIR:?répertoire hôte des corpus servables "
        "requis}:/app/servable-corpus:ro"
    ) in compose


def test_integration_make_target_exposes_the_ingestor_package() -> None:
    makefile = MAKEFILE.read_text(encoding="utf-8")

    assert (
        "test-integration: install\n"
        "\tPYTHONPATH=src $(PYTEST) tests/integration -q"
    ) in makefile
