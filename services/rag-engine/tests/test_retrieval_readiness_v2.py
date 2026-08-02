"""Sonde fail-closed des privilèges PostgreSQL du rôle retrieval v2."""

from __future__ import annotations

from typing import Any

import pytest

from src.ingestor import retrieval_readiness_v2 as readiness

EXPECTED_RETRIEVAL_PRIVILEGES = (
    True,  # SELECT sur rag_chunks
    False,  # pas d'INSERT, y compris par colonne
    False,  # pas d'UPDATE, y compris par colonne
    False,  # pas de DELETE
    False,  # pas de TRUNCATE
    False,  # pas de REFERENCES, y compris par colonne
    False,  # pas de TRIGGER
    True,  # SELECT sur rag_schema_migrations
    False,  # pas d'INSERT registre, y compris par colonne
    False,  # pas d'UPDATE registre, y compris par colonne
    False,  # pas de DELETE registre
    False,  # pas de TRUNCATE registre
    False,  # pas de REFERENCES registre, y compris par colonne
    False,  # pas de TRIGGER registre
    False,  # aucune appartenance au propriétaire de rag_chunks
    False,  # aucune appartenance au propriétaire du registre
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
    True,  # USAGE sur le type vector
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


def test_retrieval_database_ready_proves_exact_read_only_privileges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cursor, captured = _patch_connection(
        monkeypatch,
        EXPECTED_RETRIEVAL_PRIVILEGES,
    )

    assert readiness.retrieval_database_ready("postgresql://reader") is True
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
    normalized = cursor.sql.upper()
    assert normalized.lstrip().startswith("SELECT")
    assert "RAG_CHUNKS" in normalized
    assert "RAG_SCHEMA_MIGRATIONS" in normalized
    assert "HAS_COLUMN_PRIVILEGE" in normalized
    assert "PG_ATTRIBUTE" in normalized
    assert "HAS_TYPE_PRIVILEGE" in normalized
    assert "PG_HAS_ROLE" in normalized
    assert "'MEMBER'" in normalized
    assert "REACHABLE_ROLE" in normalized


@pytest.mark.parametrize("position", range(len(EXPECTED_RETRIEVAL_PRIVILEGES)))
def test_retrieval_database_ready_rejects_every_privilege_drift(
    monkeypatch: pytest.MonkeyPatch,
    position: int,
) -> None:
    expected = list(EXPECTED_RETRIEVAL_PRIVILEGES)
    expected[position] = not expected[position]
    _patch_connection(monkeypatch, tuple(expected))

    assert readiness.retrieval_database_ready("postgresql://reader") is False


def test_retrieval_database_ready_rejects_missing_catalog_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_connection(monkeypatch, None)

    assert readiness.retrieval_database_ready("postgresql://reader") is False
