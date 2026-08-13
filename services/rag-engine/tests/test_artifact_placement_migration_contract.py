"""Contrat statique de la migration produit H2-C 004.

Ces tests complètent le cycle PostgreSQL réel du runner d'intégration. Ils
gardent les propriétés de sécurité lisibles au niveau du diff : migration
strictement additive, identité liée au contenu, rollback gardé et publisher
insert-only.
"""

from __future__ import annotations

from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ENGINE_ROOT / "infra" / "postgres"
MIGRATIONS = POSTGRES / "migrations"
ROLLBACKS = POSTGRES / "rollbacks"
SCRIPTS = ENGINE_ROOT / "infra" / "scripts"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_manifest_declares_artifact_placements_head() -> None:
    assert _read(MIGRATIONS / "HEAD") == "004_artifact_placements\n"
    assert (MIGRATIONS / "004_artifact_placements.sql").is_file()
    assert (ROLLBACKS / "004_artifact_placements.down.sql").is_file()


def test_migration_004_is_additive_and_content_bound() -> None:
    sql = _read(MIGRATIONS / "004_artifact_placements.sql")
    normalized = " ".join(sql.upper().split())

    assert "CREATE TABLE PUBLIC.RAG_ARTIFACTS" in normalized
    assert "CREATE TABLE PUBLIC.RAG_ARTIFACT_PLACEMENTS" in normalized
    assert "ADD COLUMN ARTIFACT_ID TEXT" in normalized
    assert "REFERENCES PUBLIC.RAG_ARTIFACTS (ARTIFACT_ID)" in normalized
    assert "ARTIFACT_ID = CONTENT_SHA256" in normalized
    assert "CONTENT_SHA256 TEXT NOT NULL UNIQUE" in normalized
    assert "(ARTIFACT_ID, CHUNK_INDEX)" in normalized
    assert "WHERE ARTIFACT_ID IS NOT NULL" in normalized
    assert "RAG_ARTIFACT_PLACEMENTS_CANONICAL_SCOPE_UNIQUE" in normalized
    assert "ARTIFACT_ID, COLLECTION, TENANT, NIVEAU, VOIE, AUDIENCE" in normalized

    for destructive in (
        "DROP TABLE RAG_CHUNKS",
        "TRUNCATE",
        "UPDATE RAG_CHUNKS",
        "DELETE FROM RAG_CHUNKS",
        "ALTER COLUMN VECTOR",
        "SET NOT NULL",
    ):
        assert destructive not in normalized


def test_migration_004_encodes_fail_closed_placement_state() -> None:
    sql = _read(MIGRATIONS / "004_artifact_placements.sql")

    for field in (
        "placement_id",
        "artifact_id",
        "collection",
        "tenant",
        "niveau",
        "voie",
        "audience",
        "matiere",
        "statut_enseignement",
        "candidat",
        "visibility",
        "school_year",
        "programme_version",
        "currentness",
        "placement_status",
        "source_scope",
        "source_placement_id",
        "source_uri",
        "authorization_id",
        "publication_attestation_id",
    ):
        assert field in sql
    assert "placement_status = 'active'" in sql
    assert "currentness = 'current'" in sql
    assert "reviewed" in sql


def test_rollback_004_refuses_to_drop_governed_rows() -> None:
    sql = _read(ROLLBACKS / "004_artifact_placements.down.sql")
    normalized = " ".join(sql.upper().split())

    lock = normalized.index(
        "LOCK TABLE PUBLIC.RAG_ARTIFACTS, PUBLIC.RAG_ARTIFACT_PLACEMENTS, "
        "PUBLIC.RAG_CHUNKS IN ACCESS EXCLUSIVE MODE"
    )
    guard = normalized.index("ROLLBACK_004_DATA_PRESENT")
    first_drop = normalized.index("DROP INDEX")
    assert lock < guard < first_drop
    assert "ARTIFACT_ID IS NOT NULL" in normalized
    assert "PUBLIC.RAG_ARTIFACTS" in normalized
    assert "PUBLIC.RAG_ARTIFACT_PLACEMENTS" in normalized
    assert "DROP COLUMN ARTIFACT_ID" in normalized


def test_migration_runtime_validates_004_and_rollback() -> None:
    library = _read(SCRIPTS / "lib" / "pgvector_migration_state.sh")
    apply = _read(SCRIPTS / "apply_pgvector_migrations.sh")
    rollback = _read(SCRIPTS / "rollback_pgvector_artifact_placements.sh")

    assert "validate_004_sql()" in library
    assert "validate_004_absent_sql()" in library
    assert "validate_004_sql" in apply
    assert "validate_004_absent_sql" in apply
    assert "004_artifact_placements" in rollback
    assert "validate_registry_sql 4" in rollback
    assert "validate_registry_sql 3" in rollback


def test_upgrade_runner_reconciles_runtime_roles_after_head_004() -> None:
    apply = _read(SCRIPTS / "apply_pgvector_migrations.sh")
    provisioning = _read(POSTGRES / "provision_runtime_roles.sh")

    assert "provision_runtime_roles" in apply
    assert "PGVECTOR_RETRIEVAL_USER" in apply
    assert "PGVECTOR_REVIEW_USER" in apply
    assert "PGVECTOR_PUBLISHER_USER" in apply
    assert '-e "PGVECTOR_RETRIEVAL_PASSWORD=$' not in apply
    assert '-e "PGVECTOR_REVIEW_PASSWORD=$' not in apply
    assert '-e "PGVECTOR_PUBLISHER_PASSWORD=$' not in apply
    transition = apply.index("run_up_transition")
    assert transition < apply.index("provision_runtime_roles_sql", transition)
    assert "WHERE NOT EXISTS" in provisioning
    assert "ALTER ROLE" in provisioning
    assert "GRANT SELECT ON TABLE rag_chunks, rag_artifacts" in provisioning
    assert "GRANT SELECT, INSERT ON TABLE rag_artifacts" in provisioning


def test_publisher_role_is_insert_only_on_product_tables() -> None:
    provisioning = _read(POSTGRES / "provision_runtime_roles.sh")

    for variable in ("PGVECTOR_PUBLISHER_USER", "PGVECTOR_PUBLISHER_PASSWORD"):
        assert variable in provisioning
    for table in ("rag_artifacts", "rag_artifact_placements", "rag_chunks"):
        assert f"GRANT SELECT, INSERT ON TABLE {table}" in provisioning
    assert "GRANT UPDATE ON TABLE rag_artifacts" not in provisioning
    assert "GRANT UPDATE ON TABLE rag_artifact_placements" not in provisioning
    assert "GRANT DELETE" not in provisioning
    assert "GRANT TRUNCATE" not in provisioning
