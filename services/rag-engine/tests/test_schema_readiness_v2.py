"""Sonde read-only du head PostgreSQL LOT41U."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from src.ingestor import schema_readiness_v2 as readiness

ENGINE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ENGINE_ROOT / "infra" / "postgres" / "migrations"


class _Cursor:
    def __init__(self, row: tuple[object, ...]) -> None:
        self.row = row
        self.sql = ""
        self.params: tuple[object, ...] = ()

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.sql = sql
        self.params = params

    def fetchone(self) -> tuple[object, ...]:
        return self.row


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _Cursor:
        return self._cursor


def _valid_row() -> tuple[object, ...]:
    return (
        readiness.REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS,
        readiness.REQUIRED_RAG_CHUNKS_CONSTRAINT_DEFINITIONS,
        readiness.REQUIRED_RAG_CHUNKS_INDEX_DEFINITIONS,
        readiness.REQUIRED_PROFILE_INDEX_PREDICATE,
        readiness.REQUIRED_TEXT_TSV_EXPRESSION,
        [list(item) for item in readiness.expected_migration_records(MIGRATIONS)],
        readiness.REQUIRED_RAG_CHUNKS_TABLE_STATE,
        readiness.REQUIRED_RAG_CHUNKS_TRIGGER_DEFINITIONS,
        readiness.REQUIRED_RAG_CHUNKS_RULE_DEFINITIONS,
        readiness.REQUIRED_RAG_CHUNKS_INHERITANCE_DEFINITIONS,
    )


@contextmanager
def _patched_connection(
    monkeypatch: pytest.MonkeyPatch,
    row: tuple[object, ...],
) -> Iterator[_Cursor]:
    cursor = _Cursor(row)
    captured: dict[str, Any] = {}

    def connect(dsn: str, **kwargs: object) -> _Connection:
        captured["dsn"] = dsn
        captured["kwargs"] = kwargs
        return _Connection(cursor)

    monkeypatch.setattr(readiness.psycopg, "connect", connect)
    yield cursor
    assert captured == {
        "dsn": "postgresql://reader",
        "kwargs": {
            "connect_timeout": readiness.READINESS_CONNECT_TIMEOUT_S,
            "options": (
                "-c statement_timeout="
                f"{readiness.READINESS_STATEMENT_TIMEOUT_MS} "
                "-c default_transaction_read_only=on"
            ),
        },
    }


def test_schema_head_003_accepts_only_the_exact_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _patched_connection(monkeypatch, _valid_row()) as cursor:
        assert readiness.schema_head_003_ready("postgresql://reader") is True

    normalized = cursor.sql.upper()
    assert normalized.lstrip().startswith("SELECT")
    assert "CONVALIDATED" in normalized
    assert "CONTYPE" in normalized
    assert "PG_GET_CONSTRAINTDEF" in normalized
    assert "PG_GET_INDEXDEF" in normalized
    assert "PG_ATTRDEF" in normalized
    assert "COLUMN_DEFAULT" in normalized
    assert "FORMAT_TYPE" in normalized
    assert "ATTTYPMOD" in normalized
    assert "INDEX_DEFINITION.INDRELID = 'PUBLIC.RAG_CHUNKS'::REGCLASS" in normalized
    assert "INDEX_DEFINITION.INDISVALID" in normalized
    assert "INDEX_DEFINITION.INDISREADY" in normalized
    assert "RAG_SCHEMA_MIGRATIONS" in normalized
    assert "RELROWSECURITY" in normalized
    assert "RELFORCEROWSECURITY" in normalized
    assert "RELPERSISTENCE" in normalized
    assert "PG_POLICY" in normalized
    assert "PG_TRIGGER" in normalized
    assert "TGISINTERNAL" in normalized
    assert "PG_REWRITE" in normalized
    assert "PG_GET_RULEDEF" in normalized
    assert "PG_INHERITS" in normalized
    assert "INHERITANCE_DEFINITION.INHPARENT" in normalized
    assert "INHERITANCE_DEFINITION.INHRELID" in normalized
    assert "INDEX_RELATION.RELNAME IN" not in normalized
    assert "CONSTRAINT_DEFINITION.CONTYPE = 'C'" not in normalized
    assert readiness.REQUIRED_RAG_CHUNKS_CONSTRAINT_DEFINITIONS[
        "rag_chunks_pkey"
    ][0] == "p"
    assert readiness.REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS["vector"][-2:] == [
        "vector(1024)",
        1024,
    ]
    assert readiness.REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS["audience"][4] == (
        "'{tous}'::text[]"
    )
    assert cursor.params == ()
    for forbidden in ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP"):
        assert re.search(rf"\b{forbidden}\b", normalized) is None


def test_schema_contract_is_loaded_from_the_shared_versioned_source() -> None:
    contract = ENGINE_ROOT / "infra" / "postgres" / "schema_head_003_columns.tsv"

    assert readiness.load_rag_chunks_column_definitions(contract) == (
        readiness.REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS
    )
    assert len(readiness.REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS) == 31


@pytest.mark.parametrize(
    "position",
    range(10),
    ids=(
        "columns",
        "constraints",
        "indexes",
        "predicate",
        "text-tsv-expression",
        "migrations",
        "table-state",
        "triggers",
        "rewrite-rules",
        "inheritance-hierarchy",
    ),
)
def test_schema_head_003_rejects_every_drifted_contract_component(
    monkeypatch: pytest.MonkeyPatch,
    position: int,
) -> None:
    row = list(_valid_row())
    row[position] = {} if position < 3 else "drifted"
    with _patched_connection(monkeypatch, tuple(row)):
        assert readiness.schema_head_003_ready("postgresql://reader") is False


def test_schema_head_003_rejects_registry_hash_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = list(_valid_row())
    migrations = [list(item) for item in row[5]]
    migrations[2][2] = "0" * 64
    row[5] = migrations
    with _patched_connection(monkeypatch, tuple(row)):
        assert readiness.schema_head_003_ready("postgresql://reader") is False


def test_schema_head_003_rejects_unexpected_ready_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = list(_valid_row())
    row[2] = {
        **readiness.REQUIRED_RAG_CHUNKS_INDEX_DEFINITIONS,
        "idx_rag_chunks_unexpected": "0" * 32,
    }
    with _patched_connection(monkeypatch, tuple(row)):
        assert readiness.schema_head_003_ready("postgresql://reader") is False


def test_schema_head_003_rejects_an_unexpected_foreign_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = list(_valid_row())
    row[1] = {
        **readiness.REQUIRED_RAG_CHUNKS_CONSTRAINT_DEFINITIONS,
        "lot41u_unexpected_fk": ["f", False, "0" * 32],
    }
    with _patched_connection(monkeypatch, tuple(row)):
        assert readiness.schema_head_003_ready("postgresql://reader") is False


def test_expected_migration_records_hash_the_canonical_files() -> None:
    assert readiness.expected_migration_records(MIGRATIONS) == (
        (
            1,
            "001_rag_chunks_v2_schema.sql",
            "c0ce69353bd04c87a9bf7adf885ebf9e915885b8e0b286faffc620b74cebc88c",
        ),
        (
            2,
            "002_hybrid_retrieval.sql",
            "6fef12777291653611aa8b561709e2090b169b40629ce99acf0767ebb388f89d",
        ),
        (
            3,
            "003_profile_filtering.sql",
            "069cd391d77ee47a6daae037221dbef7403e7710d35abecaecb0484f05d0428a",
        ),
    )


def test_schema_head_003_does_not_hide_database_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_dsn: str, **_kwargs: object) -> None:
        raise readiness.psycopg.OperationalError("database unavailable")

    monkeypatch.setattr(readiness.psycopg, "connect", fail)

    with pytest.raises(readiness.psycopg.OperationalError):
        readiness.schema_head_003_ready("postgresql://reader")
