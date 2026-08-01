"""Preuves LOT40 sur une base PostgreSQL/pgvector ephemere reelle."""

from __future__ import annotations

import hashlib
import math
import os
import re
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ingestor import retrieval_v2_endpoint as endpoint
from ingestor.pg_pool import close_pool
from ingestor.retrieval_hybrid_v2 import (
    EMBED_DIMENSION,
    RetrievalPipelineError,
    retrieve_hybrid,
)
from ingestor.retrieval_pg_v2 import _DENSE_SQL, _LEXICAL_SQL, PgCandidateStore

pytestmark = pytest.mark.integration

APP_DSN = os.environ.get("LOT40_PG_DSN", "").strip()
ADMIN_DSN = os.environ.get("LOT40_PG_ADMIN_DSN", "").strip()
if not APP_DSN or not ADMIN_DSN:
    pytest.skip(
        "LOT40_PG_DSN et LOT40_PG_ADMIN_DSN requis par le runner ephemere LOT40",
        allow_module_level=True,
    )

SERVICE_ROOT = Path(__file__).resolve().parents[2]
TARGET_COLLECTION = "lot40_target"
TIE_COLLECTION = "lot40_ties"
SMALL_COLLECTION = "lot40_small"
TARGET_SCALE = 6000
QUERY = "algorithme graphe"
QUERY_VECTOR = (1.0,) + (0.0,) * (EMBED_DIMENSION - 1)
QUERY_VECTOR_TEXT = "[" + ",".join(str(value) for value in QUERY_VECTOR) + "]"

_DENSE_ORACLE_SQL = """
    SELECT chunk_id
    FROM rag_chunks
    WHERE collection = %s AND review_status = 'reviewed'
      AND text IS NOT NULL AND btrim(text) <> '' AND vector IS NOT NULL
      AND btrim(source_label) <> '' AND btrim(source_uri) <> ''
      AND btrim(rights) <> ''
    ORDER BY vector <=> %s::vector ASC, chunk_id ASC
    LIMIT 50
"""

def _vector(first: float, second: float = 0.0) -> str:
    values = (first, second) + (0.0,) * (EMBED_DIMENSION - 2)
    return "[" + ",".join(f"{value:.12g}" for value in values) + "]"


def _unit_vector(angle: float) -> str:
    return _vector(math.cos(angle), math.sin(angle))


def _row(
    chunk_id: str,
    *,
    collection: str,
    vector: str,
    text: str,
    review_status: str = "reviewed",
    doc_id: str | None = None,
    source_label: str = "Preuve LOT40",
    source_uri: str = "https://example.invalid/lot40",
    rights: str = "usage_interne",
    page_start: int | None = 1,
) -> tuple[object, ...]:
    return (
        chunk_id,
        doc_id or f"doc-{chunk_id}",
        hashlib.sha256(chunk_id.encode()).hexdigest(),
        vector,
        collection,
        "terminale",
        "nsi",
        source_label,
        source_uri,
        rights,
        "cours",
        text,
        0,
        page_start,
        page_start,
        review_status,
    )


def _seed_rows() -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = []
    for index in range(80):
        rows.append(
            _row(
                f"target-{index:03d}",
                collection=TARGET_COLLECTION,
                vector=_unit_vector(0.002 + index * 0.002),
                text=f"algorithme graphe preuve pedagogique ordinal {index:03d}",
                doc_id="doc-shared" if index in {0, 1} else None,
                page_start=0 if index == 0 else index + 1,
            )
        )
    rows.extend(
        [
            _row(
                "target-dense-only",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="contenu vectoriel distinct sans terme de recherche",
                page_start=0,
            ),
            _row(
                "target-lexical-only",
                collection=TARGET_COLLECTION,
                vector=_vector(-1.0),
                text="algorithme graphe algorithme graphe algorithme graphe",
                page_start=7,
            ),
        ]
    )

    for index in range(120):
        rows.append(
            _row(
                f"outside-{index:03d}",
                collection="lot40_outside",
                vector=_unit_vector(index * 0.000001),
                text="algorithme graphe hors collection",
            )
        )
    for index in range(80):
        rows.append(
            _row(
                f"pending-{index:03d}",
                collection=TARGET_COLLECTION,
                vector=_unit_vector(index * 0.000001),
                text="algorithme graphe non revu",
                review_status="needs_review",
            )
        )
    rows.extend(
        [
            _row(
                "incomplete-label",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe",
                source_label=" ",
            ),
            _row(
                "incomplete-uri",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe",
                source_uri=" ",
            ),
            _row(
                "incomplete-rights",
                collection=TARGET_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe",
                rights=" ",
            ),
        ]
    )
    for index in range(52):
        rows.append(
            _row(
                f"tie-{index:03d}",
                collection=TIE_COLLECTION,
                vector=_vector(1.0),
                text="algorithme graphe egalite complete",
            )
        )
    for index in range(3):
        rows.append(
            _row(
                f"small-{index:03d}",
                collection=SMALL_COLLECTION,
                vector=_unit_vector(index * 0.01),
                text="algorithme graphe petit corpus",
            )
        )
    return rows


@pytest.fixture(scope="module", autouse=True)
def seeded_database() -> Iterator[None]:
    rows = _seed_rows()
    with psycopg.connect(ADMIN_DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("TRUNCATE TABLE rag_chunks")
            cursor.executemany(
                """
                INSERT INTO rag_chunks (
                    chunk_id, doc_id, chunk_sha256, vector, collection, niveau,
                    matiere, source_label, source_uri, rights, type_doc, text,
                    chunk_index, page_start, page_end, review_status
                ) VALUES (
                    %s, %s, %s, %s::vector, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s
                )
                """,
                rows,
            )
            cursor.execute(
                """
                INSERT INTO rag_chunks (
                    chunk_id, doc_id, chunk_sha256, vector, collection, niveau,
                    matiere, source_label, source_uri, rights, type_doc, text,
                    chunk_index, page_start, page_end, review_status
                )
                SELECT
                    prefix || '-' || lpad(series::text, 6, '0'),
                    'doc-' || prefix || '-' || series,
                    md5(prefix || series::text) || md5('b' || prefix || series::text),
                    ((ARRAY[cos(base_angle + series * angle_step),
                            sin(base_angle + series * angle_step)]::real[]
                      || array_fill(0::real, ARRAY[1022])))::vector,
                    collection, 'terminale', 'nsi', 'Preuve LOT40',
                    'https://example.invalid/lot40', 'usage_interne', 'cours',
                    'algorithme graphe preuve pedagogique de charge',
                    0, 1, 1, review_status
                FROM (
                    VALUES
                      ('target-bulk', 'lot40_target', 'reviewed', 0.4::float8,
                       0.00001::float8, 80, %s - 1),
                      ('outside-bulk', 'lot40_outside', 'reviewed', 0.0::float8,
                       0.000001::float8, 120, (%s * 15 / 100) - 1),
                      ('pending-bulk', 'lot40_target', 'needs_review', 0.0::float8,
                       0.000001::float8, 80, (%s * 10 / 100) - 1)
                ) AS fixture(
                    prefix, collection, review_status, base_angle, angle_step,
                    first_series, last_series
                )
                CROSS JOIN LATERAL generate_series(first_series, last_series) AS generated(series)
                """,
                (TARGET_SCALE, TARGET_SCALE, TARGET_SCALE),
            )
            cursor.execute("ANALYZE rag_chunks")
    yield
    with psycopg.connect(ADMIN_DSN) as connection:
        connection.execute("TRUNCATE TABLE rag_chunks")


@contextmanager
def _store_connection(
    *,
    force_exact: bool = False,
    ef_search: int = 40,
    max_scan_tuples: int = 100000,
) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(APP_DSN) as connection:
        with connection.cursor() as cursor:
            cursor.execute("SELECT %s::vector IS NOT NULL", (QUERY_VECTOR_TEXT,))
            cursor.execute("SELECT set_config('hnsw.ef_search', %s, true)", (str(ef_search),))
            cursor.execute(
                "SELECT set_config('hnsw.max_scan_tuples', %s, true)",
                (str(max_scan_tuples),),
            )
            if force_exact:
                cursor.execute("SET LOCAL enable_indexscan = off")
                cursor.execute("SET LOCAL enable_bitmapscan = off")
        yield connection


def _plan_lines(
    connection: psycopg.Connection[Any],
    sql: str,
    params: Sequence[object],
) -> str:
    with connection.cursor() as cursor:
        cursor.execute("EXPLAIN (ANALYZE, COSTS OFF, SUMMARY OFF) " + sql, params)
        return "\n".join(str(row[0]) for row in cursor.fetchall())


def _assert_gin_plan(connection: psycopg.Connection[Any]) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SET LOCAL enable_seqscan = off")
    plan = _plan_lines(
        connection,
        _LEXICAL_SQL,
        (QUERY, TARGET_COLLECTION, 50),
    )
    if "idx_rag_chunks_text_tsv" not in plan:
        raise AssertionError(plan)


def _assert_ids(actual: Sequence[str], expected: Sequence[str]) -> None:
    if list(actual) != list(expected):
        raise AssertionError(f"ordre inattendu: {list(actual)!r}")


def _dense_params(collection: str) -> tuple[object, ...]:
    return (
        QUERY_VECTOR_TEXT,
        collection,
        QUERY_VECTOR_TEXT,
        50,
        QUERY_VECTOR_TEXT,
        collection,
        50,
        QUERY_VECTOR_TEXT,
        QUERY_VECTOR_TEXT,
        50,
    )


def test_application_role_is_non_superuser_and_select_only() -> None:
    with psycopg.connect(APP_DSN, autocommit=True) as connection:
        role = connection.execute(
            """
            SELECT current_user, rolsuper, rolcreatedb, rolcreaterole,
                   rolreplication, rolbypassrls
            FROM pg_roles
            WHERE rolname = current_user
            """
        ).fetchone()
        assert role == ("lot40_app", False, False, False, False, False)
        privileges = connection.execute(
            """
            SELECT
              has_database_privilege(current_user, current_database(), 'CONNECT'),
              has_database_privilege(current_user, current_database(), 'CREATE'),
              has_database_privilege(current_user, current_database(), 'TEMP'),
              has_schema_privilege(current_user, 'public', 'USAGE'),
              has_schema_privilege(current_user, 'public', 'CREATE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'SELECT'),
              has_table_privilege(current_user, 'public.rag_chunks', 'INSERT'),
              has_table_privilege(current_user, 'public.rag_chunks', 'UPDATE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'DELETE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'TRUNCATE'),
              has_table_privilege(current_user, 'public.rag_chunks', 'REFERENCES'),
              has_table_privilege(current_user, 'public.rag_chunks', 'TRIGGER'),
              pg_has_role(current_user, tableowner, 'USAGE')
            FROM pg_tables
            WHERE schemaname = 'public' AND tablename = 'rag_chunks'
            """
        ).fetchone()
        assert privileges == (
            True,
            False,
            False,
            True,
            False,
            True,
            False,
            False,
            False,
            False,
            False,
            False,
            False,
        )
    print("APP_ROLE_NON_SUPERUSER_SELECT_ONLY=PASS")


def test_schema_registry_and_real_migration_objects_are_exact() -> None:
    expected = {
        1: (
            "001_rag_chunks_v2_schema.sql",
            hashlib.sha256(
                (SERVICE_ROOT / "infra/postgres/migrations/001_rag_chunks_v2_schema.sql")
                .read_bytes()
            ).hexdigest(),
        ),
        2: (
            "002_hybrid_retrieval.sql",
            hashlib.sha256(
                (SERVICE_ROOT / "infra/postgres/migrations/002_hybrid_retrieval.sql")
                .read_bytes()
            ).hexdigest(),
        ),
    }
    with psycopg.connect(ADMIN_DSN) as connection:
        rows = connection.execute(
            "SELECT version, file_name, sha256 FROM rag_schema_migrations ORDER BY version"
        ).fetchall()
        assert rows == [(version, *expected[version]) for version in (1, 2)]
        objects = connection.execute(
            """
            SELECT
              to_regclass('public.idx_rag_chunks_vector')::text,
              to_regclass('public.idx_rag_chunks_text_tsv')::text,
              (SELECT is_generated FROM information_schema.columns
               WHERE table_schema='public' AND table_name='rag_chunks'
                 AND column_name='text_tsv')
            """
        ).fetchone()
        assert objects == (
            "idx_rag_chunks_vector",
            "idx_rag_chunks_text_tsv",
            "ALWAYS",
        )
    print("MIGRATION_OBJECTS_REAL_DB=PASS")


def test_equal_score_rank_50_is_deterministic_in_both_channels() -> None:
    store = PgCandidateStore(_store_connection)
    dense = store.dense(
        query_vector=QUERY_VECTOR,
        collection=TIE_COLLECTION,
        limit=50,
    )
    lexical = store.lexical(raw_query=QUERY, collection=TIE_COLLECTION, limit=50)
    expected = [f"tie-{index:03d}" for index in range(50)]
    _assert_ids([item.chunk_id for item in dense], expected)
    _assert_ids([item.chunk_id for item in lexical], expected)
    with pytest.raises(AssertionError):
        _assert_ids([item.chunk_id for item in dense], list(reversed(expected)))
    assert dense[-1].chunk_id == "tie-049"
    assert lexical[-1].chunk_id == "tie-049"
    print("RANK_50_DETERMINISTIC=PASS")


def test_real_gin_and_hnsw_plans_filters_top_50_and_local_scope() -> None:
    with psycopg.connect(APP_DSN, autocommit=True) as connection:
        assert connection.execute(
            "SELECT current_setting('hnsw.iterative_scan', true)"
        ).fetchone()[0] is None
        assert connection.execute(
            "SELECT %s::vector IS NOT NULL", (QUERY_VECTOR_TEXT,)
        ).fetchone()[0]
        initial_scan_mode = connection.execute("SHOW hnsw.iterative_scan").fetchone()[0]
        with connection.transaction():
            connection.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            assert connection.execute("SHOW hnsw.iterative_scan").fetchone()[0] == (
                "strict_order"
            )
        assert connection.execute("SHOW hnsw.iterative_scan").fetchone()[0] == (
            initial_scan_mode
        )

        with connection.transaction():
            connection.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            connection.execute("SET LOCAL hnsw.ef_search = 40")
            connection.execute("SET LOCAL hnsw.max_scan_tuples = 100000")
            hnsw_plan = _plan_lines(
                connection,
                _DENSE_SQL,
                _dense_params(TARGET_COLLECTION),
            )
            assert "idx_rag_chunks_vector" in hnsw_plan, hnsw_plan

        with connection.transaction():
            connection.execute("SET LOCAL enable_seqscan = off")
            connection.execute("SET LOCAL enable_bitmapscan = off")
            connection.execute("SET LOCAL enable_sort = off")
            connection.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            connection.execute("SET LOCAL hnsw.ef_search = 40")
            connection.execute("SET LOCAL hnsw.max_scan_tuples = 100000")
            structural_plan = _plan_lines(
                connection,
                _DENSE_SQL,
                _dense_params(TARGET_COLLECTION),
            )
            assert "idx_rag_chunks_vector" in structural_plan, structural_plan

        with connection.transaction():
            _assert_gin_plan(connection)

    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin_connection:
        admin_connection.execute("DROP INDEX idx_rag_chunks_text_tsv")
    try:
        with psycopg.connect(APP_DSN) as app_connection:
            with pytest.raises(AssertionError):
                _assert_gin_plan(app_connection)
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as admin_connection:
            admin_connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_rag_chunks_text_tsv
                    ON rag_chunks USING gin (text_tsv)
                """
            )
    with psycopg.connect(APP_DSN) as app_connection:
        _assert_gin_plan(app_connection)

    store = PgCandidateStore(_store_connection)
    actual = store.dense(
        query_vector=QUERY_VECTOR,
        collection=TARGET_COLLECTION,
        limit=50,
    )
    with psycopg.connect(APP_DSN) as connection:
        connection.execute("SET LOCAL enable_indexscan = off")
        connection.execute("SET LOCAL enable_bitmapscan = off")
        expected_rows = connection.execute(
            _DENSE_ORACLE_SQL,
            (TARGET_COLLECTION, QUERY_VECTOR_TEXT),
        ).fetchall()
    expected_ids = [str(row[0]) for row in expected_rows]
    _assert_ids([item.chunk_id for item in actual], expected_ids)
    assert len(actual) == 50
    assert actual[-1].chunk_id == "target-048"
    assert all(item.review_status == "reviewed" for item in actual)
    assert not any(
        item.chunk_id.startswith(("outside-", "pending-", "incomplete-"))
        for item in actual
    )

    assert PgCandidateStore(_store_connection).dense(
        query_vector=QUERY_VECTOR,
        collection="lot40_empty",
        limit=50,
    ) == []
    small = PgCandidateStore(_store_connection).dense(
        query_vector=QUERY_VECTOR,
        collection=SMALL_COLLECTION,
        limit=50,
    )
    _assert_ids([item.chunk_id for item in small], [f"small-{index:03d}" for index in range(3)])

    with psycopg.connect(APP_DSN, autocommit=True) as connection:
        assert connection.execute(
            "SELECT %s::vector IS NOT NULL", (QUERY_VECTOR_TEXT,)
        ).fetchone()[0]
        with connection.transaction():
            connection.execute("SET LOCAL enable_seqscan = off")
            connection.execute("SET LOCAL enable_bitmapscan = off")
            connection.execute("SET LOCAL hnsw.iterative_scan = 'strict_order'")
            connection.execute("SET LOCAL hnsw.ef_search = 1")
            connection.execute("SET LOCAL hnsw.max_scan_tuples = 1")
            underfill_plan = _plan_lines(
                connection,
                _DENSE_SQL,
                _dense_params(TARGET_COLLECTION),
            )
    underfill_match = re.search(
        r"CTE hnsw_candidates\s+->\s+Limit .*?rows=(\d+)",
        underfill_plan,
        re.DOTALL,
    )
    assert underfill_match is not None, underfill_plan
    assert int(underfill_match.group(1)) < 50, underfill_plan
    underfill_store = PgCandidateStore(
        lambda: _store_connection(ef_search=1, max_scan_tuples=1)
    )
    underfill_actual = underfill_store.dense(
        query_vector=QUERY_VECTOR,
        collection=TARGET_COLLECTION,
        limit=50,
    )
    _assert_ids([item.chunk_id for item in underfill_actual], expected_ids)
    print("GIN_PLAN=PASS")
    print("HNSW_STRICT_FILTERED_TOP50=PASS")
    print("HNSW_NATURAL_AND_STRUCTURAL_PLAN=PASS")
    print("HNSW_UNDERFILL_EXACT_FALLBACK=PASS")


class DeterministicEmbedder:
    def encode(self, text: str, *, normalize_embeddings: bool) -> Sequence[float]:
        assert text == f"query: {QUERY}"
        assert normalize_embeddings is True
        return QUERY_VECTOR


class DeterministicReranker:
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        scores: list[float] = []
        for query, text in pairs:
            assert query == QUERY
            if "distinct sans terme" in text:
                scores.append(2.60)
            elif text.count("algorithme graphe") == 3:
                scores.append(2.55)
            else:
                ordinal = int(text.rsplit(" ", 1)[1])
                scores.append(2.50 - ordinal / 1000)
        return scores


class EmptyReranker:
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        return [0.0] * len(pairs)


def test_real_store_and_core_prove_union_scores_page_dedup_and_dimension_failure() -> None:
    store = PgCandidateStore(_store_connection)
    hits = retrieve_hybrid(
        QUERY,
        TARGET_COLLECTION,
        5,
        store=store,
        embedder=DeterministicEmbedder(),
        reranker=DeterministicReranker(),
    )
    assert [hit.candidate.chunk_id for hit in hits[:2]] == [
        "target-dense-only",
        "target-lexical-only",
    ]
    assert hits[0].dense_rank == 1
    assert hits[0].lexical_rank is None
    assert hits[1].dense_rank is None
    assert hits[1].lexical_rank == 1
    assert hits[0].candidate.page_start is None
    assert hits[1].candidate.page_start == 7
    assert hits[0].rrf_score == pytest.approx(0.7 / 61)
    assert hits[0].rerank_score == 2.60
    expected_first_mmr = 0.7 / (1.0 + math.exp(-2.60))
    assert hits[0].mmr_score == pytest.approx(expected_first_mmr)
    assert hits[0].score_final == pytest.approx((expected_first_mmr + 0.3) / 1.3)
    assert len({hit.candidate.doc_id for hit in hits}) == len(hits)
    assert all(hit.candidate.review_status == "reviewed" for hit in hits)
    assert not any(hit.candidate.chunk_id.startswith("incomplete-") for hit in hits)

    sql_calls = 0

    @contextmanager
    def counted_connection() -> Iterator[psycopg.Connection[Any]]:
        nonlocal sql_calls
        sql_calls += 1
        with psycopg.connect(APP_DSN) as connection:
            yield connection

    class WrongDimensionEmbedder:
        def encode(self, text: str, *, normalize_embeddings: bool) -> Sequence[float]:
            return (1.0, 0.0)

    with pytest.raises(RetrievalPipelineError):
        retrieve_hybrid(
            QUERY,
            TARGET_COLLECTION,
            5,
            store=PgCandidateStore(counted_connection),
            embedder=WrongDimensionEmbedder(),
            reranker=DeterministicReranker(),
        )
    assert sql_calls == 0
    print("HYBRID_REAL_DB=PASS")


def _test_app(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(endpoint, "_enforce_security_v2", lambda *args, **kwargs: None)
    monkeypatch.setattr(endpoint, "load_collection_config", lambda: {})
    monkeypatch.setattr(endpoint, "_check_retrievable", lambda *args, **kwargs: {})
    app = FastAPI()
    app.include_router(endpoint.router)
    return TestClient(app)


def test_http_search_fails_closed_then_uses_real_hybrid_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", APP_DSN)
    monkeypatch.setenv("PG_POOL_MIN_SIZE", "1")
    monkeypatch.setenv("PG_POOL_MAX_SIZE", "2")
    monkeypatch.setenv("PG_POOL_TIMEOUT_S", "5")
    monkeypatch.setattr(endpoint, "_get_embed_model", lambda: DeterministicEmbedder())
    monkeypatch.setattr(endpoint, "_get_reranker", lambda: DeterministicReranker())
    close_pool()
    client = _test_app(monkeypatch)
    real_retrieve = endpoint._retrieve_hybrid_hits

    def fail_with_private_context(*args: object, **kwargs: object) -> list[object]:
        raise RetrievalPipelineError(f"private database context: {APP_DSN}")

    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", fail_with_private_context)
    failed = client.post(
        "/search/v2",
        json={"q": QUERY, "collection": TARGET_COLLECTION, "k": 5},
    )
    assert failed.status_code == 503
    assert failed.json() == {"detail": "retrieval unavailable"}
    assert APP_DSN not in failed.text

    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", real_retrieve)
    response = client.post(
        "/search/v2",
        json={"q": QUERY, "collection": TARGET_COLLECTION, "k": 5},
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["returned"] == 5
    assert [hit["chunk_id"] for hit in payload["hits"][:2]] == [
        "target-dense-only",
        "target-lexical-only",
    ]
    assert payload["hits"][0]["page"] is None
    assert payload["hits"][1]["page"] == 7
    assert all(hit["review_status"] == "reviewed" for hit in payload["hits"])
    assert all(hit["source_label"] and hit["source_uri"] and hit["rights"] for hit in payload["hits"])
    assert all(
        key in payload["hits"][0]
        for key in (
            "dense_score",
            "lexical_score",
            "rrf_score",
            "rerank_score",
            "mmr_score",
            "score_final",
        )
    )
    client.close()
    close_pool()
    print("HTTP_SEARCH_V2=PASS")


def test_http_chat_is_locked_with_zero_or_real_hits_and_never_calls_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_RAG_DSN", APP_DSN)
    monkeypatch.setenv("OPENROUTER_API_KEY", "lot40-fake-key-never-used")
    active_reranker: dict[str, object] = {"value": EmptyReranker()}
    monkeypatch.setattr(endpoint, "_get_embed_model", lambda: DeterministicEmbedder())
    monkeypatch.setattr(endpoint, "_get_reranker", lambda: active_reranker["value"])
    network_calls = 0

    def network_must_not_run(*args: object, **kwargs: object) -> None:
        nonlocal network_calls
        network_calls += 1
        raise AssertionError("network generation forbidden in LOT40")

    monkeypatch.setattr(endpoint, "_openrouter_answer", network_must_not_run, raising=False)
    close_pool()
    client = _test_app(monkeypatch)
    profile = {
        "niveau": "terminale",
        "voie": "generale",
        "matieres": ["nsi"],
        "statut_enseignement": "specialite",
        "candidat": "scolarise",
        "school_year": "2026-2027",
        "zone": "tunis",
    }
    base_request = {
        "student_profile": profile,
        "query": QUERY,
        "collections": [TARGET_COLLECTION],
        "top_k": 3,
        "include_retrieval": True,
    }

    empty = client.post("/chat", json=base_request)
    assert empty.status_code == 200, empty.text
    assert empty.json()["refusal_reason"] == "answer_generation_locked"
    assert empty.json()["grounded"] is False
    assert empty.json()["citations"] == []
    assert empty.json()["retrieval_hits"] == []

    active_reranker["value"] = DeterministicReranker()
    populated = client.post("/chat", json=base_request)
    assert populated.status_code == 200, populated.text
    assert populated.json()["refusal_reason"] == "answer_generation_locked"
    assert populated.json()["grounded"] is False
    assert populated.json()["citations"] == []
    assert len(populated.json()["retrieval_hits"]) == 3
    assert populated.json()["retrieval_hits"][0]["chunk_id"] == "target-dense-only"

    hidden_request = dict(base_request, include_retrieval=False)
    hidden = client.post("/chat", json=hidden_request)
    assert hidden.status_code == 200
    assert hidden.json()["refusal_reason"] == "answer_generation_locked"
    assert hidden.json()["retrieval_hits"] == []
    assert hidden.json()["citations"] == []
    assert network_calls == 0
    client.close()
    close_pool()
    print("HTTP_CHAT_LOCKED=PASS")
