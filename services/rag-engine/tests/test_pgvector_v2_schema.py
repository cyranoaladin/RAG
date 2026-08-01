"""Static tests for pgvector v2 schema alignment."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
INIT_SQL = ENGINE_ROOT / "infra" / "postgres" / "init.sql"
MIGRATION_SQL = ENGINE_ROOT / "infra" / "postgres" / "migrations" / "001_rag_chunks_v2_schema.sql"
MIGRATION_002 = ENGINE_ROOT / "infra" / "postgres" / "migrations" / "002_hybrid_retrieval.sql"
MIGRATION_HEAD = ENGINE_ROOT / "infra" / "postgres" / "migrations" / "HEAD"
ROLLBACK_002 = (
    ENGINE_ROOT
    / "infra"
    / "postgres"
    / "rollbacks"
    / "002_hybrid_retrieval.down.sql"
)
MIGRATION_002_ALLOWED_STATEMENTS = [
    "ALTER TABLE rag_chunks ADD COLUMN IF NOT EXISTS text_tsv tsvector "
    "GENERATED ALWAYS AS (to_tsvector('french', coalesce(text, ''))) STORED",
    "CREATE INDEX IF NOT EXISTS idx_rag_chunks_text_tsv "
    "ON rag_chunks USING gin (text_tsv)",
]
ROLLBACK_002_ALLOWED_STATEMENTS = [
    "DROP INDEX IF EXISTS idx_rag_chunks_text_tsv",
    "ALTER TABLE rag_chunks DROP COLUMN IF EXISTS text_tsv",
]
V2_COMPOSE = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"
UPGRADE_SCRIPT = ENGINE_ROOT / "infra" / "scripts" / "apply_pgvector_migrations.sh"
MIGRATION_LIBRARY = (
    ENGINE_ROOT / "infra" / "scripts" / "lib" / "pgvector_migration_state.sh"
)
ROLLBACK_SCRIPT = (
    ENGINE_ROOT / "infra" / "scripts" / "rollback_pgvector_migration.sh"
)

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
    content = (
        UPGRADE_SCRIPT.read_text(encoding="utf-8")
        + MIGRATION_LIBRARY.read_text(encoding="utf-8")
    )
    assert "postgres/migrations" in content, "Script must apply migrations from migrations dir"
    assert ".sql" in content


def test_upgrade_script_verifies_v2_columns() -> None:
    content = (
        UPGRADE_SCRIPT.read_text(encoding="utf-8")
        + MIGRATION_LIBRARY.read_text(encoding="utf-8")
    )
    for col in ("chunk_id", "doc_id", "collection", "review_status",
                "source_label", "source_uri", "rights", "type_doc"):
        assert col in content, f"Script must verify column {col}"


def test_upgrade_script_verifies_vector_1024() -> None:
    content = (
        UPGRADE_SCRIPT.read_text(encoding="utf-8")
        + MIGRATION_LIBRARY.read_text(encoding="utf-8")
    )
    assert "vector(1024)" in content


def test_upgrade_script_no_secret_leak() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    for pattern in ("echo $PGVECTOR_PASSWORD", "echo ${PGVECTOR_PASSWORD",
                    "cat .env", "cat ./.env"):
        assert pattern not in content, (
            f"Script must not leak secrets via: {pattern}"
        )


def test_upgrade_script_no_hardcoded_backup_root() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    assert 'BACKUP_ROOT:-/backup' not in content, (
        "Script must not default BACKUP_ROOT to an absolute path"
    )
    assert '${BACKUP_ROOT:-/backup/rag}' not in content


def test_upgrade_script_requires_backup_root() -> None:
    content = UPGRADE_SCRIPT.read_text(encoding="utf-8")
    assert "BACKUP_ROOT:?" in content, (
        "Script must require BACKUP_ROOT to be set"
    )


def test_migration_library_exposes_exact_registry_contract() -> None:
    content = MIGRATION_LIBRARY.read_text(encoding="utf-8")
    normalized = " ".join(content.split())
    assert "rag_schema_migrations" in content
    assert "version integer PRIMARY KEY" in normalized
    assert "CHECK (version > 0)" in normalized
    assert "file_name text NOT NULL UNIQUE" in normalized
    assert "btrim(file_name) <> ''" in normalized
    assert "sha256 text NOT NULL" in normalized
    assert "^[0-9a-f]{64}$" in content
    assert "applied_at timestamptz NOT NULL DEFAULT now()" in normalized


@pytest.mark.parametrize(
    "needle",
    [
        "rag_schema_migrations",
        "sha256sum",
        "pg_advisory_xact_lock",
        "MIGRATION_CHECKSUM_MISMATCH",
        "MIGRATION_GAP",
        "vector(1024)",
        "pg_get_expr",
        "pg_get_indexdef",
        "SCHEMA_HEAD_001_INVALID",
        "SCHEMA_HEAD_002_INVALID",
    ],
)
def test_migration_library_declares_exact_invariants(needle: str) -> None:
    assert needle in MIGRATION_LIBRARY.read_text(encoding="utf-8")


def test_migration_library_validates_all_001_columns_and_indexes() -> None:
    content = MIGRATION_LIBRARY.read_text(encoding="utf-8")
    for column in (
        "chunk_id",
        "doc_id",
        "chunk_sha256",
        "vector",
        "collection",
        "niveau",
        "voie",
        "audience",
        "matiere",
        "statut_enseignement",
        "notions",
        "domain",
        "source_label",
        "source_uri",
        "rights",
        "type_doc",
        "official",
        "text",
        "chunk_index",
        "page_start",
        "page_end",
        "review_status",
        "model",
        "source_kind",
        "indexed_at",
    ):
        assert column in content
    for index in (
        "rag_chunks_pkey",
        "idx_rag_chunks_vector",
        "idx_rag_chunks_collection",
        "idx_rag_chunks_niveau",
        "idx_rag_chunks_matiere",
        "idx_rag_chunks_audience",
        "idx_rag_chunks_rights",
        "idx_rag_chunks_review",
    ):
        assert index in content
    assert "PRIMARY KEY (chunk_id)" in content
    assert "format_type" in content


def test_migration_runners_use_single_transaction_and_advisory_lock() -> None:
    library = MIGRATION_LIBRARY.read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in library
    for path in (UPGRADE_SCRIPT, ROLLBACK_SCRIPT):
        content = path.read_text(encoding="utf-8")
        assert "--single-transaction" in content
        assert "advisory_lock_sql" in content


# ── Migration legacy pkey guard ──────────────────────────────────────


def test_migration_renames_legacy_pkey_before_table_rename() -> None:
    content = MIGRATION_SQL.read_text(encoding="utf-8")
    assert "rag_chunks_pkey" in content, (
        "Migration must handle legacy rag_chunks_pkey constraint"
    )
    assert "rag_chunks_legacy_pre_v2_001_pkey" in content, (
        "Migration must rename pkey to rag_chunks_legacy_pre_v2_001_pkey"
    )
    # The pkey rename must appear before the table rename
    pkey_pos = content.index("rag_chunks_legacy_pre_v2_001_pkey")
    table_rename_pos = content.index("RENAME TO rag_chunks_legacy_pre_v2_001;")
    assert pkey_pos < table_rename_pos, (
        "pkey rename must occur before table rename"
    )


# ── Migration 002: hybrid retrieval ────────────────────────────────


def _normalized_sql(path: Path) -> str:
    return " ".join(path.read_text(encoding="utf-8").split())


def _sql_statements(path: Path) -> list[str]:
    content = path.read_text(encoding="utf-8")
    without_block_comments = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    without_comments = re.sub(
        r"--.*?$",
        "",
        without_block_comments,
        flags=re.MULTILINE,
    )
    return [
        " ".join(statement.split())
        for statement in without_comments.split(";")
        if statement.strip()
    ]


def _assert_hybrid_search_schema(path: Path) -> None:
    content = _normalized_sql(path)
    assert (
        "text_tsv tsvector GENERATED ALWAYS AS "
        "(to_tsvector('french', coalesce(text, ''))) STORED"
    ) in content
    assert (
        "CREATE INDEX IF NOT EXISTS idx_rag_chunks_text_tsv "
        "ON rag_chunks USING gin (text_tsv)"
    ) in content


def test_migration_head_points_exactly_to_002() -> None:
    assert MIGRATION_HEAD.read_text(encoding="utf-8") == "002_hybrid_retrieval\n"


def test_migration_002_adds_generated_french_fts_column_and_named_gin_index() -> None:
    _assert_hybrid_search_schema(MIGRATION_002)


def test_migration_002_contains_only_whitelisted_statements() -> None:
    assert _sql_statements(MIGRATION_002) == MIGRATION_002_ALLOWED_STATEMENTS


def test_init_sql_matches_migration_002_hybrid_search_schema() -> None:
    _assert_hybrid_search_schema(INIT_SQL)


def test_migration_002_rollback_is_outside_up_migrations() -> None:
    assert ROLLBACK_002.is_file()
    assert ROLLBACK_002.parent != MIGRATION_002.parent
    assert ROLLBACK_002 not in MIGRATION_002.parent.glob("*.sql")


def test_migration_002_rollback_only_removes_its_column() -> None:
    content = ROLLBACK_002.read_text(encoding="utf-8")
    dropped_columns = re.findall(
        r"\bDROP\s+COLUMN(?:\s+IF\s+EXISTS)?\s+([a-z_][a-z0-9_]*)",
        content,
        flags=re.IGNORECASE,
    )
    assert dropped_columns == ["text_tsv"]
    assert not re.search(r"\b(?:DELETE|DROP\s+TABLE|TRUNCATE)\b", content, re.IGNORECASE)


def test_migration_002_rollback_drops_index_before_column() -> None:
    content = _normalized_sql(ROLLBACK_002).upper()
    assert content.index("DROP INDEX") < content.index("DROP COLUMN")


def test_migration_002_rollback_contains_only_whitelisted_statements() -> None:
    assert _sql_statements(ROLLBACK_002) == ROLLBACK_002_ALLOWED_STATEMENTS


def test_sql_statement_extractor_retains_arbitrary_extra_statements(
    tmp_path: Path,
) -> None:
    mutated_sql = tmp_path / "mutated.sql"
    mutated_sql.write_text(
        MIGRATION_002.read_text(encoding="utf-8")
        + "\n-- Ce commentaire doit être ignoré.\n"
        + "DROP SCHEMA public;\n"
        + "DELETE FROM rag_chunks;\n",
        encoding="utf-8",
    )

    assert _sql_statements(mutated_sql) == [
        *MIGRATION_002_ALLOWED_STATEMENTS,
        "DROP SCHEMA public",
        "DELETE FROM rag_chunks",
    ]
