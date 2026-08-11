"""Contrat statique de la migration LOT41A-V2 du plan de contrôle."""
from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ENGINE_ROOT / "infra" / "postgres" / "ingestion_control" / "migrations"
ROLLBACKS = ENGINE_ROOT / "infra" / "postgres" / "ingestion_control" / "rollbacks"
MIGRATION = MIGRATIONS / "009_scope_authorization_content_allowlist.sql"
ROLLBACK = ROLLBACKS / "009_scope_authorization_content_allowlist.down.sql"
PIN_MIGRATION = MIGRATIONS / "011_external_authority_commit_pins.sql"
PIN_ROLLBACK = ROLLBACKS / "011_external_authority_commit_pins.down.sql"
ROLE_PROVISIONING = ENGINE_ROOT / "infra" / "scripts" / "provision_ingestion_control_roles.sh"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_migration_009_remains_the_canonical_v2_allowlist_step() -> None:
    assert _read(MIGRATIONS / "HEAD") == "012_artifact_attributions\n"
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


def test_migration_011_persists_an_immutable_external_review_snapshot() -> None:
    sql = _read(PIN_MIGRATION)

    assert "CREATE TABLE IF NOT EXISTS ingestion_control.publication_commit_pins" in sql
    assert "publication_attestation_id" in sql
    assert "publication_review_head_sha" in sql
    assert "publication_review_review_id" in sql
    assert "scope_authorization_id" in sql
    assert "authorization_digest" in sql
    assert "authorization_review_head_sha" in sql
    assert "authorization_review_review_id" in sql
    assert "authorization_protocol_version" in sql
    assert "pin_digest" in sql
    assert "LOT41A-V2" in sql
    assert "UPDATE" not in sql.upper()
    assert "DELETE" not in sql.upper()


def test_rollback_011_is_locked_and_refuses_to_discard_commit_pins() -> None:
    sql = _read(PIN_ROLLBACK)

    lock = sql.index(
        "LOCK TABLE ingestion_control.publication_commit_pins IN ACCESS EXCLUSIVE MODE"
    )
    refusal = sql.index("ROLLBACK_011_PUBLICATION_COMMIT_PINS_PRESENT")
    drop = sql.index("DROP TABLE ingestion_control.publication_commit_pins")
    assert lock < refusal < drop


def test_only_runtime_can_append_commit_pins_and_nobody_can_mutate_them() -> None:
    script = _read(ROLE_PROVISIONING)

    assert (
        'GRANT SELECT, INSERT ON ingestion_control.publication_commit_pins TO :"app_role"'
        in script
    )
    assert (
        "REVOKE UPDATE, DELETE, TRUNCATE ON "
        'ingestion_control.publication_commit_pins FROM :"app_role"'
        in script
    )
    assert (
        'GRANT SELECT, INSERT ON ingestion_control.publication_commit_pins TO :"authority_role"'
        not in script
    )
    assert (
        'GRANT SELECT, INSERT ON ingestion_control.publication_commit_pins TO :"attestor_role"'
        not in script
    )
