"""Application Nexus v2 minimale : retrieval et revue, sans writer."""

from __future__ import annotations

import os
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def _app_lifespan(_app: FastAPI) -> AsyncIterator[None]:
    try:
        yield
    finally:
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
            request.method,
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
        database_dim = pgvector_dimension(rag_dsn)
        schema_ready = schema_head_003_ready(rag_dsn)
        retrieval_ready = retrieval_database_ready(rag_dsn)
        review_ready = review_database_ready(review_dsn)
        verify_configured_embedding_artifact()
        verify_configured_reranker_artifact()
    except Exception as exc:
        raise HTTPException(status_code=503, detail="service unavailable") from exc
    if (
        model != CANONICAL_EMBED_MODEL
        or declared_dim != CANONICAL_EMBED_DIM
        or database_dim != CANONICAL_EMBED_DIM
        or not schema_ready
        or not retrieval_ready
        or not review_ready
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
