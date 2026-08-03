"""Tests des deux canaux SQL PostgreSQL du retrieval hybride v2."""

from __future__ import annotations

import math
from collections.abc import Sequence
from types import TracebackType
from typing import Any

import pytest
from nexus_contracts import Rights

from ingestor.retrieval_hybrid_v2 import (
    CHANNEL_LIMIT,
    RetrievalCandidate,
    RetrievalPipelineError,
    reciprocal_rank_fusion,
)
from ingestor.retrieval_pg_v2 import (
    _DENSE_ANN_POOL_FACTOR,
    _DENSE_ANN_POOL_LIMIT,
    _DENSE_ANN_PROBE_LIMIT,
    PgCandidateStore,
)
from ingestor.retrieval_scope_v2 import ServerRetrievalScope

VECTOR = (1.0, *([0.0] * 1023))
VECTOR_TEXT = "[" + ",".join(str(value) for value in VECTOR) + "]"
SCOPE = ServerRetrievalScope(
    tenant="libre_terminale",
    niveau="terminale",
    voie="generale",
    matiere="maths",
    statut_enseignement="specialite",
    candidat="individuel",
    audiences=("libre", "tous"),
    rights=(Rights.officiel_public, Rights.public_allowed),
    visibilities=("public",),
    school_year="2026-2027",
    collection="libre_terminale",
    programme_version="BOEN_special_8_2019-07-25",
    scope_id="lot41_test_scope",
    scope_digest="a" * 64,
    source_sha256="b" * 64,
)


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.split())


DENSE_SQL = _normalize_sql(
    """
    WITH hnsw_candidates AS MATERIALIZED (
        SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc,
               text, page_start, vector::text AS vector_text, review_status,
               collection, tenant, niveau, voie, matiere, statut_enseignement,
               candidat, audience, visibility, school_year, programme_version,
               vector <=> %s::vector AS distance
        FROM public.rag_chunks
        WHERE collection = %s
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
)

DENSE_STRICT_ORDER_SQL = "SET LOCAL hnsw.iterative_scan = 'strict_order'"
PGVECTOR_ACTIVATION_SQL = "SELECT %s::vector IS NOT NULL"

LEXICAL_SQL = _normalize_sql(
    """
    WITH lexical_query AS MATERIALIZED (SELECT plainto_tsquery('french', %s) AS value)
    SELECT chunk_id, doc_id, source_label, source_uri, rights, type_doc, text,
           page_start, vector::text, review_status,
           collection, tenant, niveau, voie, matiere, statut_enseignement,
           candidat, audience, visibility, school_year, programme_version,
           ts_rank_cd(text_tsv, lexical_query.value, 32) AS lexical_score
    FROM public.rag_chunks
    CROSS JOIN lexical_query
    WHERE collection = %s
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
      AND text IS NOT NULL AND btrim(text) <> '' AND vector IS NOT NULL
      AND btrim(source_label) <> '' AND btrim(source_uri) <> ''
      AND btrim(rights) <> ''
      AND text_tsv @@ lexical_query.value
    ORDER BY lexical_score DESC, chunk_id ASC
    LIMIT %s
    """
)


def _row(
    *,
    chunk_id: str = "chunk-a",
    doc_id: str = "doc-a",
    source_label: str = "Référentiel officiel",
    source_uri: str = "https://example.test/source",
    rights: str = Rights.officiel_public.value,
    type_doc: str = "programme",
    text: str = "Une ressource qui enseigne réellement la notion.",
    page_start: object = 7,
    vector_text: object = VECTOR_TEXT,
    review_status: object = "reviewed",
    collection: object = SCOPE.collection,
    tenant: object = SCOPE.tenant,
    niveau: object = SCOPE.niveau,
    voie: object = SCOPE.voie,
    matiere: object = SCOPE.matiere,
    statut_enseignement: object = SCOPE.statut_enseignement,
    candidat: object = SCOPE.candidat,
    audience: object = list(SCOPE.audiences),
    visibility: object = SCOPE.visibilities[0],
    school_year: object = SCOPE.school_year,
    programme_version: object = SCOPE.programme_version,
    score: object = 0.75,
) -> tuple[object, ...]:
    return (
        chunk_id,
        doc_id,
        source_label,
        source_uri,
        rights,
        type_doc,
        text,
        page_start,
        vector_text,
        review_status,
        collection,
        tenant,
        niveau,
        voie,
        matiere,
        statut_enseignement,
        candidat,
        audience,
        visibility,
        school_year,
        programme_version,
        score,
    )


def _dense_row(*, tie_overflow: object = False, **overrides: object) -> tuple[object, ...]:
    return (*_row(**overrides), tie_overflow)


class CursorSpy:
    def __init__(
        self,
        events: list[tuple[Any, ...]],
        rows: object,
        *,
        fail_at: str | None = None,
    ) -> None:
        self.events = events
        self.rows = rows
        self.fail_at = fail_at
        self.executions: list[tuple[str, tuple[object, ...] | None]] = []

    def __enter__(self) -> CursorSpy:
        self.events.append(("cursor-enter",))
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        self.events.append(("cursor-exit", exc_type))
        return False

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        self.events.append(("execute",))
        normalized_sql = _normalize_sql(sql)
        self.executions.append((normalized_sql, params))
        fails_on_activation = (
            self.fail_at == "activation" and normalized_sql == PGVECTOR_ACTIVATION_SQL
        )
        fails_on_set = self.fail_at == "set" and normalized_sql == DENSE_STRICT_ORDER_SQL
        fails_on_select = self.fail_at == "execute" and normalized_sql in {
            DENSE_SQL,
            LEXICAL_SQL,
        }
        if fails_on_activation or fails_on_set or fails_on_select:
            raise RuntimeError("query leaked: postgresql://secret@db/rag")

    def fetchall(self) -> object:
        self.events.append(("fetchall",))
        if self.fail_at == "fetchall":
            raise RuntimeError("fetch leaked: postgresql://secret@db/rag")
        return self.rows


class ConnectionSpy:
    def __init__(self, cursor: CursorSpy) -> None:
        self.cursor_spy = cursor

    def cursor(self) -> CursorSpy:
        self.cursor_spy.events.append(("cursor-create",))
        return self.cursor_spy


class FreshBackendCursor(CursorSpy):
    """Reproduit un backend où les GUC pgvector ne sont pas encore enregistrés."""

    def __init__(self, events: list[tuple[Any, ...]], rows: object) -> None:
        super().__init__(events, rows)
        self.pgvector_loaded = False

    def execute(self, sql: str, params: tuple[object, ...] | None = None) -> None:
        normalized_sql = _normalize_sql(sql)
        if normalized_sql == DENSE_STRICT_ORDER_SQL and not self.pgvector_loaded:
            raise RuntimeError("unrecognized configuration parameter hnsw.iterative_scan")
        super().execute(sql, params)
        if normalized_sql == PGVECTOR_ACTIVATION_SQL:
            self.pgvector_loaded = True


class ProviderSpy:
    def __init__(
        self,
        rows: object,
        *,
        fail_at: str | None = None,
    ) -> None:
        self.events: list[tuple[Any, ...]] = []
        self.calls = 0
        self.fail_at = fail_at
        self.cursor = CursorSpy(self.events, rows, fail_at=fail_at)
        self.connection = ConnectionSpy(self.cursor)

    def __call__(self) -> ProviderSpy:
        self.calls += 1
        self.events.append(("provider-call",))
        if self.fail_at == "provider":
            raise RuntimeError("provider leaked: postgresql://secret@db/rag")
        return self

    def __enter__(self) -> ConnectionSpy:
        self.events.append(("connection-enter",))
        if self.fail_at == "connection-enter":
            raise RuntimeError("connection leaked: postgresql://secret@db/rag")
        return self.connection

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_value, traceback
        self.events.append(("connection-exit", exc_type))
        return False


def _dense(provider: ProviderSpy, **overrides: object) -> Sequence[RetrievalCandidate]:
    arguments: dict[str, object] = {
        "query_vector": VECTOR,
        "collection": "libre_terminale",
        "limit": CHANNEL_LIMIT,
    }
    arguments.update(overrides)
    return PgCandidateStore(provider, SCOPE).dense(**arguments)  # type: ignore[arg-type]


def _dense_params(
    collection: str = "libre_terminale",
    limit: int = CHANNEL_LIMIT,
) -> tuple[object, ...]:
    return (
        VECTOR_TEXT,
        *_scope_params(collection=collection),
        _DENSE_ANN_PROBE_LIMIT,
        _DENSE_ANN_POOL_LIMIT,
        _DENSE_ANN_PROBE_LIMIT,
        limit,
    )


def _scope_params(*, collection: str = SCOPE.collection) -> tuple[object, ...]:
    return (
        collection,
        SCOPE.tenant,
        SCOPE.niveau,
        SCOPE.voie,
        SCOPE.matiere,
        SCOPE.statut_enseignement,
        [SCOPE.candidat, "both"],
        list(SCOPE.audiences),
        [right.value for right in SCOPE.rights],
        list(SCOPE.visibilities),
        SCOPE.school_year,
        SCOPE.programme_version,
    )


def _lexical(provider: ProviderSpy, **overrides: object) -> Sequence[RetrievalCandidate]:
    arguments: dict[str, object] = {
        "raw_query": "question brute",
        "collection": "libre_terminale",
        "limit": CHANNEL_LIMIT,
    }
    arguments.update(overrides)
    return PgCandidateStore(provider, SCOPE).lexical(**arguments)  # type: ignore[arg-type]


def test_dense_uses_the_exact_parameterized_reviewed_only_query() -> None:
    provider = ProviderSpy([_dense_row()])

    candidates = _dense(provider)

    assert provider.cursor.executions == [
        (PGVECTOR_ACTIVATION_SQL, (VECTOR_TEXT,)),
        (DENSE_STRICT_ORDER_SQL, None),
        (DENSE_SQL, _dense_params()),
    ]
    assert candidates == [
        RetrievalCandidate(
            chunk_id="chunk-a",
            doc_id="doc-a",
            source_label="Référentiel officiel",
            source_uri="https://example.test/source",
            rights=Rights.officiel_public.value,
            type_doc="programme",
            text="Une ressource qui enseigne réellement la notion.",
            page_start=7,
            vector=VECTOR,
            review_status="reviewed",
            dense_score=0.75,
        )
    ]


def test_dense_initializes_pgvector_before_strict_order_on_a_fresh_backend() -> None:
    provider = ProviderSpy([_dense_row()])
    provider.cursor = FreshBackendCursor(provider.events, [_dense_row()])
    provider.connection = ConnectionSpy(provider.cursor)

    candidates = _dense(provider)

    assert candidates[0].chunk_id == "chunk-a"
    assert provider.cursor.executions == [
        (PGVECTOR_ACTIVATION_SQL, (VECTOR_TEXT,)),
        (DENSE_STRICT_ORDER_SQL, None),
        (DENSE_SQL, _dense_params()),
    ]


def test_dense_sql_is_one_bounded_ann_scan_with_determinism_inside_the_pool() -> None:
    assert _DENSE_ANN_POOL_FACTOR == 4
    assert _DENSE_ANN_POOL_LIMIT == CHANNEL_LIMIT * 4 == 200
    assert _DENSE_ANN_PROBE_LIMIT == _DENSE_ANN_POOL_LIMIT + 1 == 201
    assert DENSE_SQL.count("FROM public.rag_chunks") == 1
    assert "FROM rag_chunks" not in DENSE_SQL
    assert LEXICAL_SQL.count("FROM public.rag_chunks") == 1
    assert "FROM rag_chunks" not in LEXICAL_SQL
    assert DENSE_SQL.count("collection = %s") == 1
    assert DENSE_SQL.count("review_status = 'reviewed'") == 1
    assert DENSE_SQL.count("vector IS NOT NULL") == 1
    assert DENSE_SQL.count("btrim(source_label) <> ''") == 1
    assert "hnsw_candidates AS MATERIALIZED" in DENSE_SQL
    assert "ranked_pool AS MATERIALIZED" in DENSE_SQL
    assert "pool_diagnostics AS MATERIALIZED" in DENSE_SQL
    hnsw_phase, bounded_phase = DENSE_SQL.split("ranked_pool AS MATERIALIZED", 1)
    assert "ORDER BY distance ASC LIMIT %s" in hnsw_phase
    assert "ORDER BY distance ASC, chunk_id ASC" not in hnsw_phase
    assert "rag_chunks" not in bounded_phase
    assert "pool_rank = %s" in bounded_phase
    assert "boundary_distance" in bounded_phase
    assert "sentinel_distance" in bounded_phase
    assert "ranked_pool.pool_rank <= %s" in bounded_phase
    assert "ORDER BY ranked_pool.distance ASC, ranked_pool.chunk_id ASC" in bounded_phase
    assert "candidate_count" not in DENSE_SQL
    assert "max_distance" not in DENSE_SQL


@pytest.mark.parametrize("limit", [1, 17, CHANNEL_LIMIT])
def test_dense_keeps_a_fixed_ann_probe_for_every_valid_output_limit(limit: int) -> None:
    provider = ProviderSpy([_dense_row()])

    _dense(provider, limit=limit)

    assert provider.cursor.executions[2] == (DENSE_SQL, _dense_params(limit=limit))


def test_dense_fails_closed_when_the_ann_sentinel_overflows_an_equality() -> None:
    provider = ProviderSpy([_dense_row(tie_overflow=True)])

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed") as exc:
        _dense(provider)

    assert exc.value.__cause__ is None
    assert exc.value.__context__ is None


@pytest.mark.parametrize("tie_overflow", [None, 0, 1, "false"])
def test_dense_rejects_a_malformed_ann_tie_diagnostic(tie_overflow: object) -> None:
    provider = ProviderSpy([_dense_row(tie_overflow=tie_overflow)])

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
        _dense(provider)


def test_dense_set_local_failure_skips_select_and_releases_both_contexts() -> None:
    provider = ProviderSpy([_row()], fail_at="set")

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed") as exc_info:
        _dense(provider)

    assert provider.cursor.executions == [
        (PGVECTOR_ACTIVATION_SQL, (VECTOR_TEXT,)),
        (DENSE_STRICT_ORDER_SQL, None),
    ]
    assert any(event[0] == "cursor-exit" for event in provider.events)
    assert any(event[0] == "connection-exit" for event in provider.events)
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_lexical_uses_one_exact_parameterized_french_tsquery() -> None:
    provider = ProviderSpy([_row()])

    candidates = _lexical(provider)

    assert provider.cursor.executions == [
        (LEXICAL_SQL, ("question brute", *_scope_params(), CHANNEL_LIMIT))
    ]
    assert all("hnsw.iterative_scan" not in sql for sql, _ in provider.cursor.executions)
    assert LEXICAL_SQL.count("plainto_tsquery") == 1
    assert LEXICAL_SQL.count("MATERIALIZED") == 1
    assert candidates[0].dense_score is None
    assert candidates[0].lexical_score == 0.75


def test_dense_pgvector_activation_failure_skips_guc_and_select_and_cleans_up() -> None:
    provider = ProviderSpy([_row()], fail_at="activation")

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
        _dense(provider)

    assert provider.cursor.executions == [
        (PGVECTOR_ACTIVATION_SQL, (VECTOR_TEXT,)),
    ]
    assert any(event[0] == "cursor-exit" for event in provider.events)
    assert any(event[0] == "connection-exit" for event in provider.events)


@pytest.mark.parametrize("channel", ["dense", "lexical"])
def test_values_that_look_like_sql_remain_only_in_parameters(channel: str) -> None:
    malicious_query = "x'); DROP TABLE rag_chunks; --"
    malicious_collection = "tenant' OR TRUE --"
    provider = ProviderSpy([])

    if channel == "dense":
        with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
            _dense(provider, collection=malicious_collection)
        assert provider.calls == 0
        return
    else:
        _lexical(
            provider,
            raw_query=malicious_query,
        )
        sql, params = provider.cursor.executions[0]
        assert params == (malicious_query, *_scope_params(), CHANNEL_LIMIT)
    assert malicious_collection not in sql
    assert "DROP TABLE" not in sql


def test_lexical_empty_database_result_is_valid_and_has_no_fallback_query() -> None:
    provider = ProviderSpy([])

    assert _lexical(provider) == []
    assert provider.calls == 1
    assert len(provider.cursor.executions) == 1


@pytest.mark.parametrize("channel", ["dense", "lexical"])
def test_database_order_is_preserved_for_score_ties(channel: str) -> None:
    row_factory = _dense_row if channel == "dense" else _row
    provider = ProviderSpy(
        [
            row_factory(chunk_id="chunk-a", doc_id="doc-a", score=0.5),
            row_factory(chunk_id="chunk-b", doc_id="doc-b", score=0.5),
        ]
    )

    candidates = _dense(provider) if channel == "dense" else _lexical(provider)

    assert [candidate.chunk_id for candidate in candidates] == ["chunk-a", "chunk-b"]


def test_channel_candidates_are_compatible_with_fail_closed_rrf_scores() -> None:
    dense_provider = ProviderSpy([_dense_row(score=0.51)])
    lexical_provider = ProviderSpy([_row(score=0.37)])

    dense = _dense(dense_provider)
    lexical = _lexical(lexical_provider)
    ranked = reciprocal_rank_fusion(dense, lexical)

    assert len(ranked) == 1
    assert ranked[0].candidate.dense_score == 0.51
    assert ranked[0].candidate.lexical_score == 0.37
    assert ranked[0].dense_rank == 1
    assert ranked[0].lexical_rank == 1


@pytest.mark.parametrize("page_start", [None, 0, -1])
def test_nonpositive_or_missing_page_is_normalized_to_none(page_start: object) -> None:
    provider = ProviderSpy([_dense_row(page_start=page_start)])

    assert _dense(provider)[0].page_start is None


@pytest.mark.parametrize(
    ("row_index", "invalid_value"),
    [
        (0, ""),
        (1, " "),
        (2, ""),
        (3, "\t"),
        (4, ""),
        (5, None),
        (6, " "),
        (7, True),
        (7, "7"),
        (9, "draft"),
        (21, float("nan")),
        (21, float("inf")),
        (21, "0.5"),
    ],
)
def test_malformed_row_field_fails_closed(row_index: int, invalid_value: object) -> None:
    mutable_row = list(_dense_row())
    mutable_row[row_index] = invalid_value
    provider = ProviderSpy([tuple(mutable_row)])

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
        _dense(provider)


@pytest.mark.parametrize(
    ("row_index", "outside_value"),
    [
        (4, "usage_interne"),
        (10, "other_collection"),
        (11, "other_tenant"),
        (12, "premiere"),
        (13, "technologique"),
        (14, "nsi"),
        (15, "tronc_commun"),
        (16, "aefe"),
        (17, ["aefe"]),
        (18, "internal"),
        (19, "2027-2028"),
        (20, "other_programme"),
    ],
)
def test_every_post_database_scope_dimension_is_verified(
    row_index: int,
    outside_value: object,
) -> None:
    mutable_row = list(_dense_row())
    mutable_row[row_index] = outside_value

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
        _dense(ProviderSpy([tuple(mutable_row)]))


@pytest.mark.parametrize(
    "vector_text",
    [
        None,
        "",
        "1,0,0",
        "[1,0,0]",
        "[" + ",".join(["0"] * 1024) + "]",
        "[" + ",".join(["1", *(["0"] * 1022), "nan"]) + "]",
        "[" + ",".join(["1", *(["0"] * 1022), "inf"]) + "]",
        "[" + ",".join(["1", *(["0"] * 1022), "not-a-number"]) + "]",
    ],
)
def test_malformed_stored_vector_fails_closed(vector_text: object) -> None:
    provider = ProviderSpy([_dense_row(vector_text=vector_text)])

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
        _dense(provider)


@pytest.mark.parametrize(
    "rows",
    [
        [tuple(_row())[:-1]],
        [(*_row(), "extra")],
        [object()],
        None,
    ],
)
def test_malformed_row_cardinality_or_result_fails_closed(rows: object) -> None:
    provider = ProviderSpy(rows)

    with pytest.raises(RetrievalPipelineError, match="lexical channel query failed"):
        _lexical(provider)


def test_more_rows_than_requested_is_rejected_before_mapping() -> None:
    provider = ProviderSpy(
        [
            _dense_row(chunk_id=f"chunk-{index}", doc_id=f"doc-{index}")
            for index in range(51)
        ]
    )

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
        _dense(provider, limit=50)


@pytest.mark.parametrize(
    "query_vector",
    [
        (),
        (1.0,),
        (*([0.0] * 1024),),
        (float("nan"), *([0.0] * 1023)),
        (float("inf"), *([0.0] * 1023)),
        (True, *([0.0] * 1023)),
        ("1", *([0.0] * 1023)),
    ],
)
def test_dense_rejects_invalid_query_vectors_before_acquiring_connection(
    query_vector: object,
) -> None:
    provider = ProviderSpy([])

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
        _dense(provider, query_vector=query_vector)

    assert provider.calls == 0


@pytest.mark.parametrize("collection", ["", " ", "\t", None, 7])
def test_dense_rejects_invalid_collection_before_acquiring_connection(
    collection: object,
) -> None:
    provider = ProviderSpy([])

    with pytest.raises(RetrievalPipelineError, match="dense channel query failed"):
        _dense(provider, collection=collection)

    assert provider.calls == 0


@pytest.mark.parametrize("raw_query", ["", " ", "\t", None, 7])
def test_lexical_rejects_invalid_query_before_acquiring_connection(raw_query: object) -> None:
    provider = ProviderSpy([])

    with pytest.raises(RetrievalPipelineError, match="lexical channel query failed"):
        _lexical(provider, raw_query=raw_query)

    assert provider.calls == 0


@pytest.mark.parametrize("limit", [0, 51, -1, True, 1.5, "10", None])
@pytest.mark.parametrize("channel", ["dense", "lexical"])
def test_channels_reject_invalid_limits_before_acquiring_connection(
    channel: str,
    limit: object,
) -> None:
    provider = ProviderSpy([])

    with pytest.raises(RetrievalPipelineError):
        if channel == "dense":
            _dense(provider, limit=limit)
        else:
            _lexical(provider, limit=limit)

    assert provider.calls == 0


@pytest.mark.parametrize(
    "fail_at",
    ["provider", "connection-enter", "execute", "fetchall"],
)
@pytest.mark.parametrize("channel", ["dense", "lexical"])
def test_runtime_failures_are_sanitized_and_contexts_are_released(
    channel: str,
    fail_at: str,
) -> None:
    provider = ProviderSpy([_row()], fail_at=fail_at)

    with pytest.raises(RetrievalPipelineError) as exc_info:
        if channel == "dense":
            _dense(provider)
        else:
            _lexical(provider)

    serialized = f"{exc_info.value!s} {exc_info.value!r}"
    assert "postgresql" not in serialized
    assert "secret" not in serialized
    assert "question brute" not in serialized
    assert "libre_terminale" not in serialized
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert provider.calls == 1
    maximum_executions = 3 if channel == "dense" else 1
    assert len(provider.cursor.executions) <= maximum_executions
    if channel == "dense" and fail_at == "execute":
        assert provider.cursor.executions == [
            (PGVECTOR_ACTIVATION_SQL, (VECTOR_TEXT,)),
            (DENSE_STRICT_ORDER_SQL, None),
            (DENSE_SQL, _dense_params()),
        ]
    if fail_at in {"execute", "fetchall"}:
        assert any(event[0] == "cursor-exit" for event in provider.events)
        assert any(event[0] == "connection-exit" for event in provider.events)


def test_type_doc_may_be_blank_without_weakening_provenance_gate() -> None:
    provider = ProviderSpy([_row(type_doc="")])

    candidate = _lexical(provider)[0]

    assert candidate.type_doc == ""
    assert candidate.source_label
    assert candidate.source_uri
    assert candidate.rights


def test_dense_score_is_the_finite_value_returned_by_one_minus_cosine_distance() -> None:
    score = 1.0 - math.nextafter(0.25, math.inf)
    provider = ProviderSpy([_dense_row(score=score)])

    candidate = _dense(provider)[0]

    assert candidate.dense_score == score
    assert candidate.lexical_score is None
