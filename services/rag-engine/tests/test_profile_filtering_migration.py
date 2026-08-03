"""Contrat de migration LOT41 pour les dimensions de filtrage serveur."""

from __future__ import annotations

import stat
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ENGINE_ROOT / "infra" / "postgres"
SCRIPTS = ENGINE_ROOT / "infra" / "scripts"
FINGERPRINTS = POSTGRES / "schema_head_003_fingerprints.env"
COLUMN_CONTRACT = POSTGRES / "schema_head_003_columns.tsv"


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
    healthcheck = _read(POSTGRES / "healthcheck.sh")

    for column in ("tenant", "candidat", "visibility", "school_year", "programme_version"):
        assert f"{column} " not in rag_chunks_bootstrap
    assert "text_tsv" in rag_chunks_bootstrap
    assert (
        "./postgres/migrations/003_profile_filtering.sql:"
        "/docker-entrypoint-initdb.d/01_003_profile_filtering.sql:ro"
    ) in compose
    assert "information_schema.columns" in healthcheck
    assert "idx_rag_chunks_profile_reviewed" in healthcheck


def test_fresh_bootstrap_registers_the_exact_migration_head() -> None:
    registration_path = POSTGRES / "register_bootstrap_migrations.sh"
    role_provisioning_path = POSTGRES / "provision_runtime_roles.sh"
    healthcheck_path = POSTGRES / "healthcheck.sh"
    compose = _read(ENGINE_ROOT / "infra" / "docker-compose.v2.yml")

    assert registration_path.is_file()
    assert registration_path.stat().st_mode & stat.S_IXUSR
    assert role_provisioning_path.is_file()
    assert role_provisioning_path.stat().st_mode & stat.S_IXUSR
    registration = _read(registration_path)
    assert "sha256sum" in registration
    assert "rag_schema_migrations" in registration
    for version, migration in (
        ("001", "001_rag_chunks_v2_schema.sql"),
        ("002", "002_hybrid_retrieval.sql"),
        ("003", "003_profile_filtering.sql"),
    ):
        assert migration in registration
        assert f"migration_{version}_sha" in registration

    assert (
        "./postgres/migrations:/docker-entrypoint-migrations:ro" in compose
    )
    assert (
        "./postgres/register_bootstrap_migrations.sh:"
        "/docker-entrypoint-initdb.d/02_register_bootstrap_migrations.sh:ro"
    ) in compose
    assert (
        "./postgres/provision_runtime_roles.sh:"
        "/docker-entrypoint-initdb.d/03_provision_runtime_roles.sh:ro"
    ) in compose
    provisioning = _read(role_provisioning_path)
    for setting in (
        "PGVECTOR_RETRIEVAL_USER",
        "PGVECTOR_RETRIEVAL_PASSWORD",
        "PGVECTOR_REVIEW_USER",
        "PGVECTOR_REVIEW_PASSWORD",
    ):
        assert setting in compose
        assert setting in provisioning
    assert "GRANT SELECT ON TABLE rag_chunks" in provisioning
    assert "GRANT UPDATE (review_status) ON TABLE rag_chunks" in provisioning
    assert "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS" in provisioning
    assert healthcheck_path.is_file()
    healthcheck = _read(healthcheck_path)
    assert "sha256sum" in healthcheck
    assert "rag_schema_migrations" in healthcheck
    assert "pg_get_constraintdef" in healthcheck
    assert "pg_get_indexdef" in healthcheck
    assert (
        "./postgres/healthcheck.sh:/docker-entrypoint-healthcheck.sh:ro" in compose
    )
    assert (
        "./postgres/schema_head_003_fingerprints.env:"
        "/schema-head-003-fingerprints.env:ro" in compose
    )
    assert (
        "./postgres/schema_head_003_columns.tsv:"
        "/schema-head-003-columns.tsv:ro" in compose
    )
    assert '"CMD", "bash", "/docker-entrypoint-healthcheck.sh"' in compose


def test_schema_object_fingerprints_have_one_versioned_source() -> None:
    assert FINGERPRINTS.is_file()
    fingerprints = _read(FINGERPRINTS)
    healthcheck = _read(POSTGRES / "healthcheck.sh")
    readiness = _read(ENGINE_ROOT / "src" / "ingestor" / "schema_readiness_v2.py")

    assert "RAG_CHUNKS_TENANT_LOT41_CHECK_MD5=" in fingerprints
    assert "RAG_CHUNKS_PROFILE_REVIEWED_INDEX_MD5=" in fingerprints
    assert "IDX_RAG_CHUNKS_VECTOR_MD5=" in fingerprints
    assert "IDX_RAG_CHUNKS_TEXT_TSV_MD5=" in fingerprints
    assert "RAG_CHUNKS_TEXT_TSV_EXPRESSION_MD5=" in fingerprints
    assert "/schema-head-003-fingerprints.env" in healthcheck
    assert "/schema-head-003-columns.tsv" in healthcheck
    assert "expected_rag_chunks_columns" in healthcheck
    assert "FROM (VALUES" not in healthcheck
    assert COLUMN_CONTRACT.is_file()
    assert "column_default" in healthcheck
    assert "format_type" in healthcheck
    assert "atttypmod" in healthcheck
    assert "count(DISTINCT column_name)" in healthcheck
    assert "relrowsecurity" in healthcheck
    assert "relforcerowsecurity" in healthcheck
    assert "pg_policy" in healthcheck
    assert "vector(1024)" in _read(COLUMN_CONTRACT)
    for line in fingerprints.splitlines():
        _key, separator, fingerprint = line.partition("=")
        assert separator
        assert fingerprint in fingerprints
        assert fingerprint not in healthcheck
        assert fingerprint not in readiness
