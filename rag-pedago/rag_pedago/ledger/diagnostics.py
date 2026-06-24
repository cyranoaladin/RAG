from __future__ import annotations

from pathlib import Path
from typing import Any

from rag_pedago.ledger.db import connect


EXPECTED_TABLES = {
    "schema_migrations",
    "runs",
    "documents",
    "document_states",
    "chunks",
    "errors",
    "review_packages",
    "review_decisions",
    "controlled_import_attempts",
    "controlled_import_verifications",
}


def check_integrity(db_path: Path) -> dict[str, Any]:
    with connect(db_path) as conn:
        foreign_keys_enabled = bool(conn.execute("PRAGMA foreign_keys").fetchone()[0])
        integrity_check = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_rows = conn.execute("PRAGMA foreign_key_check").fetchall()
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        migrations_count = conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        counts = {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in [
                "runs",
                "documents",
                "chunks",
                "errors",
                "review_packages",
                "review_decisions",
                "controlled_import_attempts",
                "controlled_import_verifications",
            ]
        }

    return {
        "db_path": str(db_path),
        "integrity_check": integrity_check,
        "foreign_key_check": [tuple(row) for row in foreign_key_rows],
        "foreign_keys_enabled": foreign_keys_enabled,
        "tables_present": sorted(tables),
        "tables_ok": EXPECTED_TABLES <= tables,
        "migrations_count": migrations_count,
        "counts": counts,
    }
