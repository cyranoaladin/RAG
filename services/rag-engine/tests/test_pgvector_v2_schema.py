"""Static tests for pgvector v2 schema alignment."""

from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
INIT_SQL = ENGINE_ROOT / "infra" / "postgres" / "init.sql"
MIGRATION_SQL = ENGINE_ROOT / "infra" / "postgres" / "migrations" / "001_rag_chunks_v2_schema.sql"
V2_COMPOSE = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"

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
