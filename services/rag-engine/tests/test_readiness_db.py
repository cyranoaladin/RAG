"""Tests des attestations PostgreSQL partagées par la readiness v2."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ingestor import readiness_db


class _FakeCursor:
    def __init__(self, row: object) -> None:
        self._row = row
        self.query = ""

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, query: str) -> None:
        self.query = query

    def fetchone(self) -> object:
        return self._row


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> _FakeCursor:
        return self._cursor


def test_postgres_database_identity_is_bounded_read_only_and_cluster_specific(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor = _FakeCursor(("7549392456182038712", "nexus"))
    observed: dict[str, object] = {}

    def connect(dsn: str, **kwargs: object) -> _FakeConnection:
        observed.update({"dsn": dsn, **kwargs})
        return _FakeConnection(cursor)

    monkeypatch.setattr(
        readiness_db,
        "psycopg",
        SimpleNamespace(connect=connect),
        raising=False,
    )

    identity = readiness_db.postgres_database_identity("postgresql://runtime")

    assert identity == ("7549392456182038712", "nexus")
    assert observed == {
        "dsn": "postgresql://runtime",
        "connect_timeout": readiness_db.READINESS_CONNECT_TIMEOUT_S,
        "options": readiness_db.readiness_connection_options(),
    }
    assert "pg_control_system()" in cursor.query
    assert "current_database()" in cursor.query


@pytest.mark.parametrize(
    "row",
    (None, (None, "nexus"), ("123", ""), ("123",), ("123", "nexus", "extra")),
)
def test_postgres_database_identity_rejects_incomplete_results(
    monkeypatch: pytest.MonkeyPatch,
    row: object,
) -> None:
    cursor = _FakeCursor(row)
    monkeypatch.setattr(
        readiness_db,
        "psycopg",
        SimpleNamespace(
            connect=lambda *_args, **_kwargs: _FakeConnection(cursor),
        ),
        raising=False,
    )

    with pytest.raises(RuntimeError, match="database identity unavailable"):
        readiness_db.postgres_database_identity("postgresql://runtime")
