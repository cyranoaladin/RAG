"""Contrat statique de la migration produit 005 (ADR-0059 § 2).

`rag_artifact_placements.currentness` admet `official_snapshot` : l'instantané
officiel ADR-0055 dont l'actualité réseau n'a pas pu être établie. `current`
reste réservé à l'identité d'octets prouvée. Le retrieval sert les deux, et
jamais `archive` ni `review_required`.

Ces épreuves gardent lisibles, au niveau du diff, les propriétés que le cycle
PostgreSQL réel du runner d'intégration exerce : migration strictement
additive, contrôle transactionnel laissé au runner, rollback qui refuse au
lieu de réécrire, et définitions 004 restaurées à l'identique.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
INFRA = ENGINE_ROOT / "infra"
POSTGRES = INFRA / "postgres"
MIGRATIONS = POSTGRES / "migrations"
ROLLBACKS = POSTGRES / "rollbacks"
SCRIPTS = INFRA / "scripts"

MIGRATION_005 = MIGRATIONS / "005_official_snapshot_currentness.sql"
ROLLBACK_005 = ROLLBACKS / "005_official_snapshot_currentness.down.sql"
MIGRATION_004 = MIGRATIONS / "004_artifact_placements.sql"

# Définitions exactes que PostgreSQL 16 restitue (pg_get_constraintdef(oid,
# true) et pg_get_expr(indpred, indrelid, true)), relevées sur une base réelle
# migrée par les fichiers livrés. Ce sont elles que les validateurs SQL et
# les empreintes du head 005 figent.
CURRENTNESS_CHECK_005 = (
    "CHECK (currentness = ANY (ARRAY['current'::text, "
    "'official_snapshot'::text, 'archive'::text, 'review_required'::text]))"
)
CURRENTNESS_CHECK_004 = (
    "CHECK (currentness = ANY (ARRAY['current'::text, 'archive'::text, "
    "'review_required'::text]))"
)
SCOPE_PREDICATE_005 = (
    "placement_status = 'active'::text AND (currentness = ANY "
    "(ARRAY['current'::text, 'official_snapshot'::text])) AND "
    "review_status = 'reviewed'::text"
)
SCOPE_PREDICATE_004 = (
    "placement_status = 'active'::text AND currentness = 'current'::text "
    "AND review_status = 'reviewed'::text"
)
SCOPE_INDEX_PREFIX = (
    "CREATE INDEX idx_rag_artifact_placements_scope_active ON "
    "public.rag_artifact_placements USING btree (collection, tenant, niveau, "
    "voie, matiere, statut_enseignement, candidat, school_year, "
    "programme_version, artifact_id) WHERE "
)
SCOPE_INDEX_005 = (
    SCOPE_INDEX_PREFIX
    + "((placement_status = 'active'::text) AND (currentness = ANY "
    "(ARRAY['current'::text, 'official_snapshot'::text])) AND "
    "(review_status = 'reviewed'::text))"
)
WIDENED_FINGERPRINT_KEYS = {
    "PLACEMENTS_CURRENTNESS_CHECK_MD5",
    "PLACEMENTS_SCOPE_INDEX_MD5",
    "PLACEMENTS_SCOPE_PREDICATE_MD5",
}
_TRANSACTION_CONTROL = re.compile(
    r"^\s*(BEGIN|COMMIT|ROLLBACK|START\s+TRANSACTION|END)\s*;\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _normalized(path: Path) -> str:
    return " ".join(_read(path).upper().split())


def _without_comments(path: Path) -> str:
    return "\n".join(
        line for line in _read(path).splitlines() if not line.lstrip().startswith("--")
    )


def _fingerprints(path: Path) -> dict[str, str]:
    return dict(line.split("=", 1) for line in _read(path).splitlines())


def test_manifest_declares_the_official_snapshot_head() -> None:
    assert _read(MIGRATIONS / "HEAD") == "005_official_snapshot_currentness\n"
    assert MIGRATION_005.is_file()
    assert ROLLBACK_005.is_file()
    assert sorted(path.name for path in MIGRATIONS.glob("*.sql"))[-1] == (
        MIGRATION_005.name
    )


def test_migration_005_only_widens_currentness_and_the_served_index() -> None:
    normalized = " ".join(_without_comments(MIGRATION_005).upper().split())

    assert (
        "ALTER TABLE PUBLIC.RAG_ARTIFACT_PLACEMENTS "
        "DROP CONSTRAINT RAG_ARTIFACT_PLACEMENTS_CURRENTNESS_CHECK, "
        "ADD CONSTRAINT RAG_ARTIFACT_PLACEMENTS_CURRENTNESS_CHECK "
        "CHECK (CURRENTNESS IN ('CURRENT', 'OFFICIAL_SNAPSHOT', 'ARCHIVE', "
        "'REVIEW_REQUIRED'));"
    ) in normalized
    assert "DROP INDEX PUBLIC.IDX_RAG_ARTIFACT_PLACEMENTS_SCOPE_ACTIVE;" in normalized
    assert (
        "CREATE INDEX IDX_RAG_ARTIFACT_PLACEMENTS_SCOPE_ACTIVE "
        "ON PUBLIC.RAG_ARTIFACT_PLACEMENTS ( COLLECTION, TENANT, NIVEAU, VOIE, "
        "MATIERE, STATUT_ENSEIGNEMENT, CANDIDAT, SCHOOL_YEAR, "
        "PROGRAMME_VERSION, ARTIFACT_ID ) WHERE PLACEMENT_STATUS = 'ACTIVE' "
        "AND CURRENTNESS IN ('CURRENT', 'OFFICIAL_SNAPSHOT') "
        "AND REVIEW_STATUS = 'REVIEWED';"
    ) in normalized
    # Strictement additive : aucune ligne n'est lue pour être réécrite,
    # aucun objet hors de la contrainte et de l'index n'est touché.
    for forbidden in (
        "UPDATE ",
        "DELETE ",
        "INSERT ",
        "TRUNCATE",
        "DROP TABLE",
        "DROP COLUMN",
        "ADD COLUMN",
        "ALTER COLUMN",
        "NOT VALID",
        "CONCURRENTLY",
        "RAG_CHUNKS",
        "RAG_ARTIFACTS ",
    ):
        assert forbidden not in normalized, forbidden
    assert normalized.count("ALTER TABLE") == 1
    assert normalized.count("CREATE INDEX") == 1
    assert normalized.count("DROP INDEX") == 1


def test_product_sql_files_leave_transaction_control_to_the_runner() -> None:
    # Le runner exécute migration, registre et validateurs dans UNE
    # transaction (`psql --single-transaction`). Un `COMMIT;` dans le fichier
    # validerait la transaction extérieure à mi-parcours (lot CU).
    for path in (MIGRATION_005, ROLLBACK_005):
        assert _TRANSACTION_CONTROL.search(_read(path)) is None, path.name


def test_rollback_005_fails_closed_before_any_redefinition() -> None:
    body = _without_comments(ROLLBACK_005)
    normalized = " ".join(body.upper().split())

    lock = normalized.index(
        "LOCK TABLE PUBLIC.RAG_ARTIFACT_PLACEMENTS IN ACCESS EXCLUSIVE MODE;"
    )
    guard = normalized.index(
        "SELECT 1 FROM PUBLIC.RAG_ARTIFACT_PLACEMENTS "
        "WHERE CURRENTNESS = 'OFFICIAL_SNAPSHOT'"
    )
    refusal = normalized.index("RAISE EXCEPTION 'ROLLBACK_005_OFFICIAL_SNAPSHOT_PRESENT'")
    first_mutation = min(
        normalized.index("DROP INDEX"), normalized.index("ALTER TABLE")
    )
    assert lock < guard < refusal < first_mutation
    # Refuser vaut mieux que réécrire : aucune ligne n'est supprimée ni
    # requalifiée pour faire passer la contrainte 004.
    for forbidden in ("UPDATE ", "DELETE ", "INSERT ", "TRUNCATE", "DROP TABLE"):
        assert forbidden not in normalized, forbidden
    # Le verrou ne vise que la table redéfinie : aucun cycle possible avec
    # l'ordre artefact -> placements -> chunks du publisher.
    assert "PUBLIC.RAG_ARTIFACTS" not in normalized
    assert "PUBLIC.RAG_CHUNKS" not in normalized


def test_rollback_005_restores_the_exact_004_definitions() -> None:
    migration_004 = " ".join(_read(MIGRATION_004).split())
    rollback = " ".join(_without_comments(ROLLBACK_005).split())

    check_004 = (
        "CONSTRAINT rag_artifact_placements_currentness_check "
        "CHECK (currentness IN ('current', 'archive', 'review_required'))"
    )
    index_004 = (
        "CREATE INDEX idx_rag_artifact_placements_scope_active "
        "ON public.rag_artifact_placements ( collection, tenant, niveau, voie, "
        "matiere, statut_enseignement, candidat, school_year, "
        "programme_version, artifact_id ) WHERE placement_status = 'active' "
        "AND currentness = 'current' AND review_status = 'reviewed';"
    )
    assert check_004 in migration_004
    assert index_004 in migration_004
    assert (
        "ALTER TABLE public.rag_artifact_placements "
        "DROP CONSTRAINT rag_artifact_placements_currentness_check, "
        f"ADD {check_004};"
    ) in rollback
    assert "DROP INDEX public.idx_rag_artifact_placements_scope_active;" in rollback
    assert index_004 in rollback


def test_shared_validators_pin_both_sides_of_migration_005() -> None:
    library = _read(SCRIPTS / "lib" / "pgvector_migration_state.sh")

    present = library[library.index("validate_005_sql() {") :]
    present = present[: present.index("\n}\n")]
    absent = library[library.index("validate_005_absent_sql() {") :]
    absent = absent[: absent.index("\n}\n")]
    assert CURRENTNESS_CHECK_005 in present
    assert SCOPE_PREDICATE_005 in present
    assert "SCHEMA_HEAD_005_INVALID" in present
    assert CURRENTNESS_CHECK_004 in absent
    assert SCOPE_PREDICATE_004 in absent
    assert "official_snapshot" not in absent


def test_upgrade_runner_and_rollbacks_know_head_005() -> None:
    apply = _read(SCRIPTS / "apply_pgvector_migrations.sh")
    rollback_005 = _read(SCRIPTS / "rollback_pgvector_official_snapshot_currentness.sh")
    rollback_004 = _read(SCRIPTS / "rollback_pgvector_artifact_placements.sh")

    assert "validate_005_sql" in apply
    assert "validate_005_absent_sql" in apply
    assert "005_official_snapshot_currentness" in rollback_005
    assert "005_official_snapshot_currentness.down.sql" in rollback_005
    assert "validate_registry_sql 5" in rollback_005
    assert "validate_registry_sql 4" in rollback_005
    assert "validate_005_absent_sql" in rollback_005
    assert "WHERE version = 5;" in rollback_005
    assert '"$EFFECTIVE_HEAD" -ne 5' in rollback_005
    # Le rollback 004 reste exécutable sous un manifeste déclaré au-delà de
    # 004, à condition que la base soit effectivement redescendue à 004.
    assert '"$MIGRATION_DECLARED_HEAD" != "004_artifact_placements"' not in rollback_004
    assert '"$EFFECTIVE_HEAD" -ne 4' in rollback_004
    assert "validate_005_absent_sql" in rollback_004


def test_fresh_volume_bootstraps_and_registers_head_005() -> None:
    compose = _read(INFRA / "docker-compose.v2.yml")
    registration = _read(POSTGRES / "register_bootstrap_migrations.sh")
    healthcheck = _read(POSTGRES / "healthcheck.sh")

    initdb = re.findall(r"/docker-entrypoint-initdb\.d/([^:]+):ro", compose)
    assert initdb == [
        "00_init.sql",
        "01_003_profile_filtering.sql",
        "02_004_artifact_placements.sql",
        "03_005_official_snapshot_currentness.sql",
        "04_register_bootstrap_migrations.sh",
        "05_provision_runtime_roles.sh",
    ]
    assert (
        "./postgres/migrations/005_official_snapshot_currentness.sql:"
        "/docker-entrypoint-initdb.d/03_005_official_snapshot_currentness.sql:ro"
    ) in compose
    assert "005_official_snapshot_currentness.sql" in registration
    assert "(5, :'migration_005_file', :'migration_005_sha')" in registration
    assert '"$MIGRATION_DECLARED_HEAD" != "005_official_snapshot_currentness"' in healthcheck
    assert "validate_005_sql" in healthcheck
    assert "validate_registry_sql 5" in healthcheck


def test_head_005_contract_files_are_shipped_everywhere_they_are_read() -> None:
    compose = _read(INFRA / "docker-compose.v2.yml")
    dockerfile = _read(INFRA / "Dockerfile.ingestor-v2")
    dockerignore = _read(REPO_ROOT / ".dockerignore")
    healthcheck = _read(POSTGRES / "healthcheck.sh")

    for name in ("schema_head_005_fingerprints.env", "schema_head_005_columns.tsv"):
        assert (POSTGRES / name).is_file()
        assert f"!services/rag-engine/infra/postgres/{name}" in dockerignore
        assert f"infra/postgres/{name} /app/{name}" in dockerfile
        assert f"/app/{name}" in compose
        assert f"./postgres/{name}:/{name.replace('_', '-')}:ro" in compose
        assert f"/{name.replace('_', '-')}" in healthcheck
    assert "schema_head_004" not in compose + dockerfile + healthcheck
    assert "schema-head-004" not in compose + healthcheck


def test_head_005_adds_no_column_and_changes_exactly_the_widened_objects() -> None:
    assert (POSTGRES / "schema_head_005_columns.tsv").read_bytes() == (
        POSTGRES / "schema_head_004_columns.tsv"
    ).read_bytes()
    before = _fingerprints(POSTGRES / "schema_head_004_fingerprints.env")
    after = _fingerprints(POSTGRES / "schema_head_005_fingerprints.env")
    assert list(after) == list(before)
    assert {key for key in after if after[key] != before[key]} == (
        WIDENED_FINGERPRINT_KEYS
    )

    def md5(text: str) -> str:
        return hashlib.md5(text.encode("utf-8")).hexdigest()

    assert before["PLACEMENTS_CURRENTNESS_CHECK_MD5"] == md5(CURRENTNESS_CHECK_004)
    assert before["PLACEMENTS_SCOPE_PREDICATE_MD5"] == md5(SCOPE_PREDICATE_004)
    assert after["PLACEMENTS_CURRENTNESS_CHECK_MD5"] == md5(CURRENTNESS_CHECK_005)
    assert after["PLACEMENTS_SCOPE_PREDICATE_MD5"] == md5(SCOPE_PREDICATE_005)
    assert after["PLACEMENTS_SCOPE_INDEX_MD5"] == md5(SCOPE_INDEX_005)
