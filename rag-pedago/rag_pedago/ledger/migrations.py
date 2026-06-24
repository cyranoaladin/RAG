from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from rag_pedago.ledger.db import transaction
from rag_pedago.ledger.models import DOCUMENT_STATES, RUN_STATUSES, Migration


DEFAULT_LEDGER_PATH = Path("data/ledger/rag_pedago.sqlite")


def _quoted_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _apply_v1(conn: sqlite3.Connection) -> None:
    run_statuses = _quoted_values(RUN_STATUSES)
    document_states = _quoted_values(DOCUMENT_STATES)

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
            run_id TEXT PRIMARY KEY,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            status TEXT NOT NULL CHECK (status IN ({run_statuses})),
            command TEXT,
            git_commit TEXT,
            report_path TEXT,
            created_by TEXT,
            notes TEXT
        )
        """.format(run_statuses=run_statuses)
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS documents (
            doc_id TEXT PRIMARY KEY,
            source_uri TEXT NOT NULL,
            source_type TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            rights TEXT NOT NULL,
            visibility TEXT NOT NULL,
            niveau TEXT,
            voie TEXT,
            matiere TEXT NOT NULL,
            statut_enseignement TEXT,
            type_doc TEXT NOT NULL,
            epreuve TEXT,
            candidat TEXT,
            is_retrievable INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            metadata_json TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_states (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            doc_id TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ({document_states})),
            run_id TEXT NOT NULL,
            input_sha256 TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
            FOREIGN KEY (run_id) REFERENCES runs(run_id)
        )
        """.format(document_states=document_states)
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            doc_id TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_sha256 TEXT NOT NULL,
            page_start INTEGER,
            page_end INTEGER,
            char_count INTEGER,
            chunk_type TEXT NOT NULL,
            citation_label TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id),
            UNIQUE (doc_id, chunk_index)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS errors (
            error_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            doc_id TEXT,
            step TEXT NOT NULL,
            message TEXT NOT NULL,
            recoverable INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES runs(run_id),
            FOREIGN KEY (doc_id) REFERENCES documents(doc_id)
        )
        """
    )


def _apply_v2(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_packages (
            package_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            status TEXT NOT NULL,
            gate_status TEXT NOT NULL,
            readiness_status TEXT NOT NULL,
            coverage_status TEXT NOT NULL,
            review_package_sha256 TEXT NOT NULL,
            gate_json_sha256 TEXT NOT NULL,
            readiness_json_sha256 TEXT NOT NULL,
            coverage_json_sha256 TEXT NOT NULL,
            official_reference_sha256 TEXT NOT NULL,
            manifests_sha256_json TEXT NOT NULL,
            taxonomy_sha256_json TEXT NOT NULL,
            package_json_path TEXT,
            package_markdown_path TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_decisions (
            review_id TEXT PRIMARY KEY,
            package_id TEXT NOT NULL,
            batch_id TEXT NOT NULL,
            decision TEXT NOT NULL CHECK (decision IN ('approved', 'rejected')),
            reviewer TEXT NOT NULL,
            reviewed_at TEXT NOT NULL,
            review_package_sha256 TEXT NOT NULL,
            gate_json_sha256 TEXT NOT NULL,
            notes TEXT,
            decision_json_path TEXT,
            metadata_json TEXT NOT NULL,
            FOREIGN KEY (package_id) REFERENCES review_packages(package_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS controlled_import_attempts (
            attempt_id TEXT PRIMARY KEY,
            batch_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('imported', 'blocked_by_gate', 'failed')),
            gate_status TEXT NOT NULL,
            review_required INTEGER NOT NULL CHECK (review_required IN (0, 1)),
            review_id TEXT,
            package_id TEXT,
            documents_valid INTEGER NOT NULL DEFAULT 0,
            documents_invalid INTEGER NOT NULL DEFAULT 0,
            documents_not_retrievable INTEGER NOT NULL DEFAULT 0,
            run_ids_json TEXT NOT NULL,
            reasons_json TEXT NOT NULL,
            report_markdown_path TEXT,
            report_json_path TEXT,
            created_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL,
            FOREIGN KEY (review_id) REFERENCES review_decisions(review_id),
            FOREIGN KEY (package_id) REFERENCES review_packages(package_id)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS controlled_import_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            attempt_id TEXT NOT NULL,
            check_name TEXT NOT NULL,
            passed INTEGER NOT NULL CHECK (passed IN (0, 1)),
            message TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (attempt_id) REFERENCES controlled_import_attempts(attempt_id)
        )
        """
    )


MIGRATIONS = [
    Migration(version=1, description="create minimal ledger tables", apply=_apply_v1),
    Migration(version=2, description="add review and controlled import audit tables", apply=_apply_v2),
]


def initialize_database(db_path: Path = DEFAULT_LEDGER_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)

    with transaction(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL,
                description TEXT NOT NULL
            )
            """
        )
        applied_versions = {
            row["version"]
            for row in conn.execute("SELECT version FROM schema_migrations").fetchall()
        }
        for migration in MIGRATIONS:
            if migration.version in applied_versions:
                continue
            migration.apply(conn)
            conn.execute(
                """
                INSERT INTO schema_migrations (version, applied_at, description)
                VALUES (?, ?, ?)
                """,
                (
                    migration.version,
                    datetime.now(timezone.utc).isoformat(),
                    migration.description,
                ),
            )
