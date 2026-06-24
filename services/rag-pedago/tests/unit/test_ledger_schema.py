from __future__ import annotations

import sqlite3

from rag_pedago.ledger.migrations import initialize_database

EXPECTED_TABLES = {
    "schema_migrations",
    "runs",
    "documents",
    "document_states",
    "chunks",
    "errors",
}


def test_initialize_database_creates_tables(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"

    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()

    assert EXPECTED_TABLES <= {row[0] for row in rows}


def test_initialize_database_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "ledger.sqlite"

    initialize_database(db_path)
    initialize_database(db_path)

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT version FROM schema_migrations WHERE version = 1"
        ).fetchall()

    assert rows == [(1,)]

