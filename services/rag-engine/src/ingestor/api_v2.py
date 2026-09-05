"""Application Nexus v2 minimale : retrieval et revue, sans writer."""

from __future__ import annotations

import os
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST
from starlette.concurrency import run_in_threadpool


def _missing_sibling(exc: ImportError) -> bool:
    """Le frère visé est-il absent, ou son exécution a-t-elle échoué ?

    Deux situations autorisent le repli : le module frère (ou son paquet
    parent) est introuvable, et le runtime aplati de l'image Docker, où
    les modules n'ont pas de paquet parent et ``from .x import y`` lève
    « attempted relative import with no known parent package ».

    Tout le reste — une dépendance transitive manquante, un ``cannot
    import name``, une configuration refusée — remonte intact : réessayer
    par un autre chemin rejouerait le même échec sous un autre nom.
    """
    if not isinstance(exc, ModuleNotFoundError):
        return exc.name is None and "relative import" in str(exc)
    name = exc.name or ""
    return name == name.rsplit(".", 1)[-1] or name in (
        "src",
        "src.ingestor",
        "ingestor",
    )


try:
    from . import metrics as ingest_metrics
    from . import retrieval_v2_endpoint, review_v2_endpoint, servable_corpus_api
    from .api_scopes import (
        ApiScope,
        load_api_clients,
        require_api_scope,
        required_scope_for_route,
    )
    from .collection_config import validate_collection_catalogue_v2
    from .embedding_contract import (
        CANONICAL_EMBED_DIM,
        CANONICAL_EMBED_MODEL,
        declared_embedding_dim,
        declared_embedding_model,
        pgvector_dimension,
        verify_configured_embedding_artifact,
    )
    from .identity_v2 import load_identity_verifier_config
    from .model_artifact import (
        ModelArtifactAttestation,
        attest_verified_model_artifact,
        model_artifact_attestation_ready,
    )
    from .pg_pool import (
        PoolConfigurationError,
        PoolSettings,
        close_pool,
        current_runtime_request_deadline,
        get_pool,
        remaining_request_budget_ms,
        runtime_request_budget,
    )
    from .readiness_db import (
        READINESS_AGGREGATE_BUDGET_MS,
        postgres_database_authorities_share_instance,
        readiness_database_budget,
    )
    from .reranker_contract import (
        CANONICAL_RERANK_MODEL,
        verify_configured_reranker_artifact,
    )
    from .retrieval_observability import (
        RetrievalAccessRecord,
        log_retrieval_access,
        resolve_request_id,
    )
    from .retrieval_readiness_v2 import retrieval_database_ready
    from .retrieval_scope_v2 import validate_scope_registry_catalogue_alignment
    from .review_readiness_v2 import review_database_ready
    from .schema_readiness_v2 import schema_head_004_ready
    from .security_v2 import (
        require_bff_service,
        validate_bff_service_configuration,
    )
except ImportError as _exc:  # repli à plat, cause réelle préservée
    if not _missing_sibling(_exc):
        # Le module frère existe : c'est l'une de ses dépendances qui
        # manque, ou sa configuration qui a été refusée. Réessayer par un
        # autre chemin rejouerait le même échec sous un autre nom.
        raise
    import metrics as ingest_metrics  # type: ignore[no-redef]
    import retrieval_v2_endpoint  # type: ignore[no-redef]
    import review_v2_endpoint  # type: ignore[no-redef]
    import servable_corpus_api  # type: ignore[no-redef]
    from api_scopes import (  # type: ignore[no-redef]
        ApiScope,
        load_api_clients,
        require_api_scope,
        required_scope_for_route,
    )
    from collection_config import (  # type: ignore[no-redef]
        validate_collection_catalogue_v2,
    )
    from embedding_contract import (  # type: ignore[no-redef]
        CANONICAL_EMBED_DIM,
        CANONICAL_EMBED_MODEL,
        declared_embedding_dim,
        declared_embedding_model,
        pgvector_dimension,
        verify_configured_embedding_artifact,
    )
    from identity_v2 import (  # type: ignore[no-redef]
        load_identity_verifier_config,
    )
    from model_artifact import (  # type: ignore[no-redef]
        ModelArtifactAttestation,
        attest_verified_model_artifact,
        model_artifact_attestation_ready,
    )
    from pg_pool import (  # type: ignore[no-redef]
        PoolConfigurationError,
        PoolSettings,
        close_pool,
        current_runtime_request_deadline,
        get_pool,
        remaining_request_budget_ms,
        runtime_request_budget,
    )
    from readiness_db import (  # type: ignore[no-redef]
        READINESS_AGGREGATE_BUDGET_MS,
        postgres_database_authorities_share_instance,
        readiness_database_budget,
    )
    from reranker_contract import (  # type: ignore[no-redef]
        CANONICAL_RERANK_MODEL,
        verify_configured_reranker_artifact,
    )
    from retrieval_observability import (  # type: ignore[no-redef]
        RetrievalAccessRecord,
        log_retrieval_access,
        resolve_request_id,
    )
    from retrieval_readiness_v2 import (  # type: ignore[no-redef]
        retrieval_database_ready,
    )
    from retrieval_scope_v2 import (  # type: ignore[no-redef]
        validate_scope_registry_catalogue_alignment,
    )
    from review_readiness_v2 import (  # type: ignore[no-redef]
        review_database_ready,
    )
    from schema_readiness_v2 import (  # type: ignore[no-redef]
        schema_head_004_ready,
    )
    from security_v2 import (  # type: ignore[no-redef]
        require_bff_service,
        validate_bff_service_configuration,
    )

_ALLOWED_BUSINESS_ROUTES = frozenset(
    {
        "/search/v2",
        "/taxonomy/v2",
        "/chat",
        "/collections/v2",
        "/catalogue/v2",
        "/collections/readiness",
        "/review/v2/queue",
        "/review/v2/decide",
        "/corpora/servable/v1",
        "/corpora/servable/v1/{manifest_sha256}",
    }
)
_OBSERVED_ROUTES = _ALLOWED_BUSINESS_ROUTES | {"/health", "/metrics"}
_OBSERVED_METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"})
_model_artifact_attestations: tuple[ModelArtifactAttestation, ModelArtifactAttestation] | None = (
    None
)
_READINESS_CACHE_TTL_S = 5.0
_READINESS_LOCK_TIMEOUT_S = (READINESS_AGGREGATE_BUDGET_MS + 1000) / 1000
_database_readiness_cache_lock = Lock()
_database_readiness_cache: (
    tuple[str, str, float, tuple[int, bool, bool, bool, bool] | None] | None
) = None


def _business_route_template(path: str) -> str | None:
    if path in _ALLOWED_BUSINESS_ROUTES:
        return path
    if re.fullmatch(r"/corpora/servable/v1/[0-9a-f]{64}", path):
        return "/corpora/servable/v1/{manifest_sha256}"
    return None


def _required_route_scope(route_template: str) -> ApiScope:
    """Portée exigée par une route métier montée. Jamais de repli permissif.

    Une route exposée dont la portée n'aurait pas été déclarée serait une
    route sans porte : on refuse le trafic plutôt que de la servir ouverte.
    Un test de surface vérifie par ailleurs que la table les couvre toutes,
    de sorte que ce refus reste un filet et non un comportement normal.
    """
    scope = required_scope_for_route(route_template)
    if scope is None:
        raise HTTPException(
            status_code=503,
            detail=f"{route_template}: no API scope declared for this route",
        )
    return scope


def _required_model_inventory_anchor(environment_variable: str) -> str:
    anchor = os.environ.get(environment_variable, "").strip()
    if not anchor:
        raise RuntimeError("model artifact inventory anchor unavailable")
    return anchor


def _initialize_model_artifacts() -> (
    tuple[
        ModelArtifactAttestation,
        ModelArtifactAttestation,
    ]
):
    """Hacher intégralement les deux artefacts avant d'accepter du trafic."""
    embedding_root = verify_configured_embedding_artifact()
    reranker_root = verify_configured_reranker_artifact()
    embedding_attestation = attest_verified_model_artifact(
        embedding_root,
        expected_inventory_sha256=_required_model_inventory_anchor(
            "RAG_EMBEDDING_MODEL_INVENTORY_SHA256"
        ),
    )
    reranker_attestation = attest_verified_model_artifact(
        reranker_root,
        expected_inventory_sha256=_required_model_inventory_anchor(
            "RAG_RERANKER_MODEL_INVENTORY_SHA256"
        ),
    )
    return embedding_attestation, reranker_attestation


def _validate_release_model_attestations(
    embedding_attestation: ModelArtifactAttestation,
    reranker_attestation: ModelArtifactAttestation,
) -> None:
    """Lier les poids attestés aux inventaires scellés de la release active."""
    expected = retrieval_v2_endpoint.configured_release_model_contract()
    if expected is None:
        return
    actual = (
        CANONICAL_EMBED_MODEL,
        embedding_attestation.inventory_sha256,
        CANONICAL_EMBED_DIM,
        CANONICAL_RERANK_MODEL,
        reranker_attestation.inventory_sha256,
    )
    if actual != expected:
        raise RuntimeError("release model inventory mismatch")


def _model_artifacts_ready() -> bool:
    """Sonder les attestations de démarrage sans relire les poids modèles."""
    if _model_artifact_attestations is None:
        return False
    embedding_attestation, reranker_attestation = _model_artifact_attestations
    try:
        return model_artifact_attestation_ready(
            embedding_attestation,
            expected_inventory_sha256=_required_model_inventory_anchor(
                "RAG_EMBEDDING_MODEL_INVENTORY_SHA256"
            ),
        ) and model_artifact_attestation_ready(
            reranker_attestation,
            expected_inventory_sha256=_required_model_inventory_anchor(
                "RAG_RERANKER_MODEL_INVENTORY_SHA256"
            ),
        )
    except Exception:
        return False


def _reset_database_readiness_cache() -> None:
    """Vider la preuve process-local lors des transitions de lifespan/tests."""
    global _database_readiness_cache
    with _database_readiness_cache_lock:
        _database_readiness_cache = None


def _probe_database_readiness(
    rag_dsn: str,
    review_dsn: str,
) -> tuple[int, bool, bool, bool, bool]:
    """Exécuter une unique sonde profonde des deux autorités PostgreSQL."""
    with readiness_database_budget(current_runtime_request_deadline()):
        same_database = postgres_database_authorities_share_instance(
            rag_dsn,
            review_dsn,
        )
        return (
            pgvector_dimension(rag_dsn),
            schema_head_004_ready(rag_dsn),
            retrieval_database_ready(rag_dsn),
            review_database_ready(review_dsn),
            same_database,
        )


def _cached_database_readiness(
    rag_dsn: str,
    review_dsn: str,
) -> tuple[int, bool, bool, bool, bool]:
    """Coalescer les rafales de probes et borner leur travail PostgreSQL."""
    global _database_readiness_cache
    request_deadline = current_runtime_request_deadline()
    lock_timeout_s = _READINESS_LOCK_TIMEOUT_S
    if request_deadline is not None:
        remaining_s = request_deadline - time.monotonic()
        if remaining_s <= 0:
            raise RuntimeError("database readiness unavailable")
        lock_timeout_s = min(lock_timeout_s, remaining_s)
    if not _database_readiness_cache_lock.acquire(timeout=lock_timeout_s):
        raise RuntimeError("database readiness unavailable")
    try:
        now = time.monotonic()
        cached = _database_readiness_cache
        if (
            cached is not None
            and cached[0] == rag_dsn
            and cached[1] == review_dsn
            and now < cached[2]
        ):
            if cached[3] is None:
                raise RuntimeError("database readiness unavailable")
            return cached[3]

        try:
            readiness = _probe_database_readiness(rag_dsn, review_dsn)
        except Exception:
            _database_readiness_cache = (
                rag_dsn,
                review_dsn,
                time.monotonic() + _READINESS_CACHE_TTL_S,
                None,
            )
            raise

        _database_readiness_cache = (
            rag_dsn,
            review_dsn,
            time.monotonic() + _READINESS_CACHE_TTL_S,
            readiness,
        )
        return readiness
    finally:
        _database_readiness_cache_lock.release()


def _database_readiness_from_environment() -> tuple[int, bool, bool, bool, bool]:
    """Charger les deux autorités puis retourner leur preuve coalescée."""
    rag_dsn = os.environ.get("PG_RAG_DSN", "").strip()
    review_dsn = os.environ.get("PG_REVIEW_DSN", "").strip()
    if not rag_dsn or not review_dsn:
        raise RuntimeError("database readiness unavailable")
    return _cached_database_readiness(rag_dsn, review_dsn)


def _database_readiness_is_healthy(
    readiness: tuple[int, bool, bool, bool, bool],
) -> bool:
    """Interpréter en un seul endroit la preuve exigée par toutes les routes."""
    database_dim, schema_ready, retrieval_ready, review_ready, same_database = readiness
    return (
        database_dim == CANONICAL_EMBED_DIM
        and schema_ready
        and retrieval_ready
        and review_ready
        and same_database
    )


def _database_runtime_ready() -> bool:
    """Fermer le runtime sur toute preuve PostgreSQL absente ou invalide."""
    try:
        return _database_readiness_is_healthy(_database_readiness_from_environment())
    except Exception:
        return False


def _validate_runtime_authorities() -> None:
    """Lier au démarrage le BFF, les clés d'API, le registre signé et le catalogue."""
    validate_bff_service_configuration()
    # Le registre de clés est vérifié au démarrage, pas seulement à la
    # première requête : un runtime qui accepterait du trafic avant de
    # savoir qui a le droit d'appeler serait ouvert le temps d'un appel.
    load_api_clients()
    identity_config = load_identity_verifier_config()
    collection_catalogue = validate_collection_catalogue_v2()
    validate_scope_registry_catalogue_alignment(
        identity_config.artifacts,
        collection_catalogue,
    )
    retrieval_v2_endpoint.validate_release_startup_configuration(
        identity_config.artifacts,
        collection_catalogue,
    )


@asynccontextmanager
async def _app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _model_artifact_attestations
    try:
        _reset_database_readiness_cache()
        _validate_runtime_authorities()
        get_pool(PoolSettings.from_env())
        if not _database_runtime_ready():
            raise RuntimeError("database readiness unavailable")
        retrieval_v2_endpoint.validate_configured_release_database()
        _model_artifact_attestations = _initialize_model_artifacts()
        embedding_attestation, reranker_attestation = _model_artifact_attestations
        _validate_release_model_attestations(
            embedding_attestation,
            reranker_attestation,
        )
        retrieval_v2_endpoint.configure_verified_model_artifacts(
            embedding_root=embedding_attestation.root,
            reranker_root=reranker_attestation.root,
        )
        retrieval_v2_endpoint.preload_runtime_models()
        if not _model_artifacts_ready():
            raise RuntimeError("model artifacts changed during startup")
        yield
    finally:
        retrieval_v2_endpoint.reset_runtime_model_state()
        _model_artifact_attestations = None
        _reset_database_readiness_cache()
        close_pool()


_development = os.environ.get("RAG_ENV", "production").strip().casefold() == "development"
app = FastAPI(
    title="Nexus RAG Engine v2",
    docs_url="/docs" if _development else None,
    redoc_url="/redoc" if _development else None,
    openapi_url="/openapi.json" if _development else None,
    lifespan=_app_lifespan,
)


@app.middleware("http")
async def _metrics_middleware(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        path = request.url.path
        route_template = _business_route_template(path)
        if route_template is not None:
            try:
                # Deux portes cumulatives : le credential machine du BFF
                # établit que l'appel vient de la façade autorisée ; la
                # portée de la clé porteuse établit ce que CE client a le
                # droit de faire. Aucune ne dispense de l'autre.
                require_bff_service(request, endpoint=path)
                request.state.api_client = require_api_scope(
                    request,
                    required=_required_route_scope(route_template),
                    endpoint=path,
                )
            except HTTPException as exc:
                response = JSONResponse(
                    content={"detail": exc.detail},
                    status_code=exc.status_code,
                    headers=exc.headers,
                )
            else:
                try:
                    with runtime_request_budget():
                        if route_template.startswith("/corpora/servable/v1"):
                            response = await call_next(request)
                            remaining_request_budget_ms()
                            status_code = response.status_code
                            return response
                        database_ready = await run_in_threadpool(_database_runtime_ready)
                        if database_ready:
                            remaining_request_budget_ms()
                            response = await call_next(request)
                        else:
                            response = JSONResponse(
                                content={"detail": "service unavailable"},
                                status_code=503,
                            )
                except PoolConfigurationError:
                    response = JSONResponse(
                        content={"detail": "service unavailable"},
                        status_code=503,
                    )
        else:
            response = await call_next(request)
        status_code = response.status_code
        if route_template is not None:
            _journal_unrecorded_access(
                request,
                endpoint=route_template,
                status_code=status_code,
                started=started,
            )
    finally:
        path = request.url.path
        ingest_metrics.record_http_request(
            _business_route_template(path)
            or (path if path in _OBSERVED_ROUTES else "unmatched"),
            request.method if request.method in _OBSERVED_METHODS else "other",
            status_code,
            time.perf_counter() - started,
        )
    return response


def _journal_unrecorded_access(
    request: Request,
    *,
    endpoint: str,
    status_code: int,
    started: float,
) -> None:
    """Journaliser ce qui n'a jamais atteint la route.

    Un refus d'authentification, un corps rejeté par la validation du
    framework ou une base déclarée indisponible ne traversent pas la fonction
    de route : sans cette ligne, les requêtes les plus intéressantes pour
    l'exploitation — celles qui ont échoué — seraient les seules absentes du
    journal. La route pose une marque quand elle a déjà écrit ; il y a donc
    exactement un enregistrement par requête, jamais deux.
    """
    state = getattr(request, "state", None)
    if getattr(state, "access_journaled", False):
        return
    client = getattr(state, "api_client", None)
    scopes = tuple(
        sorted(
            value
            for value in (
                getattr(scope, "value", scope)
                for scope in (getattr(client, "scopes", None) or ())
            )
            if isinstance(value, str)
        )
    )
    log_retrieval_access(
        RetrievalAccessRecord(
            request_id=resolve_request_id(getattr(request, "headers", None)),
            endpoint=endpoint,
            client_id=str(getattr(client, "client_id", None) or "unattributed"),
            granted_scopes=scopes,
            status_code=status_code,
            latency_ms=(time.perf_counter() - started) * 1000.0,
            outcome="pre_route",
        )
    )


def _mount_allowed_routes() -> None:
    for source in (
        retrieval_v2_endpoint.router,
        review_v2_endpoint.router,
        servable_corpus_api.router,
    ):
        for route in source.routes:
            route_path = getattr(route, "path", None)
            if route_path in _ALLOWED_BUSINESS_ROUTES:
                app.router.routes.append(route)


_mount_allowed_routes()


@app.get("/health")
def health_check() -> dict[str, str | int]:
    try:
        PoolSettings.from_env()
        _validate_runtime_authorities()
        model = declared_embedding_model()
        declared_dim = declared_embedding_dim()
        model_artifacts_ready = _model_artifacts_ready()
        database_readiness = _database_readiness_from_environment()
        database_dim = database_readiness[0]
    except Exception as exc:
        raise HTTPException(status_code=503, detail="service unavailable") from exc
    if (
        model != CANONICAL_EMBED_MODEL
        or declared_dim != CANONICAL_EMBED_DIM
        or database_dim != CANONICAL_EMBED_DIM
        or not _database_readiness_is_healthy(database_readiness)
        or not model_artifacts_ready
    ):
        raise HTTPException(status_code=503, detail="service unavailable")
    return {
        "status": "healthy",
        "schema_head": "004_artifact_placements",
        "embedding_model": model,
        "embedding_dim_declared": declared_dim,
        "pgvector_dim": database_dim,
    }


@app.get("/metrics")
def metrics() -> Response:
    if not ingest_metrics.METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="Not Found")
    return Response(
        content=ingest_metrics.generate_latest(ingest_metrics.REGISTRY),
        media_type=CONTENT_TYPE_LATEST,
    )
