"""Contrat de la clôture transactionnelle control→produit (migration 010)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "infra/postgres/ingestion_control/migrations"
ROLLBACKS = ROOT / "infra/postgres/ingestion_control/rollbacks"
MIGRATION = MIGRATIONS / "010_governed_publication_commit_fence.sql"
ROLLBACK = ROLLBACKS / "010_governed_publication_commit_fence.down.sql"


def test_migration_010_remains_the_declared_commit_fence_step() -> None:
    assert (MIGRATIONS / "HEAD").read_text(encoding="utf-8") == (
        "011_external_authority_commit_pins\n"
    )
    assert MIGRATION.is_file()
    assert ROLLBACK.is_file()


def test_migration_fences_every_mutable_publication_input() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")

    assert "_governed_publication_resource_fence" in sql
    assert "_governed_publication_authorization_fence" in sql
    for table in (
        "resources",
        "resource_candidates",
        "artifacts",
        "workflow_events",
        "publication_attestations",
    ):
        assert f"ON ingestion_control.{table}" in sql
    assert "ON ingestion_control.scope_authorizations" in sql
    assert "pg_advisory_xact_lock" in sql
    assert "SECURITY DEFINER" not in sql


def test_rollback_removes_only_the_commit_fence_objects() -> None:
    sql = ROLLBACK.read_text(encoding="utf-8")

    assert "DROP TRIGGER" in sql
    assert "DROP FUNCTION ingestion_control._governed_publication_resource_fence" in sql
    assert (
        "DROP FUNCTION ingestion_control._governed_publication_authorization_fence"
        in sql
    )
