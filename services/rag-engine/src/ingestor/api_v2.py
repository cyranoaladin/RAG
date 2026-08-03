"""Application Nexus v2 minimale : retrieval et revue, sans writer."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from threading import Lock

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST

try:
    from . import metrics as ingest_metrics
    from . import retrieval_v2_endpoint, review_v2_endpoint
    from .embedding_contract import (
        CANONICAL_EMBED_DIM,
        CANONICAL_EMBED_MODEL,
        declared_embedding_dim,
        declared_embedding_model,
        pgvector_dimension,
        verify_configured_embedding_artifact,
    )
    from .model_artifact import (
        ModelArtifactAttestation,
        attest_verified_model_artifact,
        model_artifact_attestation_ready,
    )
    from .pg_pool import close_pool
    from .reranker_contract import verify_configured_reranker_artifact
    from .retrieval_readiness_v2 import retrieval_database_ready
    from .review_readiness_v2 import review_database_ready
    from .schema_readiness_v2 import schema_head_003_ready
except (ImportError, ValueError):
    import metrics as ingest_metrics  # type: ignore[no-redef]
    import retrieval_v2_endpoint  # type: ignore[no-redef]
    import review_v2_endpoint  # type: ignore[no-redef]
    from embedding_contract import (  # type: ignore[no-redef]
        CANONICAL_EMBED_DIM,
        CANONICAL_EMBED_MODEL,
        declared_embedding_dim,
        declared_embedding_model,
        pgvector_dimension,
        verify_configured_embedding_artifact,
    )
    from model_artifact import (  # type: ignore[no-redef]
        ModelArtifactAttestation,
        attest_verified_model_artifact,
        model_artifact_attestation_ready,
    )
    from pg_pool import close_pool  # type: ignore[no-redef]
    from reranker_contract import (  # type: ignore[no-redef]
        verify_configured_reranker_artifact,
    )
    from retrieval_readiness_v2 import (  # type: ignore[no-redef]
        retrieval_database_ready,
    )
    from review_readiness_v2 import (  # type: ignore[no-redef]
        review_database_ready,
    )
    from schema_readiness_v2 import (  # type: ignore[no-redef]
        schema_head_003_ready,
    )

_ALLOWED_BUSINESS_ROUTES = frozenset(
    {
        "/search/v2",
        "/chat",
        "/collections/v2",
        "/catalogue/v2",
        "/collections/readiness",
        "/review/v2/queue",
        "/review/v2/decide",
    }
)
_OBSERVED_ROUTES = _ALLOWED_BUSINESS_ROUTES | {"/health", "/metrics"}
_OBSERVED_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"}
)
_model_artifact_attestations: (
    tuple[ModelArtifactAttestation, ModelArtifactAttestation] | None
) = None
_READINESS_CACHE_TTL_S = 5.0
_database_readiness_cache_lock = Lock()
_database_readiness_cache: (
    tuple[str, str, float, tuple[int, bool, bool, bool] | None] | None
) = None


def _required_model_inventory_anchor(environment_variable: str) -> str:
    anchor = os.environ.get(environment_variable, "").strip()
    if not anchor:
        raise RuntimeError("model artifact inventory anchor unavailable")
    return anchor


def _initialize_model_artifacts() -> tuple[
    ModelArtifactAttestation,
    ModelArtifactAttestation,
]:
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
) -> tuple[int, bool, bool, bool]:
    """Exécuter une unique sonde profonde des deux autorités PostgreSQL."""
    return (
        pgvector_dimension(rag_dsn),
        schema_head_003_ready(rag_dsn),
        retrieval_database_ready(rag_dsn),
        review_database_ready(review_dsn),
    )


def _cached_database_readiness(
    rag_dsn: str,
    review_dsn: str,
) -> tuple[int, bool, bool, bool]:
    """Coalescer les rafales de probes et borner leur travail PostgreSQL."""
    global _database_readiness_cache
    now = time.monotonic()
    with _database_readiness_cache_lock:
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


@asynccontextmanager
async def _app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    global _model_artifact_attestations
    try:
        _reset_database_readiness_cache()
        _model_artifact_attestations = _initialize_model_artifacts()
        embedding_attestation, reranker_attestation = _model_artifact_attestations
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
        response = await call_next(request)
        status_code = response.status_code
    finally:
        path = request.url.path
        ingest_metrics.record_http_request(
            path if path in _OBSERVED_ROUTES else "unmatched",
            request.method if request.method in _OBSERVED_METHODS else "other",
            status_code,
            time.perf_counter() - started,
        )
    return response


def _mount_allowed_routes() -> None:
    for source in (retrieval_v2_endpoint.router, review_v2_endpoint.router):
        for route in source.routes:
            route_path = getattr(route, "path", None)
            if route_path in _ALLOWED_BUSINESS_ROUTES:
                app.router.routes.append(route)


_mount_allowed_routes()


@app.get("/health")
def health_check() -> dict[str, str | int]:
    rag_dsn = os.environ.get("PG_RAG_DSN", "").strip()
    review_dsn = os.environ.get("PG_REVIEW_DSN", "").strip()
    if not rag_dsn or not review_dsn:
        raise HTTPException(status_code=503, detail="service unavailable")
    try:
        model = declared_embedding_model()
        declared_dim = declared_embedding_dim()
        model_artifacts_ready = _model_artifacts_ready()
        (
            database_dim,
            schema_ready,
            retrieval_ready,
            review_ready,
        ) = _cached_database_readiness(rag_dsn, review_dsn)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="service unavailable") from exc
    if (
        model != CANONICAL_EMBED_MODEL
        or declared_dim != CANONICAL_EMBED_DIM
        or database_dim != CANONICAL_EMBED_DIM
        or not schema_ready
        or not retrieval_ready
        or not review_ready
        or not model_artifacts_ready
    ):
        raise HTTPException(status_code=503, detail="service unavailable")
    return {
        "status": "healthy",
        "schema_head": "003_profile_filtering",
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
