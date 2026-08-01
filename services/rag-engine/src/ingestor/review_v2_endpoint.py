"""Review humaine scopée des contenus issus du pipeline d'ingestion."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from nexus_contracts import Rights
from pydantic import BaseModel, ConfigDict, Field

try:
    from .collection_config import load_collection_config
    from .identity_v2 import VerifiedInternalIdentity, require_internal_identity
    from .retrieval_scope_v2 import (
        RetrievalScopeError,
        ServerRetrievalScope,
        build_server_retrieval_scope,
    )
    from .retrieval_v2_endpoint import invalidate_cache
    from .security_v2 import require_bff_service
except (ImportError, ValueError):
    from collection_config import load_collection_config  # type: ignore[no-redef]
    from identity_v2 import (  # type: ignore[no-redef]
        VerifiedInternalIdentity,
        require_internal_identity,
    )
    from retrieval_scope_v2 import (  # type: ignore[no-redef]
        RetrievalScopeError,
        ServerRetrievalScope,
        build_server_retrieval_scope,
    )
    from retrieval_v2_endpoint import invalidate_cache  # type: ignore[no-redef]
    from security_v2 import require_bff_service  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review/v2", tags=["review_v2"])

_REVIEW_ROLES = frozenset({"admin", "reviewer"})
_SCOPE_PREDICATE_SQL = """
    collection = %s
    AND tenant = %s
    AND niveau = %s
    AND voie IS NOT DISTINCT FROM %s
    AND matiere = %s
    AND statut_enseignement = %s
    AND candidat = ANY(%s::text[])
    AND audience && %s::text[]
    AND rights = ANY(%s::text[])
    AND visibility = ANY(%s::text[])
    AND school_year = %s
    AND programme_version = %s
"""


def _get_pg_dsn() -> str:
    dsn = os.environ.get("PG_REVIEW_DSN")
    if not dsn:
        raise HTTPException(status_code=503, detail="review unavailable")
    return dsn


def _require_review_identity(
    request: Request,
    *,
    endpoint: str,
) -> VerifiedInternalIdentity:
    """Exiger le BFF, l'identité signée et un rôle humain de review."""
    require_bff_service(request, endpoint=endpoint)
    verified = require_internal_identity(request)
    if verified.envelope.identity.role not in _REVIEW_ROLES:
        raise HTTPException(status_code=403, detail="Forbidden")
    return verified


def _resolve_review_scopes(
    verified: VerifiedInternalIdentity,
    *,
    collection: str | None,
    tenant: str | None,
    collection_config: Mapping[str, Any],
) -> tuple[ServerRetrievalScope, ...]:
    """Dériver les scopes signés ; les sélecteurs clients ne font que réduire."""
    identity_tenant = str(verified.envelope.identity.tenant)
    if tenant is not None and tenant != identity_tenant:
        raise HTTPException(status_code=403, detail="Forbidden")

    allowed = tuple(str(value) for value in verified.envelope.allowed_collections)
    selected: tuple[str, ...]
    if collection is not None:
        if collection not in allowed:
            raise HTTPException(status_code=403, detail="Forbidden")
        selected = (collection,)
    else:
        selected = allowed
    if not selected:
        raise HTTPException(status_code=403, detail="Forbidden")

    scopes: list[ServerRetrievalScope] = []
    try:
        for selected_collection in selected:
            scope = build_server_retrieval_scope(
                verified,
                collection=selected_collection,
                collection_config=collection_config,
            )
            if scope.tenant != identity_tenant:
                raise RetrievalScopeError("review scope forbidden")
            scopes.append(scope)
    except (RetrievalScopeError, ValueError) as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
    return tuple(scopes)


def _scope_params(scope: ServerRetrievalScope) -> tuple[object, ...]:
    if not isinstance(scope, ServerRetrievalScope):
        raise HTTPException(status_code=403, detail="Forbidden")
    if not scope.audiences or not scope.rights or not scope.visibilities:
        raise HTTPException(status_code=403, detail="Forbidden")
    if any(not isinstance(right, Rights) for right in scope.rights):
        raise HTTPException(status_code=403, detail="Forbidden")
    return (
        scope.collection,
        scope.tenant,
        scope.niveau,
        scope.voie,
        scope.matiere,
        scope.statut_enseignement,
        [scope.candidat, "both"],
        list(scope.audiences),
        [right.value for right in scope.rights],
        list(scope.visibilities),
        scope.school_year,
        scope.programme_version,
    )


def _scope_filter(
    scopes: Sequence[ServerRetrievalScope],
) -> tuple[str, tuple[object, ...]]:
    if not scopes:
        raise HTTPException(status_code=403, detail="Forbidden")
    clauses: list[str] = []
    params: list[object] = []
    for scope in scopes:
        clauses.append(f"({_SCOPE_PREDICATE_SQL})")
        params.extend(_scope_params(scope))
    return "(" + " OR ".join(clauses) + ")", tuple(params)


def _load_review_scopes(
    verified: VerifiedInternalIdentity,
    *,
    collection: str | None,
    tenant: str | None,
) -> tuple[ServerRetrievalScope, ...]:
    try:
        config = load_collection_config()
    except Exception as exc:
        logger.error("review configuration unavailable")
        raise HTTPException(status_code=503, detail="review unavailable") from exc
    return _resolve_review_scopes(
        verified,
        collection=collection,
        tenant=tenant,
        collection_config=config,
    )


class PendingQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    collection: str | None = Field(default=None, min_length=1, max_length=128)
    tenant: str | None = Field(default=None, min_length=1, max_length=128)
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ReviewDecision(BaseModel):
    """Décision humaine explicite sur un document ou un chunk scopé."""

    model_config = ConfigDict(extra="forbid")

    target_type: Literal["doc", "chunk"] = "doc"
    target_id: str = Field(min_length=1, max_length=256)
    decision: Literal["reviewed", "quarantined"]
    reason: str = Field(default="", max_length=1000)
    collection: str | None = Field(default=None, min_length=1, max_length=128)
    tenant: str | None = Field(default=None, min_length=1, max_length=128)


@router.get("/queue")
def list_queue(
    request: Request,
    collection: str | None = Query(default=None, min_length=1, max_length=128),
    tenant: str | None = Query(default=None, min_length=1, max_length=128),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """Lister uniquement les documents `needs_review` du scope signé."""
    verified = _require_review_identity(request, endpoint="/review/v2/queue")
    scopes = _load_review_scopes(
        verified,
        collection=collection,
        tenant=tenant,
    )
    scope_sql, scope_params = _scope_filter(scopes)
    pg_dsn = _get_pg_dsn()

    connection: Any | None = None
    try:
        connection = psycopg.connect(pg_dsn)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM (SELECT 1 FROM rag_chunks "
                "WHERE review_status = 'needs_review' AND "
                + scope_sql
                + " GROUP BY doc_id, collection) AS scoped_documents",
                scope_params,
            )
            row = cursor.fetchone()
            total_docs = int(row[0]) if row else 0

            cursor.execute(
                """
                SELECT doc_id, collection, source_label, source_uri, rights,
                       source_kind, type_doc, COUNT(*) AS chunk_count,
                       MIN(indexed_at) AS first_indexed,
                       MAX(indexed_at) AS last_indexed
                FROM rag_chunks
                WHERE review_status = 'needs_review' AND
                """
                + scope_sql
                + """
                GROUP BY doc_id, collection, source_label, source_uri, rights,
                         source_kind, type_doc
                ORDER BY MIN(indexed_at) DESC, collection ASC, doc_id ASC
                LIMIT %s OFFSET %s
                """,
                (*scope_params, limit, offset),
            )
            rows = cursor.fetchall()
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("review queue unavailable")
        raise HTTPException(status_code=503, detail="review unavailable") from exc
    finally:
        if connection is not None:
            connection.close()

    documents = [
        {
            "doc_id": row[0],
            "collection": row[1],
            "source_label": row[2],
            "source_uri": row[3],
            "rights": row[4],
            "source_kind": row[5],
            "type_doc": row[6],
            "chunk_count": row[7],
            "first_indexed": row[8].isoformat() if row[8] else None,
            "last_indexed": row[9].isoformat() if row[9] else None,
        }
        for row in rows
    ]
    return {
        "total_pending_docs": total_docs,
        "returned": len(documents),
        "offset": offset,
        "documents": documents,
    }


@router.post("/decide")
def review_decide(payload: ReviewDecision, request: Request) -> dict[str, Any]:
    """Promouvoir `needs_review` ou révoquer vers `quarantined`."""
    verified = _require_review_identity(request, endpoint="/review/v2/decide")
    scopes = _load_review_scopes(
        verified,
        collection=payload.collection,
        tenant=payload.tenant,
    )
    scope_sql, scope_params = _scope_filter(scopes)
    target_column = "doc_id" if payload.target_type == "doc" else "chunk_id"
    source_states = (
        ["needs_review"]
        if payload.decision == "reviewed"
        else ["needs_review", "reviewed"]
    )
    pg_dsn = _get_pg_dsn()

    connection: Any | None = None
    try:
        connection = psycopg.connect(pg_dsn)
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                UPDATE rag_chunks SET review_status = %s
                WHERE {target_column} = %s
                  AND review_status = ANY(%s::text[])
                  AND {scope_sql}
                """,
                (
                    payload.decision,
                    payload.target_id,
                    source_states,
                    *scope_params,
                ),
            )
            affected = int(cursor.rowcount)
        connection.commit()
    except Exception as exc:
        if connection is not None:
            connection.rollback()
        logger.error("review decision unavailable")
        raise HTTPException(status_code=503, detail="review unavailable") from exc
    finally:
        if connection is not None:
            connection.close()

    if affected == 0:
        raise HTTPException(status_code=404, detail="review target unavailable")

    cache_invalidated = True
    try:
        cache_cleared = invalidate_cache()
    except Exception:
        cache_cleared = 0
        cache_invalidated = False
        logger.error("local administrative cache invalidation failed")
    logger.info(
        "review decision=%s target_type=%s chunks=%d scope_digest=%s cache_cleared=%d",
        payload.decision,
        payload.target_type,
        affected,
        verified.scope_digest,
        cache_cleared,
    )
    return {
        "target_type": payload.target_type,
        "target_id": payload.target_id,
        "decision": payload.decision,
        "chunks_affected": affected,
        "cache_invalidated_this_worker": cache_invalidated,
        "max_stale_other_workers_s": 0,
    }


__all__ = [
    "PendingQuery",
    "ReviewDecision",
    "list_queue",
    "review_decide",
    "router",
]
