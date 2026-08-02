"""Sonde read-only du head PostgreSQL LOT41U."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from src.ingestor import schema_readiness_v2 as readiness


class _Cursor:
    def __init__(self, row: tuple[list[str], list[str], bool]) -> None:
        self.row = row
        self.sql = ""

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[list[str], list[str], bool]:
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


def _valid_row() -> tuple[list[str], list[str], bool]:
    return (
        sorted(readiness.REQUIRED_PROFILE_COLUMNS),
        sorted(readiness.REQUIRED_PROFILE_CONSTRAINTS),
        True,
    )


@contextmanager
def _patched_connection(
    monkeypatch: pytest.MonkeyPatch,
    row: tuple[list[str], list[str], bool],
) -> Iterator[_Cursor]:
    cursor = _Cursor(row)
    captured: dict[str, Any] = {}

    def connect(dsn: str, **kwargs: object) -> _Connection:
        captured["dsn"] = dsn
        captured["kwargs"] = kwargs
        return _Connection(cursor)

    monkeypatch.setattr(readiness.psycopg, "connect", connect)
    yield cursor
    assert captured == {"dsn": "postgresql://reader", "kwargs": {}}


def test_schema_head_003_accepts_only_the_exact_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _patched_connection(monkeypatch, _valid_row()) as cursor:
        assert readiness.schema_head_003_ready("postgresql://reader") is True

    normalized = cursor.sql.upper()
    assert normalized.lstrip().startswith("SELECT")
    for forbidden in ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP"):
        assert forbidden not in normalized


@pytest.mark.parametrize("missing", sorted(readiness.REQUIRED_PROFILE_COLUMNS))
def test_schema_head_003_rejects_each_missing_column(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    columns, constraints, index_present = _valid_row()
    columns.remove(missing)
    with _patched_connection(monkeypatch, (columns, constraints, index_present)):
        assert readiness.schema_head_003_ready("postgresql://reader") is False


@pytest.mark.parametrize("missing", sorted(readiness.REQUIRED_PROFILE_CONSTRAINTS))
def test_schema_head_003_rejects_each_missing_constraint(
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    columns, constraints, index_present = _valid_row()
    constraints.remove(missing)
    with _patched_connection(monkeypatch, (columns, constraints, index_present)):
        assert readiness.schema_head_003_ready("postgresql://reader") is False


def test_schema_head_003_rejects_missing_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    columns, constraints, _index_present = _valid_row()
    with _patched_connection(monkeypatch, (columns, constraints, False)):
        assert readiness.schema_head_003_ready("postgresql://reader") is False


def test_schema_head_003_does_not_hide_database_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_dsn: str) -> None:
        raise readiness.psycopg.OperationalError("database unavailable")

    monkeypatch.setattr(readiness.psycopg, "connect", fail)

    with pytest.raises(readiness.psycopg.OperationalError):
        readiness.schema_head_003_ready("postgresql://reader")
