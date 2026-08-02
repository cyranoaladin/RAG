"""Sonde fail-closed des privilèges PostgreSQL du rôle de revue v2."""

from __future__ import annotations

from typing import Any

import pytest

from src.ingestor import review_readiness_v2 as readiness

EXPECTED_REVIEW_PRIVILEGES = (
    True,  # SELECT sur rag_chunks
    False,  # pas d'INSERT au niveau table
    True,  # aucune colonne ne permet INSERT
    False,  # pas de DELETE
    False,  # pas de TRUNCATE
    False,  # pas d'UPDATE au niveau table
    True,  # UPDATE limité à review_status
    True,  # aucune autre colonne modifiable
    False,  # aucune appartenance au propriétaire
    False,  # aucun rôle atteignable par SET ROLE
    False,  # pas superuser
    False,  # pas CREATEDB
    False,  # pas CREATEROLE
    False,  # pas REPLICATION
    False,  # pas BYPASSRLS
    True,  # USAGE sur le schéma public
    False,  # pas CREATE sur le schéma public
    False,  # pas CREATE sur la base
    False,  # pas de tables temporaires
)


class _Cursor:
    def __init__(self, row: tuple[object, ...] | None) -> None:
        self.row = row
        self.sql = ""

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        self.sql = sql

    def fetchone(self) -> tuple[object, ...] | None:
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


def _patch_connection(
    monkeypatch: pytest.MonkeyPatch,
    row: tuple[object, ...] | None,
) -> tuple[_Cursor, dict[str, Any]]:
    cursor = _Cursor(row)
    captured: dict[str, Any] = {}

    def connect(dsn: str, **kwargs: object) -> _Connection:
        captured["dsn"] = dsn
        captured["kwargs"] = kwargs
        return _Connection(cursor)

    monkeypatch.setattr(readiness.psycopg, "connect", connect)
    return cursor, captured


def test_review_database_ready_proves_the_exact_least_privilege_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor, captured = _patch_connection(monkeypatch, EXPECTED_REVIEW_PRIVILEGES)

    assert readiness.review_database_ready("postgresql://reviewer") is True
    assert captured == {
        "dsn": "postgresql://reviewer",
        "kwargs": {
            "connect_timeout": readiness.READINESS_CONNECT_TIMEOUT_S,
            "options": (
                "-c statement_timeout="
                f"{readiness.READINESS_STATEMENT_TIMEOUT_MS} "
                "-c default_transaction_read_only=on"
            ),
        },
    }
    normalized = cursor.sql.upper()
    assert normalized.lstrip().startswith("SELECT")
    assert "HAS_TABLE_PRIVILEGE" in normalized
    assert "HAS_COLUMN_PRIVILEGE" in normalized
    assert "PG_HAS_ROLE" in normalized
    assert "'MEMBER'" in normalized
    assert "REACHABLE_ROLE" in normalized
    assert "HAS_SCHEMA_PRIVILEGE" in normalized
    assert "HAS_DATABASE_PRIVILEGE" in normalized
    assert "REVIEW_STATUS" in normalized
    assert "NOT EXISTS" in normalized
    assert "ATTNAME" in normalized
    assert "'INSERT'" in normalized
    assert "ATTNAME <> 'REVIEW_STATUS'" in normalized
    for forbidden in ("INSERT INTO", "UPDATE ", "DELETE FROM", "ALTER ", "CREATE ", "DROP "):
        assert forbidden not in normalized


@pytest.mark.parametrize("position", range(len(EXPECTED_REVIEW_PRIVILEGES)))
def test_review_database_ready_rejects_every_privilege_drift(
    monkeypatch: pytest.MonkeyPatch,
    position: int,
) -> None:
    expected = list(EXPECTED_REVIEW_PRIVILEGES)
    expected[position] = not expected[position]
    _patch_connection(monkeypatch, tuple(expected))

    assert readiness.review_database_ready("postgresql://reviewer") is False


def test_review_database_ready_rejects_a_missing_relation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connection(monkeypatch, None)

    assert readiness.review_database_ready("postgresql://reviewer") is False
