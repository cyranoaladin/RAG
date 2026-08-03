"""Canaux SQL PostgreSQL déterministes du retrieval hybride v2."""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from contextlib import AbstractContextManager
from numbers import Real
from typing import Any, Literal

from nexus_contracts import Rights

if __package__:
    from .pg_pool import execute_with_database_budget
    from .retrieval_hybrid_v2 import (
        CHANNEL_LIMIT,
        EMBED_DIMENSION,
        CandidateStore,
        RetrievalCandidate,
        RetrievalPipelineError,
    )
    from .retrieval_scope_v2 import ServerRetrievalScope
else:
    from pg_pool import execute_with_database_budget  # type: ignore[no-redef]
    from retrieval_hybrid_v2 import (  # type: ignore[no-redef]
        CHANNEL_LIMIT,
        EMBED_DIMENSION,
        CandidateStore,
        RetrievalCandidate,
        RetrievalPipelineError,
    )
    from retrieval_scope_v2 import ServerRetrievalScope  # type: ignore[no-redef]

_PGVECTOR_ACTIVATION_SQL = "SELECT %s::vector IS NOT NULL"
_DENSE_STRICT_ORDER_SQL = "SET LOCAL hnsw.iterative_scan = 'strict_order'"
_DENSE_ANN_POOL_FACTOR = 4
_DENSE_ANN_POOL_LIMIT = CHANNEL_LIMIT * _DENSE_ANN_POOL_FACTOR
_DENSE_ANN_PROBE_LIMIT = _DENSE_ANN_POOL_LIMIT + 1

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
          AND review_status = 'reviewed'
"""

# Le parcours ANN reste strictement borné à 200 candidats plus une sentinelle.
# L'ordre total est exact dans ce pool seulement; une égalité qui déborde la
# frontière 200/201 est refusée car son appartenance déterministe est inconnue.
_DENSE_SQL = f"""
    WITH hnsw_candidates AS MATERIALIZED (
        SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
               text, page_start, vector::text AS vector_text, review_status,
               collection, tenant, niveau, voie, matiere, statut_enseignement,
               candidat, audience, visibility, school_year, programme_version,
               vector <=> %s::vector AS distance
        FROM public.rag_chunks
        WHERE {_SCOPE_PREDICATE_SQL}
          AND text IS NOT NULL AND btrim(text) <> '' AND vector IS NOT NULL
          AND btrim(source_label) <> '' AND btrim(source_uri) <> ''
          AND btrim(rights) <> ''
        ORDER BY distance ASC
        LIMIT %s
    ),
    ranked_pool AS MATERIALIZED (
        SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
               text, page_start, vector_text, review_status, collection, tenant,
               niveau, voie, matiere, statut_enseignement, candidat, audience,
               visibility, school_year, programme_version, distance,
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
           ranked_pool.review_status, ranked_pool.collection, ranked_pool.tenant,
           ranked_pool.niveau, ranked_pool.voie, ranked_pool.matiere,
           ranked_pool.statut_enseignement, ranked_pool.candidat,
           ranked_pool.audience, ranked_pool.visibility, ranked_pool.school_year,
           ranked_pool.programme_version,
           1 - ranked_pool.distance AS dense_score,
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

_LEXICAL_SQL = f"""
    WITH lexical_query AS MATERIALIZED (SELECT plainto_tsquery('french', %s) AS value)
    SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc, text,
           page_start, vector::text, review_status,
           collection, tenant, niveau, voie, matiere, statut_enseignement,
           candidat, audience, visibility, school_year, programme_version,
           ts_rank_cd(text_tsv, lexical_query.value, 32) AS lexical_score
    FROM public.rag_chunks
    CROSS JOIN lexical_query
    WHERE {_SCOPE_PREDICATE_SQL}
      AND text IS NOT NULL AND btrim(text) <> '' AND vector IS NOT NULL
      AND btrim(source_label) <> '' AND btrim(source_uri) <> ''
      AND btrim(rights) <> ''
      AND text_tsv @@ lexical_query.value
    ORDER BY lexical_score DESC, chunk_id ASC
    LIMIT %s
"""

_ROW_CARDINALITY = 22
_DENSE_ROW_CARDINALITY = _ROW_CARDINALITY + 1
_SCORE_INDEX = _ROW_CARDINALITY - 1
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


def _string_array(value: object) -> tuple[str, ...]:
    if isinstance(value, str | bytes) or not isinstance(value, Sequence):
        raise RetrievalPipelineError("invalid database string array")
    normalized = tuple(_string(item) for item in value)
    if not normalized:
        raise RetrievalPipelineError("invalid database string array")
    return normalized


def _scope_params(scope: ServerRetrievalScope) -> tuple[object, ...]:
    if not isinstance(scope, ServerRetrievalScope) or scope.review_status != "reviewed":
        raise RetrievalPipelineError("invalid retrieval scope")
    scalars = (
        scope.collection,
        scope.tenant,
        scope.niveau,
        scope.matiere,
        scope.statut_enseignement,
        scope.candidat,
        scope.school_year,
        scope.programme_version,
    )
    if any(not isinstance(value, str) or not value.strip() for value in scalars):
        raise RetrievalPipelineError("invalid retrieval scope")
    if scope.voie is not None and (
        not isinstance(scope.voie, str) or not scope.voie.strip()
    ):
        raise RetrievalPipelineError("invalid retrieval scope")
    if not scope.audiences or not scope.rights or not scope.visibilities:
        raise RetrievalPipelineError("invalid retrieval scope")
    audiences = [_nonblank(value) for value in scope.audiences]
    visibilities = [_nonblank(value) for value in scope.visibilities]
    if any(not isinstance(right, Rights) for right in scope.rights):
        raise RetrievalPipelineError("invalid retrieval scope")
    rights = [right.value for right in scope.rights]
    candidates = list(dict.fromkeys((scope.candidat, "both")))
    return (
        scope.collection,
        scope.tenant,
        scope.niveau,
        scope.voie,
        scope.matiere,
        scope.statut_enseignement,
        candidates,
        audiences,
        rights,
        visibilities,
        scope.school_year,
        scope.programme_version,
    )


def _verify_scope_row(row: Sequence[object], scope: ServerRetrievalScope) -> None:
    expected_rights = {right.value for right in scope.rights}
    expected_values = (
        (row[10], scope.collection),
        (row[11], scope.tenant),
        (row[12], scope.niveau),
        (row[13], scope.voie),
        (row[14], scope.matiere),
        (row[15], scope.statut_enseignement),
        (row[19], scope.school_year),
        (row[20], scope.programme_version),
    )
    if any(actual != expected for actual, expected in expected_values):
        raise RetrievalPipelineError("database row outside retrieval scope")
    if _string(row[4]) not in expected_rights:
        raise RetrievalPipelineError("database row outside retrieval scope")
    if _string(row[16]) not in {scope.candidat, "both"}:
        raise RetrievalPipelineError("database row outside retrieval scope")
    if not set(_string_array(row[17])).intersection(scope.audiences):
        raise RetrievalPipelineError("database row outside retrieval scope")
    if _string(row[18]) not in set(scope.visibilities):
        raise RetrievalPipelineError("database row outside retrieval scope")


def _map_row(
    row: object,
    channel: Literal["dense", "lexical"],
    scope: ServerRetrievalScope,
) -> RetrievalCandidate:
    if isinstance(row, str | bytes) or not isinstance(row, Sequence):
        raise RetrievalPipelineError("invalid database row")
    if len(row) != _ROW_CARDINALITY:
        raise RetrievalPipelineError("invalid database row")

    review_status = row[9]
    if review_status != "reviewed":
        raise RetrievalPipelineError("invalid review status")
    _verify_scope_row(row, scope)
    score = _finite_float(row[_SCORE_INDEX])
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

    def __init__(
        self,
        connection_provider: _ConnectionProvider,
        scope: ServerRetrievalScope,
        *,
        statement_timeout_ms: int | None = None,
    ) -> None:
        self._connection_provider = connection_provider
        self._scope = scope
        self._scope_params = _scope_params(scope)
        self._statement_timeout_ms = statement_timeout_ms

    def _execute(
        self,
        cursor: Any,
        sql: str,
        params: object = None,
    ) -> Any:
        if self._statement_timeout_ms is None:
            return cursor.execute(sql, params)
        return execute_with_database_budget(
            cursor,
            sql,
            params,
            statement_timeout_ms=self._statement_timeout_ms,
        )

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
                    self._execute(cursor, setup_sql, setup_params)
                self._execute(cursor, sql, params)
                fetched = cursor.fetchall()
                if isinstance(fetched, str | bytes) or not isinstance(fetched, Sequence):
                    raise RetrievalPipelineError("invalid database result")
                if len(fetched) > limit:
                    raise RetrievalPipelineError("channel limit exceeded")
                if channel == "dense":
                    return [
                        _map_row(_dense_payload(row), channel, self._scope)
                        for row in fetched
                    ]
                return [_map_row(row, channel, self._scope) for row in fetched]

    def dense(
        self, *, query_vector: Sequence[float], collection: str, limit: int
    ) -> Sequence[RetrievalCandidate]:
        failed = False
        candidates: list[RetrievalCandidate] = []
        try:
            normalized_vector = _query_vector(query_vector)
            normalized_collection = _nonblank(collection)
            if normalized_collection != self._scope.collection:
                raise RetrievalPipelineError("collection outside retrieval scope")
            normalized_limit = _limit(limit)
            vector_text = "[" + ",".join(str(value) for value in normalized_vector) + "]"
            candidates = self._fetch(
                _DENSE_SQL,
                (
                    vector_text,
                    *self._scope_params,
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
            if normalized_collection != self._scope.collection:
                raise RetrievalPipelineError("collection outside retrieval scope")
            normalized_limit = _limit(limit)
            candidates = self._fetch(
                _LEXICAL_SQL,
                (normalized_query, *self._scope_params, normalized_limit),
                limit=normalized_limit,
                channel="lexical",
            )
        except Exception:
            failed = True
        if failed:
            raise RetrievalPipelineError("lexical channel query failed") from None
        return candidates
