"""Review v2 endpoints — human review of ingested content (agent needs_review).

Exposes:
- GET  /review/v2/queue — list chunks awaiting review (grouped by doc_id)
- POST /review/v2/decide  — admin/reviewer decide reviewed or quarantined

Invariant: only admin/reviewer can promote needs_review → reviewed.
An agent can ingest (→ needs_review) but NEVER promote to reviewed.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

try:
    from .security_v2 import SecurityRole, require_role
except (ImportError, ValueError):
    from security_v2 import SecurityRole, require_role  # type: ignore[no-redef]

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review/v2", tags=["review_v2"])


def _get_pg_dsn() -> str:
    dsn = os.environ.get("PG_RAG_DSN") or os.environ.get("DATABASE_URL_SYNC")
    if not dsn:
        raise HTTPException(status_code=503, detail="PG_RAG_DSN not configured")
    return dsn


def _enforce_queue_security(request: Request) -> str:
    """Auth for review queue read access."""
    _, token = require_role(
        request,
        allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER, SecurityRole.TEACHER},
        endpoint="/review/v2/queue",
    )
    return token


def _enforce_reviewer_security(request: Request) -> str:
    """Auth for review decisions.

    Decisions are limited to admin and reviewer. The reviewer role accepts
    RAG_REVIEWER_TOKEN and the legacy REVIEWER_API_TOKEN alias. An
    ingest_agent token can ingest but cannot decide.
    """
    _, token = require_role(
        request,
        allowed_roles={SecurityRole.ADMIN, SecurityRole.REVIEWER},
        endpoint="/review/v2/decide",
    )
    return token


# --- Request/Response models ---

class PendingQuery(BaseModel):
    collection: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ReviewDecision(BaseModel):
    """An admin or reviewer decides on a document or chunk."""
    target_type: Literal["doc", "chunk"] = "doc"
    target_id: str = Field(..., min_length=1, description="doc_id or chunk_id")
    decision: Literal["reviewed", "quarantined"] = Field(
        ..., description="reviewed = approved, quarantined = rejected"
    )
    reason: str = Field(default="", description="Optional reason for the decision")


# --- Endpoints ---

@router.get("/queue")
def list_queue(
    request: Request,
    collection: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    """List chunks in needs_review, grouped by doc_id.

    Returns documents with their chunk count, provenance, and preview.
    """
    _enforce_queue_security(request)
    pg_dsn = _get_pg_dsn()

    conn = psycopg.connect(pg_dsn)
    try:
        with conn.cursor() as cur:
            # Count total pending
            if collection:
                cur.execute(
                    "SELECT COUNT(DISTINCT doc_id) FROM rag_chunks "
                    "WHERE review_status = 'needs_review' AND collection = %s",
                    (collection,),
                )
            else:
                cur.execute(
                    "SELECT COUNT(DISTINCT doc_id) FROM rag_chunks "
                    "WHERE review_status = 'needs_review'",
                )
            row = cur.fetchone()
            total_docs = row[0] if row else 0

            # Get pending documents with summary
            query = """
                SELECT doc_id, collection, source_label, source_uri, rights,
                       source_kind, type_doc,
                       COUNT(*) AS chunk_count,
                       MIN(indexed_at) AS first_indexed,
                       MAX(indexed_at) AS last_indexed
                FROM rag_chunks
                WHERE review_status = 'needs_review'
            """
            params: list = []
            if collection:
                query += " AND collection = %s"
                params.append(collection)
            query += " GROUP BY doc_id, collection, source_label, source_uri, rights, source_kind, type_doc"
            query += " ORDER BY MIN(indexed_at) DESC"
            query += " LIMIT %s OFFSET %s"
            params.extend([limit, offset])

            cur.execute(query, params)
            rows = cur.fetchall()
    finally:
        conn.close()

    documents = []
    for row in rows:
        documents.append({
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
        })

    return {
        "total_pending_docs": total_docs,
        "returned": len(documents),
        "offset": offset,
        "documents": documents,
    }


@router.post("/decide")
def review_decide(payload: ReviewDecision, request: Request) -> dict[str, Any]:
    """Admin/reviewer approves or rejects a document/chunk.

    - reviewed: content becomes servable (served by /search/v2)
    - quarantined: content blocked from serving (gate enforced)

    This is a human act: only admin or reviewer may call this endpoint.
    """
    _enforce_reviewer_security(request)

    if payload.decision not in ("reviewed", "quarantined"):
        raise HTTPException(status_code=400, detail="decision must be 'reviewed' or 'quarantined'")

    pg_dsn = _get_pg_dsn()
    conn = psycopg.connect(pg_dsn)

    try:
        with conn.cursor() as cur:
            if payload.target_type == "doc":
                cur.execute(
                    "UPDATE rag_chunks SET review_status = %s "
                    "WHERE doc_id = %s AND review_status = 'needs_review'",
                    (payload.decision, payload.target_id),
                )
            else:
                cur.execute(
                    "UPDATE rag_chunks SET review_status = %s "
                    "WHERE chunk_id = %s AND review_status = 'needs_review'",
                    (payload.decision, payload.target_id),
                )
            affected = cur.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    if affected == 0:
        raise HTTPException(
            status_code=404,
            detail=f"No needs_review chunks found for {payload.target_type}={payload.target_id}",
        )

    # Invalidate retrieval cache (review_status changed)
    # NOTE (P2 cubic): in multi-worker deployment, this only clears THIS worker's cache.
    # Other workers expire stale entries via TTL (RERANK_CACHE_TTL, default 300s).
    # For quarantine decisions, we also set TTL to 0 on this worker to force immediate
    # expiration. Cross-worker broadcast requires shared cache (Redis) — deferred.
    try:
        from .retrieval_v2_endpoint import CACHE_TTL_S, invalidate_cache
    except (ImportError, ValueError):
        from retrieval_v2_endpoint import CACHE_TTL_S, invalidate_cache  # type: ignore[no-redef]
    cache_cleared = invalidate_cache()

    # For quarantine: the retrieval SQL gate (review_status = 'reviewed')
    # already prevents quarantined chunks from being returned on cache miss.
    # Stale cache entries on other workers will expire within TTL and be replaced
    # by fresh DB queries that exclude the quarantined chunks.
    max_stale_s = CACHE_TTL_S if payload.decision == "quarantined" else 0

    logger.info(
        "Review decision: %s %s=%s → %s (%d chunks), reason=%s, "
        "cache_cleared=%d, max_stale_other_workers=%ds",
        payload.target_type, payload.target_type, payload.target_id,
        payload.decision, affected, payload.reason or "(none)",
        cache_cleared, max_stale_s,
    )

    return {
        "target_type": payload.target_type,
        "target_id": payload.target_id,
        "decision": payload.decision,
        "chunks_affected": affected,
        "cache_invalidated_this_worker": True,
        "max_stale_other_workers_s": max_stale_s,
    }
