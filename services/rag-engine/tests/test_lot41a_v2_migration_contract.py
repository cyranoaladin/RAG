"""Contrat statique de la migration LOT41A-V2 du plan de contrôle."""
from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ENGINE_ROOT / "infra" / "postgres" / "ingestion_control" / "migrations"
ROLLBACKS = ENGINE_ROOT / "infra" / "postgres" / "ingestion_control" / "rollbacks"
MIGRATION = MIGRATIONS / "009_scope_authorization_content_allowlist.sql"
ROLLBACK = ROLLBACKS / "009_scope_authorization_content_allowlist.down.sql"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_migration_009_remains_the_canonical_v2_allowlist_step() -> None:
    assert _read(MIGRATIONS / "HEAD") == "010_governed_publication_commit_fence\n"
    assert MIGRATION.name == "009_scope_authorization_content_allowlist.sql"


def test_migration_is_additive_and_version_discriminated() -> None:
    sql = _read(MIGRATION)

    assert "ADD COLUMN IF NOT EXISTS allowed_content_sha256 TEXT[]" in sql
    assert "protocol_version IN ('LOT41A-V1', 'LOT41A-V2')" in sql
    assert "protocol_version = 'LOT41A-V1'" in sql
    assert "protocol_version = 'LOT41A-V2'" in sql
    assert "allowed_content_sha256 IS NULL" in sql
    assert "allowed_content_sha256 IS NOT NULL" in sql
    assert "_scope_authorizations_content_allowlist_canonical" in sql
    assert "DROP TABLE" not in sql.upper()


def test_database_helper_encodes_the_complete_canonical_array_boundary() -> None:
    sql = _read(MIGRATION)

    assert "IMMUTABLE" in sql
    assert "array_ndims" in sql
    assert "array_lower" in sql
    assert "cardinality" in sql
    assert "array_position" in sql
    assert "^[0-9a-f]{64}$" in sql
    assert 'COLLATE "C"' in sql


def test_rollback_is_locked_and_refuses_to_discard_v2_rows() -> None:
    sql = _read(ROLLBACK)

    lock = sql.index("LOCK TABLE ingestion_control.scope_authorizations IN ACCESS EXCLUSIVE MODE")
    refusal = sql.index("ROLLBACK_009_V2_DATA_PRESENT")
    drop_column = sql.index("DROP COLUMN allowed_content_sha256")
    assert lock < refusal < drop_column
    assert "WHERE protocol_version = 'LOT41A-V2'" in sql
    assert "CHECK (protocol_version = 'LOT41A-V1')" in sql
    assert "DROP FUNCTION" in sql
