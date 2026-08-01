"""Canaux SQL PostgreSQL déterministes du retrieval hybride v2."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from numbers import Real
from typing import Any, Literal

from ingestor.retrieval_hybrid_v2 import (
    CHANNEL_LIMIT,
    EMBED_DIMENSION,
    CandidateStore,
    RetrievalCandidate,
    RetrievalPipelineError,
)

_PGVECTOR_ACTIVATION_SQL = "SELECT %s::vector IS NOT NULL"
_DENSE_STRICT_ORDER_SQL = "SET LOCAL hnsw.iterative_scan = 'strict_order'"
_DENSE_ANN_POOL_FACTOR = 4
_DENSE_ANN_POOL_LIMIT = CHANNEL_LIMIT * _DENSE_ANN_POOL_FACTOR
_DENSE_ANN_PROBE_LIMIT = _DENSE_ANN_POOL_LIMIT + 1

# Le parcours ANN reste strictement borné à 200 candidats plus une sentinelle.
# L'ordre total est exact dans ce pool seulement; une égalité qui déborde la
# frontière 200/201 est refusée car son appartenance déterministe est inconnue.
_DENSE_SQL = """
    WITH hnsw_candidates AS MATERIALIZED (
        SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
               text, page_start, vector::text AS vector_text, review_status,
               vector <=> %s::vector AS distance
        FROM rag_chunks
        WHERE collection = %s AND review_status = 'reviewed'
          AND text IS NOT NULL AND btrim(text) <> '' AND vector IS NOT NULL
          AND btrim(source_label) <> '' AND btrim(source_uri) <> ''
          AND btrim(rights) <> ''
        ORDER BY distance ASC
        LIMIT %s
    ),
    ranked_pool AS MATERIALIZED (
        SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
               text, page_start, vector_text, review_status, distance,
               row_number() OVER (ORDER BY distance ASC, chunk_id ASC) AS pool_rank
        FROM hnsw_candidates
    ),
    pool_diagnostics AS MATERIALIZED (
        SELECT
          max(distance) FILTER (WHERE pool_rank = %s) AS boundary_distance,
          max(distance) FILTER (WHERE pool_rank = %s) AS sentinel_distance
        FROM ranked_pool
    )
    SELECT ranked_pool.chunk_id, ranked_pool.doc_id, ranked_pool.source_label,
           ranked_pool.source_uri, ranked_pool.rights, ranked_pool.type_doc,
           ranked_pool.text, ranked_pool.page_start, ranked_pool.vector_text,
           ranked_pool.review_status, 1 - ranked_pool.distance AS dense_score,
           (
             pool_diagnostics.boundary_distance IS NOT NULL
             AND pool_diagnostics.sentinel_distance IS NOT NULL
             AND pool_diagnostics.boundary_distance
                 = pool_diagnostics.sentinel_distance
           ) AS tie_overflow
    FROM ranked_pool
    CROSS JOIN pool_diagnostics
    WHERE ranked_pool.pool_rank <= %s
    ORDER BY ranked_pool.distance ASC, ranked_pool.chunk_id ASC
"""

_LEXICAL_SQL = """
    WITH lexical_query AS MATERIALIZED (SELECT plainto_tsquery('french', %s) AS value)
    SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc, text,
           page_start, vector::text, review_status,
           ts_rank_cd(text_tsv, lexical_query.value, 32) AS lexical_score
    FROM rag_chunks
    CROSS JOIN lexical_query
    WHERE collection = %s AND review_status = 'reviewed'
      AND text IS NOT NULL AND btrim(text) <> '' AND vector IS NOT NULL
      AND btrim(source_label) <> '' AND btrim(source_uri) <> ''
      AND btrim(rights) <> ''
      AND text_tsv @@ lexical_query.value
    ORDER BY lexical_score DESC, chunk_id ASC
    LIMIT %s
"""

_ROW_CARDINALITY = 11
_DENSE_ROW_CARDINALITY = _ROW_CARDINALITY + 1
_ConnectionProvider = Callable[[], AbstractContextManager[Any]]


def _nonblank(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RetrievalPipelineError("invalid nonblank value")
    return value


def _string(value: object, *, allow_blank: bool = False) -> str:
    if not isinstance(value, str) or (not allow_blank and not value.strip()):
        raise RetrievalPipelineError("invalid database string")
    return value


def _limit(value: object) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or not 1 <= value <= CHANNEL_LIMIT
    ):
        raise RetrievalPipelineError("invalid channel limit")
    return value


def _finite_float(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise RetrievalPipelineError("invalid finite number")
    normalized = float(value)
    if not math.isfinite(normalized):
        raise RetrievalPipelineError("invalid finite number")
    return normalized


def _query_vector(value: object) -> tuple[float, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise RetrievalPipelineError("invalid query vector")
    if len(value) != EMBED_DIMENSION:
        raise RetrievalPipelineError("invalid query vector")
    normalized = tuple(_finite_float(component) for component in value)
    norm = math.hypot(*normalized)
    if not math.isfinite(norm) or norm == 0.0:
        raise RetrievalPipelineError("invalid query vector")
    return normalized


def _stored_vector(value: object) -> tuple[float, ...]:
    if not isinstance(value, str) or not value.startswith("[") or not value.endswith("]"):
        raise RetrievalPipelineError("invalid stored vector")
    body = value[1:-1]
    components = body.split(",") if body else []
    if len(components) != EMBED_DIMENSION or any(not component.strip() for component in components):
        raise RetrievalPipelineError("invalid stored vector")
    try:
        return tuple(float(component) for component in components)
    except (OverflowError, ValueError):
        raise RetrievalPipelineError("invalid stored vector") from None


def _page(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise RetrievalPipelineError("invalid page")
    return value if value > 0 else None


def _map_row(row: object, channel: Literal["dense", "lexical"]) -> RetrievalCandidate:
    if isinstance(row, str | bytes) or not isinstance(row, Sequence):
        raise RetrievalPipelineError("invalid database row")
    if len(row) != _ROW_CARDINALITY:
        raise RetrievalPipelineError("invalid database row")

    review_status = row[9]
    if review_status != "reviewed":
        raise RetrievalPipelineError("invalid review status")
    score = _finite_float(row[10])
    return RetrievalCandidate(
        chunk_id=_string(row[0]),
        doc_id=_string(row[1]),
        source_label=_string(row[2]),
        source_uri=_string(row[3]),
        rights=_string(row[4]),
        type_doc=_string(row[5], allow_blank=True),
        text=_string(row[6]),
        page_start=_page(row[7]),
        vector=_stored_vector(row[8]),
        review_status="reviewed",
        dense_score=score if channel == "dense" else None,
        lexical_score=score if channel == "lexical" else None,
    )


def _dense_payload(row: object) -> Sequence[object]:
    if isinstance(row, str | bytes) or not isinstance(row, Sequence):
        raise RetrievalPipelineError("invalid dense database row")
    if len(row) != _DENSE_ROW_CARDINALITY:
        raise RetrievalPipelineError("invalid dense database row")
    tie_overflow = row[_ROW_CARDINALITY]
    if not isinstance(tie_overflow, bool):
        raise RetrievalPipelineError("invalid dense tie diagnostic")
    if tie_overflow:
        raise RetrievalPipelineError("dense ann tie overflow")
    return row[:_ROW_CARDINALITY]


class PgCandidateStore(CandidateStore):
    """Charge les candidats revus via deux requêtes SQL bornées et paramétrées."""

    def __init__(self, connection_provider: _ConnectionProvider) -> None:
        self._connection_provider = connection_provider

    def _fetch(
        self,
        sql: str,
        params: tuple[object, ...],
        *,
        limit: int,
        channel: Literal["dense", "lexical"],
        setup_statements: Sequence[
            tuple[str, tuple[object, ...] | None]
        ] = (),
    ) -> list[RetrievalCandidate]:
        with self._connection_provider() as connection:
            with connection.cursor() as cursor:
                for setup_sql, setup_params in setup_statements:
                    cursor.execute(setup_sql, setup_params)
                cursor.execute(sql, params)
                fetched = cursor.fetchall()
                if isinstance(fetched, str | bytes) or not isinstance(fetched, Sequence):
                    raise RetrievalPipelineError("invalid database result")
                if len(fetched) > limit:
                    raise RetrievalPipelineError("channel limit exceeded")
                if channel == "dense":
                    return [_map_row(_dense_payload(row), channel) for row in fetched]
                return [_map_row(row, channel) for row in fetched]

    def dense(
        self, *, query_vector: Sequence[float], collection: str, limit: int
    ) -> Sequence[RetrievalCandidate]:
        failed = False
        candidates: list[RetrievalCandidate] = []
        try:
            normalized_vector = _query_vector(query_vector)
            normalized_collection = _nonblank(collection)
            normalized_limit = _limit(limit)
            vector_text = "[" + ",".join(str(value) for value in normalized_vector) + "]"
            candidates = self._fetch(
                _DENSE_SQL,
                (
                    vector_text,
                    normalized_collection,
                    _DENSE_ANN_PROBE_LIMIT,
                    _DENSE_ANN_POOL_LIMIT,
                    _DENSE_ANN_PROBE_LIMIT,
                    normalized_limit,
                ),
                limit=normalized_limit,
                channel="dense",
                setup_statements=(
                    (_PGVECTOR_ACTIVATION_SQL, (vector_text,)),
                    (_DENSE_STRICT_ORDER_SQL, None),
                ),
            )
        except Exception:
            failed = True
        if failed:
            raise RetrievalPipelineError("dense channel query failed") from None
        return candidates

    def lexical(
        self, *, raw_query: str, collection: str, limit: int
    ) -> Sequence[RetrievalCandidate]:
        failed = False
        candidates: list[RetrievalCandidate] = []
        try:
            normalized_query = _nonblank(raw_query)
            normalized_collection = _nonblank(collection)
            normalized_limit = _limit(limit)
            candidates = self._fetch(
                _LEXICAL_SQL,
                (normalized_query, normalized_collection, normalized_limit),
                limit=normalized_limit,
                channel="lexical",
            )
        except Exception:
            failed = True
        if failed:
            raise RetrievalPipelineError("lexical channel query failed") from None
        return candidates
