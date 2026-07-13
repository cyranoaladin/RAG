"""Static tests for pgvector v2 schema alignment."""

from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
INIT_SQL = ENGINE_ROOT / "infra" / "postgres" / "init.sql"
MIGRATION_SQL = ENGINE_ROOT / "infra" / "postgres" / "migrations" / "001_rag_chunks_v2_schema.sql"
V2_COMPOSE = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"
UPGRADE_SCRIPT = ENGINE_ROOT / "infra" / "scripts" / "apply_pgvector_migrations.sh"

V2_REQUIRED_COLUMNS = (
    "chunk_id",
    "doc_id",
    "chunk_sha256",
    "collection",
    "niveau",
    "matiere",
    "review_status",
    "source_label",
    "source_uri",
    "rights",
    "type_doc",
)


def test_init_sql_defines_v2_columns() -> None:
    content = INIT_SQL.read_text(encoding="utf-8")
    for col in V2_REQUIRED_COLUMNS:
        assert col in content, f"init.sql must define column {col}"


def test_init_sql_uses_vector_1024() -> None:
    content = INIT_SQL.read_text(encoding="utf-8")
    assert "vector(1024)" in content, "init.sql must use vector(1024)"
    assert "vector(768)" not in content.lower().replace("vector(1024)", ""), (
        "init.sql must not define vector(768) for rag_chunks"
    )


def test_init_sql_no_legacy_columns() -> None:
    content = INIT_SQL.read_text(encoding="utf-8")
    # Legacy v1 used document_id UUID REFERENCES rag_documents and tenant
    for legacy in ("document_id UUID", "REFERENCES rag_documents"):
        assert legacy not in content, (
            f"init.sql must not contain legacy pattern: {legacy}"
        )


def test_migration_exists() -> None:
    assert MIGRATION_SQL.is_file(), "Migration 001 must exist"


def test_migration_has_data_guard() -> None:
    content = MIGRATION_SQL.read_text(encoding="utf-8")
    assert "COUNT(*)" in content, "Migration must check row count before rename"
    assert "RAISE EXCEPTION" in content, "Migration must refuse if legacy has data"


def test_migration_creates_v2_schema() -> None:
    content = MIGRATION_SQL.read_text(encoding="utf-8")
    assert "vector(1024)" in content
    for col in V2_REQUIRED_COLUMNS:
        assert col in content, f"Migration must define column {col}"


def test_migration_is_idempotent() -> None:
    content = MIGRATION_SQL.read_text(encoding="utf-8")
    assert "IF NOT EXISTS" in content, "Migration must use IF NOT EXISTS"
    assert "chunk_id" in content, "Migration must check for chunk_id to detect v2"


def test_compose_v2_mounts_init_sql() -> None:
    content = V2_COMPOSE.read_text(encoding="utf-8")
    assert "init.sql" in content, "docker-compose.v2.yml must mount init.sql"


# ── Upgrade script tests ────────────────────────────────────────────


def test_upgrade_script_exists() -> None:
    assert UPGRADE_SCRIPT.is_file(), "apply_pgvector_migrations.sh must exist"


def test_upgrade_script_strict_mode() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    assert "set -euo pipefail" in content


def test_upgrade_script_creates_backup() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    assert "pg_dump" in content, "Script must backup before migration"


def test_upgrade_script_uses_on_error_stop() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    assert "ON_ERROR_STOP=1" in content


def test_upgrade_script_applies_migrations() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    assert "postgres/migrations" in content, "Script must apply migrations from migrations dir"
    assert ".sql" in content


def test_upgrade_script_verifies_v2_columns() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    for col in ("chunk_id", "doc_id", "collection", "review_status",
                "source_label", "source_uri", "rights", "type_doc"):
        assert col in content, f"Script must verify column {col}"


def test_upgrade_script_verifies_vector_1024() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    assert "vector(1024)" in content


def test_upgrade_script_no_secret_leak() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    for pattern in ("echo $PGVECTOR_PASSWORD", "echo ${PGVECTOR_PASSWORD",
                    "cat .env", "cat ./.env"):
        assert pattern not in content, (
            f"Script must not leak secrets via: {pattern}"
        )
