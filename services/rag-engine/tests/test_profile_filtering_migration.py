"""Contrat de migration LOT41 pour les dimensions de filtrage serveur."""

from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ENGINE_ROOT / "infra" / "postgres"
SCRIPTS = ENGINE_ROOT / "infra" / "scripts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_migration_manifest_declares_profile_filtering_head() -> None:
    assert _read(POSTGRES / "migrations" / "HEAD") == "003_profile_filtering\n"
    assert (POSTGRES / "migrations" / "003_profile_filtering.sql").is_file()
    assert (POSTGRES / "rollbacks" / "003_profile_filtering.down.sql").is_file()


def test_profile_filtering_migration_is_additive_without_inferred_backfill() -> None:
    sql = _read(POSTGRES / "migrations" / "003_profile_filtering.sql")

    for declaration in (
        "ADD COLUMN tenant TEXT",
        "ADD COLUMN candidat TEXT",
        "ADD COLUMN visibility TEXT",
        "ADD COLUMN school_year TEXT",
        "ADD COLUMN programme_version TEXT",
    ):
        assert declaration in sql
    for constraint in (
        "rag_chunks_tenant_lot41_check",
        "rag_chunks_candidat_lot41_check",
        "rag_chunks_visibility_lot41_check",
        "rag_chunks_school_year_lot41_check",
        "rag_chunks_programme_version_lot41_check",
    ):
        assert constraint in sql
    assert "idx_rag_chunks_profile_reviewed" in sql
    assert "UPDATE RAG_CHUNKS" not in sql.upper()
    for column in ("tenant", "candidat", "visibility", "school_year", "programme_version"):
        assert f"{column} TEXT NOT NULL" not in sql
    assert "DEFAULT 'both'" not in sql
    assert "DEFAULT 'internal'" not in sql


def test_profile_filtering_rollback_refuses_to_drop_enriched_rows() -> None:
    sql = _read(POSTGRES / "rollbacks" / "003_profile_filtering.down.sql")

    guard = sql.index("ROLLBACK_003_DATA_PRESENT")
    first_drop = sql.index("DROP INDEX")
    assert guard < first_drop
    for predicate in (
        "tenant IS NOT NULL",
        "school_year IS NOT NULL",
        "candidat IS NOT NULL",
        "visibility IS NOT NULL",
        "programme_version IS NOT NULL",
    ):
        assert predicate in sql
    for column in ("tenant", "candidat", "visibility", "school_year", "programme_version"):
        assert f"DROP COLUMN {column}" in sql


def test_migration_runtime_validates_schema_003_and_its_absence() -> None:
    library = _read(SCRIPTS / "lib" / "pgvector_migration_state.sh")
    apply = _read(SCRIPTS / "apply_pgvector_migrations.sh")
    rollback = _read(SCRIPTS / "rollback_pgvector_profile_filtering.sh")

    assert "validate_003_sql()" in library
    assert "validate_003_absent_sql()" in library
    assert "validate_003_sql" in apply
    assert "validate_003_absent_sql" in apply
    assert "003_profile_filtering" in rollback
    assert "validate_registry_sql 3" in rollback
    assert "validate_registry_sql 2" in rollback


def test_bootstrap_stays_at_002_and_compose_applies_003_on_fresh_volume() -> None:
    bootstrap = _read(POSTGRES / "init.sql")
    rag_chunks_bootstrap = bootstrap.split("-- TABLES AUXILIAIRES", maxsplit=1)[0]
    compose = _read(ENGINE_ROOT / "infra" / "docker-compose.v2.yml")

    for column in ("tenant", "candidat", "visibility", "school_year", "programme_version"):
        assert f"{column} " not in rag_chunks_bootstrap
    assert "text_tsv" in rag_chunks_bootstrap
    assert (
        "./postgres/migrations/003_profile_filtering.sql:"
        "/docker-entrypoint-initdb.d/01_003_profile_filtering.sql:ro"
    ) in compose
    assert "information_schema.columns" in compose
    assert "idx_rag_chunks_profile_reviewed" in compose
