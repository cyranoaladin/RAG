"""Review v2 endpoints — human review of ingested content (agent needs_review).

Exposes:
- GET  /review/v2/pending — list chunks awaiting review (grouped by doc_id)
- POST /review/v2/decide  — teacher approves (reviewed) or rejects (quarantined)

Invariant: only a human (teacher) can promote needs_review → reviewed.
An agent can ingest (→ needs_review) but NEVER promote to reviewed.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Literal

import psycopg
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/review/v2", tags=["review_v2"])


def _get_pg_dsn() -> str:
    dsn = os.environ.get("PG_RAG_DSN") or os.environ.get("DATABASE_URL_SYNC")
    if not dsn:
        raise HTTPException(status_code=503, detail="PG_RAG_DSN not configured")
    return dsn


def _enforce_security(request: Request) -> str:
    """Auth check — same token as other endpoints."""
    token_env = os.getenv("INGESTOR_API_TOKEN") or os.getenv("INGEST_AUTH_TOKEN")
    if not token_env:
        raise HTTPException(status_code=503, detail="API token not configured")
    headers = request.headers
    header_token = headers.get("x-api-token")
    if not header_token:
        auth = headers.get("authorization")
        if isinstance(auth, str) and auth.strip():
            value = auth.strip()
            if value.lower().startswith("bearer "):
                header_token = value.split(" ", 1)[1].strip()
            else:
                header_token = value
    if header_token != token_env:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return header_token or ""


# --- Request/Response models ---

class PendingQuery(BaseModel):
    collection: str | None = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class ReviewDecision(BaseModel):
    """A teacher's decision on a document or chunk."""
    target_type: Literal["doc", "chunk"] = "doc"
    target_id: str = Field(..., min_length=1, description="doc_id or chunk_id")
    decision: Literal["reviewed", "quarantined"] = Field(
        ..., description="reviewed = approved, quarantined = rejected"
    )
    reason: str = Field(default="", description="Optional reason for the decision")


# --- Endpoints ---

@router.get("/pending")
def list_pending(
    request: Request,
    collection: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    """List chunks in needs_review, grouped by doc_id.

    Returns documents with their chunk count, provenance, and preview.
    """
    _enforce_security(request)
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
    """Teacher approves or rejects a document/chunk.

    - reviewed: content becomes servable (served by /search/v2)
    - quarantined: content blocked from serving (gate enforced)

    This is a HUMAN act. Agents cannot call this endpoint to promote
    their own ingested content — the token is the same but the governance
    contract (D-AGENT-NEEDS-REVIEW) is that agents submit, humans review.
    """
    _enforce_security(request)

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
    try:
        from .retrieval_v2_endpoint import invalidate_cache
    except (ImportError, ValueError):
        from retrieval_v2_endpoint import invalidate_cache  # type: ignore[no-redef]
    invalidate_cache()

    logger.info(
        "Review decision: %s %s=%s → %s (%d chunks), reason=%s",
        payload.target_type, payload.target_type, payload.target_id,
        payload.decision, affected, payload.reason or "(none)",
    )

    return {
        "target_type": payload.target_type,
        "target_id": payload.target_id,
        "decision": payload.decision,
        "chunks_affected": affected,
        "cache_invalidated": True,
    }
