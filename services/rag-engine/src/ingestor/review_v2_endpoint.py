"""Review humaine scopée des contenus issus du pipeline d'ingestion."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping, Sequence
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, HTTPException, Query, Request
from nexus_contracts import (
    ReviewDecisionRequest,
    ReviewDecisionResponse,
    ReviewQueuePayload,
    ReviewQueueResponse,
    Rights,
)
from pydantic import BeforeValidator

try:
    from .collection_config import load_collection_config
    from .identity_v2 import VerifiedInternalIdentity, require_internal_identity
    from .pg_pool import (
        apply_database_budget_before_commit,
        execute_with_database_budget,
        runtime_connection_kwargs_from_env,
        runtime_database_budget,
        runtime_statement_timeout_ms_from_env,
    )
    from .retrieval_scope_v2 import (
        RetrievalScopeError,
        ServerRetrievalScope,
        build_server_readiness_scope,
        effective_signed_collections,
    )
    from .retrieval_v2_endpoint import invalidate_cache
    from .security_v2 import require_bff_service
except (ImportError, ValueError):
    from collection_config import load_collection_config  # type: ignore[no-redef]
    from identity_v2 import (  # type: ignore[no-redef]
        VerifiedInternalIdentity,
        require_internal_identity,
    )
    from pg_pool import (  # type: ignore[no-redef]
        apply_database_budget_before_commit,
        execute_with_database_budget,
        runtime_connection_kwargs_from_env,
        runtime_database_budget,
        runtime_statement_timeout_ms_from_env,
    )
    from retrieval_scope_v2 import (  # type: ignore[no-redef]
        RetrievalScopeError,
        ServerRetrievalScope,
        build_server_readiness_scope,
        effective_signed_collections,
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


def _connect_review_database(pg_dsn: str) -> Any:
    """Ouvrir une connexion de revue bornée côté réseau et PostgreSQL."""
    return psycopg.connect(pg_dsn, **runtime_connection_kwargs_from_env())


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

    try:
        allowed = effective_signed_collections(verified)
    except RetrievalScopeError as exc:
        raise HTTPException(status_code=403, detail="Forbidden") from exc
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
            scope = build_server_readiness_scope(
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


def _parse_review_queue_integers(value: Any) -> Any:
    """Adapter les entiers de l'URL avant la validation stricte du contrat."""
    if not isinstance(value, Mapping):
        return value
    parsed = dict(value)
    for field_name in ("limit", "offset"):
        raw_value = parsed.get(field_name)
        if (
            isinstance(raw_value, str)
            and raw_value.isascii()
            and raw_value.isdecimal()
        ):
            parsed[field_name] = int(raw_value)
    return parsed


@router.get("/queue", response_model=ReviewQueueResponse)
def list_queue(
    request: Request,
    payload: Annotated[
        Annotated[ReviewQueuePayload, Query()],
        BeforeValidator(_parse_review_queue_integers),
    ],
) -> ReviewQueueResponse:
    """Lister uniquement les documents `needs_review` du scope signé."""
    verified = _require_review_identity(request, endpoint="/review/v2/queue")
    scopes = _load_review_scopes(
        verified,
        collection=payload.collection,
        tenant=None,
    )
    scope_sql, scope_params = _scope_filter(scopes)
    pg_dsn = _get_pg_dsn()
    statement_timeout_ms = runtime_statement_timeout_ms_from_env()

    connection: Any | None = None
    try:
        with runtime_database_budget():
            connection = _connect_review_database(pg_dsn)
            with connection.cursor() as cursor:
                execute_with_database_budget(
                    cursor,
                    "SELECT COUNT(*) FROM (SELECT 1 FROM rag_chunks "
                    "WHERE review_status = 'needs_review' AND "
                    + scope_sql
                    + " GROUP BY doc_id, collection) AS scoped_documents",
                    scope_params,
                    statement_timeout_ms=statement_timeout_ms,
                )
                row = cursor.fetchone()
                total_docs = int(row[0]) if row else 0

                execute_with_database_budget(
                    cursor,
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
                    (*scope_params, payload.limit, payload.offset),
                    statement_timeout_ms=statement_timeout_ms,
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
    return ReviewQueueResponse.model_validate(
        {
            "total_pending_docs": total_docs,
            "returned": len(documents),
            "offset": payload.offset,
            "documents": documents,
        }
    )


@router.post("/decide", response_model=ReviewDecisionResponse)
def review_decide(
    payload: ReviewDecisionRequest,
    request: Request,
) -> ReviewDecisionResponse:
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
    statement_timeout_ms = runtime_statement_timeout_ms_from_env()

    connection: Any | None = None
    try:
        with runtime_database_budget():
            connection = _connect_review_database(pg_dsn)
            with connection.cursor() as cursor:
                execute_with_database_budget(
                    cursor,
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
                    statement_timeout_ms=statement_timeout_ms,
                )
                affected = int(cursor.rowcount)
            apply_database_budget_before_commit(
                connection,
                statement_timeout_ms=statement_timeout_ms,
            )
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
    return ReviewDecisionResponse(
        target_type=payload.target_type,
        target_id=payload.target_id,
        decision=payload.decision,
        chunks_affected=affected,
        cache_invalidated_this_worker=cache_invalidated,
        max_stale_other_workers_s=0,
    )


__all__ = [
    "list_queue",
    "review_decide",
    "router",
]
