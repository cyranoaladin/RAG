"""LOT44b : schéma ingestion_control, migrations, et primitives de
concurrence — tests d'intégration PostgreSQL réels.

Périmètre strict : aucun worker, aucun scheduler, aucun agent, aucun
endpoint. Ces tests exercent exclusivement les quatre primitives
(claim, transition CAS, retry/backoff, lease reaper) contre un vrai
PostgreSQL jetable, avec de vraies connexions concurrentes indépendantes —
jamais une course simulée dans une seule transaction ni un mock.

Convention reprise de tests/integration/test_migrations_autorun.py
(LOT43) : conteneur Docker jetable, nom aléatoire, port libre, `--rm`,
nettoyage `finally`. Marqué `integration`, ignoré si Docker indisponible.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

import sys  # noqa: E402

sys.path.insert(0, str(ENGINE_ROOT / "src"))

from nexus_contracts.resource_state import ResourceState  # noqa: E402

from ingestor.ingestion_control import (  # noqa: E402
    CLAIMABLE_STATES,
    cas_transition,
    claim_resource,
    compute_backoff_seconds,
    reap_expired_leases,
    record_retry,
)
from ingestor.ingestion_control.transitions import (  # noqa: E402
    InvalidTransitionError,
    TransitionConflictError,
)

PG_IMAGE = "pgvector/pgvector:pg16"
PG_SUPERUSER = "raguser"
PG_SUPERUSER_PASSWORD = "test-password"
PG_DB = "ragdb"
APP_PASSWORD = "ingestion-control-app-test-pw"
MIGRATOR_PASSWORD = "ingestion-control-migrator-test-pw"

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available"),
]

VALID_SCOPE = {
    "tenant": "libre_terminale",
    "collection": "rag_nexus_nsi_terminale_specialite",
    "niveau": "terminale",
    "voie": "generale",
    "matiere": "nsi",
    "candidat": "libre",
    "audience": ["libre", "tous"],
    "visibility": "internal",
    "school_year": "2026-2027",
    "programme_version": "BOEN_special_8_2019-07-25",
}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_pg_isready(port: int, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["pg_isready", "-h", "127.0.0.1", "-p", str(port), "-U", PG_SUPERUSER],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    """Conteneur PostgreSQL jetable, dédié à ce module de tests — un seul
    conteneur pour tous les tests du fichier (démarrage coûteux), nettoyage
    des données entre tests via la fixture `clean_db`, pas de conteneur."""
    container_name = f"nexus-lot44b-ingestion-control-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", container_name,
            "-e", f"POSTGRES_USER={PG_SUPERUSER}",
            "-e", f"POSTGRES_PASSWORD={PG_SUPERUSER_PASSWORD}",
            "-e", f"POSTGRES_DB={PG_DB}",
            "-p", f"{port}:5432",
            PG_IMAGE,
        ],
        check=True,
        capture_output=True,
    )
    try:
        _wait_pg_isready(port)
        env = os.environ.copy()
        env.update({
            "PGHOST": "127.0.0.1",
            "PGPORT": str(port),
            "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD,
            "PGDATABASE": PG_DB,
        })

        bootstrap = subprocess.run(
            [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
            capture_output=True, text=True, check=False,
        )
        assert bootstrap.returncode == 0, bootstrap.stderr
        assert "BOOTSTRAP_COMPLETE" in bootstrap.stdout

        provision_env = dict(env)
        provision_env.update({
            "INGESTION_CONTROL_MIGRATOR_PASSWORD": MIGRATOR_PASSWORD,
            "INGESTION_CONTROL_APP_PASSWORD": APP_PASSWORD,
        })
        provision = subprocess.run(
            [str(PROVISION_SCRIPT)], cwd=ENGINE_ROOT, env=provision_env,
            capture_output=True, text=True, check=False,
        )
        assert provision.returncode == 0, provision.stderr
        assert "ROLES_PROVISIONED=1" in provision.stdout

        yield {"host": "127.0.0.1", "port": str(port), "dbname": PG_DB}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _superuser_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )


def _app_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_app password={APP_PASSWORD}"
    )


@pytest.fixture
def superuser_conn(pg_container: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_superuser_dsn(pg_container), autocommit=True) as conn:
        yield conn


@pytest.fixture
def clean_db(superuser_conn: psycopg.Connection) -> None:
    """Vide les tables ingestion_control avant chaque test — un seul
    conteneur partagé, tests indépendants par TRUNCATE, pas par conteneur."""
    with superuser_conn.cursor() as cur:
        cur.execute(
            "TRUNCATE ingestion_control.workflow_events, "
            "ingestion_control.artifacts, ingestion_control.resource_candidates, "
            "ingestion_control.resources, ingestion_control.ingestion_runs CASCADE"
        )


def _app_conn(pg_container: dict[str, str]) -> psycopg.Connection:
    return psycopg.connect(_app_dsn(pg_container), autocommit=False)


def _insert_run(conn: psycopg.Connection, **overrides: object) -> uuid.UUID:
    scope = {**VALID_SCOPE, **overrides}
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.ingestion_runs
                (tenant, collection, niveau, voie, matiere, candidat, audience,
                 visibility, school_year, programme_version, profile_version, trigger)
            VALUES (%(tenant)s, %(collection)s, %(niveau)s, %(voie)s, %(matiere)s,
                    %(candidat)s, %(audience)s, %(visibility)s, %(school_year)s,
                    %(programme_version)s, '1.0', 'manual')
            RETURNING run_id
            """,
            scope,
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id


def _insert_resource(
    conn: psycopg.Connection,
    run_id: uuid.UUID,
    *,
    dedup_key: str | None = None,
    resource_state: str = "DISCOVERED",
    **overrides: object,
) -> uuid.UUID:
    scope = {**VALID_SCOPE, **overrides}
    dedup_key = dedup_key or uuid.uuid4().hex + "0" * 24
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.resources
                (run_id, dedup_key, tenant, collection, niveau, voie, matiere,
                 candidat, audience, visibility, school_year, programme_version,
                 resource_state)
            VALUES (%(run_id)s, %(dedup_key)s, %(tenant)s, %(collection)s, %(niveau)s,
                    %(voie)s, %(matiere)s, %(candidat)s, %(audience)s, %(visibility)s,
                    %(school_year)s, %(programme_version)s, %(resource_state)s)
            RETURNING resource_id
            """,
            {**scope, "run_id": run_id, "dedup_key": dedup_key, "resource_state": resource_state},
        )
        resource_id = cur.fetchone()[0]
    conn.commit()
    return resource_id


# --- 1. Application propre de la migration ---


def test_migration_applies_cleanly_on_fresh_volume(pg_container: dict[str, str]) -> None:
    conn = psycopg.connect(_superuser_dsn(pg_container))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT version, file_name FROM ingestion_control.schema_migrations ORDER BY version"
            )
            rows = cur.fetchall()
        assert [r[0] for r in rows] == [1, 2, 3]
        assert rows[0][1] == "001_ingestion_control_schema.sql"
        assert rows[2][1] == "003_workflow_events.sql"
    finally:
        conn.close()


def test_bootstrap_is_idempotent_on_rerun(pg_container: dict[str, str]) -> None:
    env = os.environ.copy()
    env.update({
        "PGHOST": pg_container["host"], "PGPORT": pg_container["port"],
        "PGUSER": PG_SUPERUSER, "PGPASSWORD": PG_SUPERUSER_PASSWORD,
        "PGDATABASE": pg_container["dbname"],
    })
    result = subprocess.run(
        [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "MIGRATIONS_APPLIED=0" in result.stdout
    assert "BOOTSTRAP_COMPLETE" in result.stdout


# --- 2. Contraintes et index réellement présents dans PostgreSQL ---


def test_expected_tables_constraints_and_indexes_exist(
    pg_container: dict[str, str],
) -> None:
    conn = psycopg.connect(_superuser_dsn(pg_container))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'ingestion_control' ORDER BY table_name"
            )
            tables = {row[0] for row in cur.fetchall()}
        assert tables == {
            "artifacts", "ingestion_runs", "resource_candidates",
            "resources", "schema_migrations", "workflow_events",
        }

        with conn.cursor() as cur:
            cur.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'ingestion_control'"
            )
            indexes = {row[0] for row in cur.fetchall()}
        assert "idx_ingestion_control_resources_claimable" in indexes
        assert "idx_ingestion_control_resources_lease_expiry" in indexes
        assert "idx_ingestion_control_workflow_events_idempotency_key" in indexes
        assert "resources_collection_dedup_key_unique" in indexes
        assert "resource_candidates_resource_run_unique" in indexes

        with conn.cursor() as cur:
            cur.execute(
                "SELECT conname FROM pg_constraint c "
                "JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname = 'ingestion_control' AND conname = 'resources_state_valid'"
            )
            assert cur.fetchone() is not None
    finally:
        conn.close()


# --- 3. Privilèges conformes à D1 ---


def test_app_role_cannot_update_or_delete_workflow_events(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id)

    app_conn = _app_conn(pg_container)
    try:
        with app_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_control.workflow_events (run_id, resource_id, event_type, actor) "
                "VALUES (%s, %s, 'test_event', 'test')",
                (run_id, resource_id),
            )
        app_conn.commit()

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with app_conn.cursor() as cur:
                cur.execute(
                    "UPDATE ingestion_control.workflow_events SET event_type = 'tampered' WHERE run_id = %s",
                    (run_id,),
                )
        app_conn.rollback()

        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with app_conn.cursor() as cur:
                cur.execute("DELETE FROM ingestion_control.workflow_events WHERE run_id = %s", (run_id,))
        app_conn.rollback()
    finally:
        app_conn.close()


def test_app_role_has_no_privileges_on_public_schema(pg_container: dict[str, str]) -> None:
    app_conn = _app_conn(pg_container)
    try:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            with app_conn.cursor() as cur:
                cur.execute("CREATE TABLE public.should_not_be_creatable (id int)")
        app_conn.rollback()
    finally:
        app_conn.close()


# --- 4. Rejet d'un scope incomplet ---


@pytest.mark.parametrize("missing_field", list(VALID_SCOPE))
def test_incomplete_scope_is_rejected_on_ingestion_runs(
    clean_db: None, superuser_conn: psycopg.Connection, missing_field: str
) -> None:
    scope = dict(VALID_SCOPE)
    del scope[missing_field]
    columns = ", ".join(scope) + ", profile_version, trigger"
    placeholders = ", ".join(f"%({k})s" for k in scope) + ", '1.0', 'manual'"
    with pytest.raises(psycopg.errors.NotNullViolation):
        with superuser_conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO ingestion_control.ingestion_runs ({columns}) VALUES ({placeholders})",
                scope,
            )
    superuser_conn.rollback()


def test_blank_scope_values_rejected_by_check_constraints(
    clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_resource(superuser_conn, run_id, tenant="   ")
    superuser_conn.rollback()


def test_invalid_candidat_rejected(clean_db: None, superuser_conn: psycopg.Connection) -> None:
    run_id = _insert_run(superuser_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_resource(superuser_conn, run_id, candidat="not_a_real_value")
    superuser_conn.rollback()


# --- 5. Rejet de PUBLISHED ---


def test_published_state_is_rejected_by_database_constraint(
    clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    with pytest.raises(psycopg.errors.CheckViolation):
        _insert_resource(superuser_conn, run_id, resource_state="PUBLISHED")
    superuser_conn.rollback()


def test_published_is_rejected_as_workflow_event_to_state(
    clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id)
    with pytest.raises(psycopg.errors.CheckViolation):
        with superuser_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_control.workflow_events "
                "(run_id, resource_id, event_type, to_state, actor) "
                "VALUES (%s, %s, 'transition', 'PUBLISHED', 'test')",
                (run_id, resource_id),
            )
    superuser_conn.rollback()


# --- 6. Deux claims concurrents sur la même ressource ---


def test_two_concurrent_claims_never_get_the_same_resource(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id, resource_state="DISCOVERED")

    conn_a = _app_conn(pg_container)
    conn_b = _app_conn(pg_container)
    try:
        claim_a = claim_resource(
            conn_a, eligible_states=(ResourceState.DISCOVERED,), owner="worker-a"
        )
        assert claim_a is not None
        assert claim_a.resource_id == resource_id
        # conn_a n'a pas encore committé : la ligne reste verrouillée.

        claim_b = claim_resource(
            conn_b, eligible_states=(ResourceState.DISCOVERED,), owner="worker-b"
        )
        assert claim_b is None, "SKIP LOCKED doit empêcher un second claim concurrent"

        conn_a.commit()
        conn_b.commit()
    finally:
        conn_a.close()
        conn_b.close()


def test_claim_returns_none_when_nothing_eligible(
    pg_container: dict[str, str], clean_db: None
) -> None:
    conn = _app_conn(pg_container)
    try:
        result = claim_resource(conn, eligible_states=(ResourceState.DISCOVERED,), owner="worker")
        assert result is None
        conn.commit()
    finally:
        conn.close()


# --- 7. Deux transitions CAS concurrentes ---


def test_two_concurrent_cas_transitions_only_one_succeeds(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id, resource_state="DISCOVERED")

    conn_a = _app_conn(pg_container)
    conn_b = _app_conn(pg_container)
    try:
        # conn_a transitionne et NE committe PAS encore — la ligne est
        # verrouillée par son propre UPDATE, conn_b doit attendre puis
        # échouer explicitement une fois conn_a committée (pas un blocage
        # silencieux : psycopg attend la fin de la transaction concurrente,
        # PostgreSQL lui donne alors une version à jour où le CAS échoue).
        result_a = cas_transition(
            conn_a,
            resource_id=resource_id,
            expected_state=ResourceState.DISCOVERED,
            expected_version=0,
            new_state=ResourceState.CANDIDATE,
            actor="worker-a",
            run_id=run_id,
        )
        assert result_a.to_state is ResourceState.CANDIDATE
        conn_a.commit()

        with pytest.raises(TransitionConflictError):
            cas_transition(
                conn_b,
                resource_id=resource_id,
                expected_state=ResourceState.DISCOVERED,
                expected_version=0,
                new_state=ResourceState.CANDIDATE,
                actor="worker-b",
                run_id=run_id,
            )
        conn_b.rollback()
    finally:
        conn_a.close()
        conn_b.close()


def test_cas_transition_rejects_invalid_transition_before_touching_database(
    clean_db: None, superuser_conn: psycopg.Connection, pg_container: dict[str, str]
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id, resource_state="CANDIDATE")

    conn = _app_conn(pg_container)
    try:
        with pytest.raises(InvalidTransitionError):
            cas_transition(
                conn,
                resource_id=resource_id,
                expected_state=ResourceState.CANDIDATE,
                expected_version=0,
                new_state=ResourceState.STAGED,  # raccourci interdit
                actor="worker",
                run_id=run_id,
            )
        conn.rollback()

        # Preuve que rien n'a été touché : l'état est resté CANDIDATE.
        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_state FROM ingestion_control.resources WHERE resource_id = %s",
                (resource_id,),
            )
            assert cur.fetchone()[0] == "CANDIDATE"
    finally:
        conn.close()


# --- 8. Rollback transactionnel en cas d'échec ---


def test_transaction_rollback_leaves_no_partial_state(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id, resource_state="DISCOVERED")

    conn = _app_conn(pg_container)
    try:
        with pytest.raises(TransitionConflictError):
            cas_transition(
                conn,
                resource_id=resource_id,
                expected_state=ResourceState.CANDIDATE,  # état attendu erroné
                expected_version=0,
                new_state=ResourceState.FETCHED,
                actor="worker",
                run_id=run_id,
            )
        conn.rollback()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_state, state_version FROM ingestion_control.resources WHERE resource_id = %s",
                (resource_id,),
            )
            state, version = cur.fetchone()
            assert state == "DISCOVERED"
            assert version == 0

            cur.execute(
                "SELECT count(*) FROM ingestion_control.workflow_events WHERE resource_id = %s",
                (resource_id,),
            )
            assert cur.fetchone()[0] == 0, "aucun événement ne doit survivre à un rollback"
    finally:
        conn.close()


# --- 9. Séparation entre REVIEWED et RETRIEVAL_ELIGIBLE ---


def test_reviewed_and_retrieval_eligible_are_distinct_states_in_database(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id, resource_state="NEEDS_REVIEW")

    conn = _app_conn(pg_container)
    try:
        reviewed = cas_transition(
            conn, resource_id=resource_id, expected_state=ResourceState.NEEDS_REVIEW,
            expected_version=0, new_state=ResourceState.REVIEWED, actor="reconciliation", run_id=run_id,
        )
        conn.commit()
        assert reviewed.to_state is ResourceState.REVIEWED
        assert reviewed.to_state is not ResourceState.RETRIEVAL_ELIGIBLE

        eligible = cas_transition(
            conn, resource_id=resource_id, expected_state=ResourceState.REVIEWED,
            expected_version=reviewed.state_version, new_state=ResourceState.RETRIEVAL_ELIGIBLE,
            actor="reconciliation", run_id=run_id,
        )
        conn.commit()
        assert eligible.to_state is ResourceState.RETRIEVAL_ELIGIBLE

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT event_type, from_state, to_state FROM ingestion_control.workflow_events "
                "WHERE resource_id = %s ORDER BY occurred_at",
                (resource_id,),
            )
            events = cur.fetchall()
        assert events == [
            ("transition", "NEEDS_REVIEW", "REVIEWED"),
            ("transition", "REVIEWED", "RETRIEVAL_ELIGIBLE"),
        ], "les deux transitions doivent rester deux événements distincts, jamais fusionnés"
    finally:
        conn.close()


# --- 10. Deux rattachements candidat-ressource identiques ---


def test_two_identical_concurrent_candidate_attachments_do_not_duplicate(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    dedup_key = "c" * 64

    def _attach_candidate(conn: psycopg.Connection) -> uuid.UUID:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_control.resources
                    (run_id, dedup_key, tenant, collection, niveau, voie, matiere,
                     candidat, audience, visibility, school_year, programme_version)
                VALUES (%(run_id)s, %(dedup_key)s, %(tenant)s, %(collection)s, %(niveau)s,
                        %(voie)s, %(matiere)s, %(candidat)s, %(audience)s, %(visibility)s,
                        %(school_year)s, %(programme_version)s)
                ON CONFLICT (collection, dedup_key) DO NOTHING
                RETURNING resource_id
                """,
                {**VALID_SCOPE, "run_id": run_id, "dedup_key": dedup_key},
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT resource_id FROM ingestion_control.resources "
                    "WHERE collection = %s AND dedup_key = %s",
                    (VALID_SCOPE["collection"], dedup_key),
                )
                row = cur.fetchone()
            resource_id = row[0]

            cur.execute(
                """
                INSERT INTO ingestion_control.resource_candidates
                    (resource_id, run_id, dedup_key, source_url, canonical_url, domain, proposed_type_doc)
                VALUES (%s, %s, %s, 'https://eduscol.example/x', 'https://eduscol.example/x',
                        'eduscol.example', 'programme_officiel')
                ON CONFLICT (resource_id, run_id) DO NOTHING
                """,
                (resource_id, run_id, dedup_key),
            )
        conn.commit()
        return resource_id

    conn_a = _app_conn(pg_container)
    conn_b = _app_conn(pg_container)
    try:
        resource_id_a = _attach_candidate(conn_a)
        resource_id_b = _attach_candidate(conn_b)
        assert resource_id_a == resource_id_b, "les deux rattachements doivent converger vers la même ressource"

        with superuser_conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM ingestion_control.resources WHERE dedup_key = %s", (dedup_key,))
            assert cur.fetchone()[0] == 1
            cur.execute(
                "SELECT count(*) FROM ingestion_control.resource_candidates WHERE resource_id = %s",
                (resource_id_a,),
            )
            assert cur.fetchone()[0] == 1, "aucun doublon de rattachement, malgré deux tentatives concurrentes"
    finally:
        conn_a.close()
        conn_b.close()


# --- 11. idempotency_key : NULL x2, et doublon non nul rejeté ---


def test_two_events_with_null_idempotency_key_do_not_conflict(
    clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id)
    with superuser_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_control.workflow_events (run_id, resource_id, event_type, actor) "
            "VALUES (%s, %s, 'e1', 'test')",
            (run_id, resource_id),
        )
        cur.execute(
            "INSERT INTO ingestion_control.workflow_events (run_id, resource_id, event_type, actor) "
            "VALUES (%s, %s, 'e2', 'test')",
            (run_id, resource_id),
        )
    superuser_conn.commit()
    with superuser_conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ingestion_control.workflow_events WHERE idempotency_key IS NULL"
        )
        assert cur.fetchone()[0] == 2


def test_two_events_with_the_same_idempotency_key_conflict(
    clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id)
    with superuser_conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ingestion_control.workflow_events (run_id, resource_id, event_type, actor, idempotency_key) "
            "VALUES (%s, %s, 'claim', 'test', 'same-key')",
            (run_id, resource_id),
        )
    superuser_conn.commit()

    with pytest.raises(psycopg.errors.UniqueViolation):
        with superuser_conn.cursor() as cur:
            cur.execute(
                "INSERT INTO ingestion_control.workflow_events (run_id, resource_id, event_type, actor, idempotency_key) "
                "VALUES (%s, %s, 'claim', 'test', 'same-key')",
                (run_id, resource_id),
            )
    superuser_conn.rollback()


def test_ordinary_transition_never_receives_an_idempotency_key(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id, resource_state="DISCOVERED")

    conn = _app_conn(pg_container)
    try:
        cas_transition(
            conn, resource_id=resource_id, expected_state=ResourceState.DISCOVERED,
            expected_version=0, new_state=ResourceState.CANDIDATE, actor="worker", run_id=run_id,
        )
        conn.commit()
        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT idempotency_key FROM ingestion_control.workflow_events WHERE resource_id = %s",
                (resource_id,),
            )
            assert cur.fetchone()[0] is None
    finally:
        conn.close()


# --- 12. Lease valide non récupéré / lease expiré récupéré une seule fois ---


def test_valid_lease_is_never_reaped(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id)
    lease_token = uuid.uuid4()
    with superuser_conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_control.resources SET claimed_by = 'worker', lease_token = %s, "
            "lease_expires_at = now() + interval '1 hour' WHERE resource_id = %s",
            (lease_token, resource_id),
        )
    superuser_conn.commit()

    conn = _app_conn(pg_container)
    try:
        reaped = reap_expired_leases(conn)
        conn.commit()
        assert reaped == []

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT lease_token FROM ingestion_control.resources WHERE resource_id = %s", (resource_id,)
            )
            assert cur.fetchone()[0] == lease_token
    finally:
        conn.close()


def test_expired_lease_is_reaped_exactly_once(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id)
    lease_token = uuid.uuid4()
    with superuser_conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_control.resources SET claimed_by = 'worker', lease_token = %s, "
            "lease_expires_at = now() - interval '1 minute', resource_state = 'FETCHED' "
            "WHERE resource_id = %s",
            (lease_token, resource_id),
        )
    superuser_conn.commit()

    conn = _app_conn(pg_container)
    try:
        first = reap_expired_leases(conn)
        conn.commit()
        assert len(first) == 1
        assert first[0].resource_id == resource_id
        assert first[0].previous_lease_token == lease_token

        second = reap_expired_leases(conn)
        conn.commit()
        assert second == [], "un bail déjà libéré ne doit jamais être récupéré une seconde fois"

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT lease_token, resource_state FROM ingestion_control.resources WHERE resource_id = %s",
                (resource_id,),
            )
            token, state = cur.fetchone()
            assert token is None
            assert state == "FETCHED", "le lease reaper ne doit jamais faire progresser resource_state"
    finally:
        conn.close()


def test_two_concurrent_reapers_never_double_process_the_same_lease(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id)
    with superuser_conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_control.resources SET claimed_by = 'worker', lease_token = %s, "
            "lease_expires_at = now() - interval '1 minute' WHERE resource_id = %s",
            (uuid.uuid4(), resource_id),
        )
    superuser_conn.commit()

    conn_a = _app_conn(pg_container)
    conn_b = _app_conn(pg_container)
    try:
        reaped_a = reap_expired_leases(conn_a)
        # conn_a n'a pas committé : la ligne reste verrouillée pour conn_b.
        reaped_b = reap_expired_leases(conn_b)
        conn_a.commit()
        conn_b.commit()

        total = len(reaped_a) + len(reaped_b)
        assert total == 1, "SKIP LOCKED doit empêcher les deux reapers de traiter la même ligne"
    finally:
        conn_a.close()
        conn_b.close()


# --- 13. Retry / backoff déterministe ---


@pytest.mark.parametrize(
    ("attempt", "expected"),
    [(0, 5.0), (1, 10.0), (2, 20.0), (3, 40.0), (10, 300.0)],  # plafonné à 300s
)
def test_compute_backoff_seconds_is_deterministic(attempt: int, expected: float) -> None:
    assert compute_backoff_seconds(attempt) == expected
    # Rejoué : toujours la même valeur pour le même n.
    assert compute_backoff_seconds(attempt) == expected


def test_record_retry_advances_next_attempt_and_releases_lease(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id)
    with superuser_conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_control.resources SET claimed_by = 'worker', lease_token = %s, "
            "lease_expires_at = now() + interval '1 hour' WHERE resource_id = %s",
            (uuid.uuid4(), resource_id),
        )
    superuser_conn.commit()

    conn = _app_conn(pg_container)
    try:
        outcome = record_retry(conn, resource_id=resource_id, error="fetch timed out")
        conn.commit()
        assert outcome.exhausted is False
        assert outcome.attempt_count == 1
        assert outcome.next_attempt_at is not None
        assert outcome.next_attempt_at > datetime.now(UTC) + timedelta(seconds=4)

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT lease_token, last_error FROM ingestion_control.resources WHERE resource_id = %s",
                (resource_id,),
            )
            token, error = cur.fetchone()
            assert token is None
            assert error == "fetch timed out"
    finally:
        conn.close()


def test_record_retry_reports_exhaustion_without_advancing_next_attempt(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id)
    with superuser_conn.cursor() as cur:
        cur.execute(
            "UPDATE ingestion_control.resources SET max_attempts = 1 WHERE resource_id = %s",
            (resource_id,),
        )
    superuser_conn.commit()

    conn = _app_conn(pg_container)
    try:
        outcome = record_retry(conn, resource_id=resource_id, error="permanent failure")
        conn.commit()
        assert outcome.exhausted is True
        assert outcome.next_attempt_at is None
        assert outcome.attempt_count == 1
    finally:
        conn.close()


# --- 14. Revue de clôture : CREATEROLE réellement absent ---


def test_migrator_role_has_no_createrole_privilege(pg_container: dict[str, str]) -> None:
    """CREATEROLE a été retiré du rôle de migration (ADR-0025) : ni lui ni
    le rôle runtime n'en disposent — seule la connexion administrative
    externe utilisée pour le provisionnement en a besoin."""
    conn = psycopg.connect(_superuser_dsn(pg_container))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT rolname, rolcreaterole, rolsuper, rolcreatedb FROM pg_roles "
                "WHERE rolname IN ('ingestion_control_migrator', 'ingestion_control_app') "
                "ORDER BY rolname"
            )
            rows = {row[0]: row[1:] for row in cur.fetchall()}
        assert rows["ingestion_control_app"] == (False, False, False)
        assert rows["ingestion_control_migrator"] == (False, False, False), (
            "le rôle de migration ne doit posséder ni CREATEROLE, ni SUPERUSER, ni CREATEDB"
        )
    finally:
        conn.close()


# --- 15. Revue de clôture : job_id et lease_token restent des identités distinctes ---


def test_job_id_and_lease_token_remain_distinct_identities(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id, resource_state="DISCOVERED")

    conn = _app_conn(pg_container)
    try:
        claim = claim_resource(
            conn, eligible_states=(ResourceState.DISCOVERED,), owner="worker"
        )
        conn.commit()
        assert claim is not None

        explicit_job_id = uuid.uuid4()
        assert explicit_job_id != claim.lease_token, "précondition du test : les deux UUID générés diffèrent"

        cas_transition(
            conn, resource_id=resource_id, expected_state=ResourceState.DISCOVERED,
            expected_version=0, new_state=ResourceState.CANDIDATE, actor="worker",
            run_id=run_id, job_id=explicit_job_id,
        )
        conn.commit()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT job_id FROM ingestion_control.workflow_events "
                "WHERE resource_id = %s AND to_state = 'CANDIDATE'",
                (resource_id,),
            )
            stored_job_id = cur.fetchone()[0]
        assert stored_job_id == explicit_job_id
        assert stored_job_id != claim.lease_token, (
            "job_id ne doit jamais être silencieusement assimilé à lease_token"
        )
    finally:
        conn.close()


def test_job_id_defaults_to_null_never_backfilled_from_lease_token(
    pg_container: dict[str, str], clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    run_id = _insert_run(superuser_conn)
    resource_id = _insert_resource(superuser_conn, run_id, resource_state="DISCOVERED")

    conn = _app_conn(pg_container)
    try:
        claim = claim_resource(
            conn, eligible_states=(ResourceState.DISCOVERED,), owner="worker"
        )
        conn.commit()
        assert claim is not None and claim.lease_token is not None

        # job_id non fourni : doit rester NULL, jamais rempli avec claim.lease_token.
        cas_transition(
            conn, resource_id=resource_id, expected_state=ResourceState.DISCOVERED,
            expected_version=0, new_state=ResourceState.CANDIDATE, actor="worker", run_id=run_id,
        )
        conn.commit()

        with superuser_conn.cursor() as cur:
            cur.execute(
                "SELECT job_id FROM ingestion_control.workflow_events WHERE resource_id = %s",
                (resource_id,),
            )
            assert cur.fetchone()[0] is None
    finally:
        conn.close()


# --- 16. Revue de clôture : portée exacte de UNIQUE(collection, dedup_key) ---


def test_dedup_key_collision_across_different_scope_is_documented_not_fixed(
    clean_db: None, superuser_conn: psycopg.Connection
) -> None:
    """Documente (ADR-0025) le comportement actuel, volontairement non
    élargi : sous la limitation « une valeur par dimension et par
    déploiement », deux tentatives de même (collection, dedup_key) mais de
    tenant différent convergent silencieusement vers la ressource du
    premier écrivain — ce n'est pas une garantie multi-tenant, et ce test
    échouerait si un futur lot élargissait la contrainte sans ADR dédié."""
    run_a = _insert_run(superuser_conn, tenant="libre_terminale")
    run_b = _insert_run(superuser_conn, tenant="aefe_terminale")
    dedup_key = "d" * 64

    def _try_insert(conn: psycopg.Connection, run_id: uuid.UUID, tenant: str) -> uuid.UUID:
        scope = {**VALID_SCOPE, "tenant": tenant}
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO ingestion_control.resources
                    (run_id, dedup_key, tenant, collection, niveau, voie, matiere,
                     candidat, audience, visibility, school_year, programme_version)
                VALUES (%(run_id)s, %(dedup_key)s, %(tenant)s, %(collection)s, %(niveau)s,
                        %(voie)s, %(matiere)s, %(candidat)s, %(audience)s, %(visibility)s,
                        %(school_year)s, %(programme_version)s)
                ON CONFLICT (collection, dedup_key) DO NOTHING
                RETURNING resource_id
                """,
                {**scope, "run_id": run_id, "dedup_key": dedup_key},
            )
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    "SELECT resource_id FROM ingestion_control.resources "
                    "WHERE collection = %s AND dedup_key = %s",
                    (scope["collection"], dedup_key),
                )
                row = cur.fetchone()
        conn.commit()
        return row[0]

    resource_id_a = _try_insert(superuser_conn, run_a, "libre_terminale")
    resource_id_b = _try_insert(superuser_conn, run_b, "aefe_terminale")

    assert resource_id_a == resource_id_b, "comportement actuel : convergence silencieuse vers le premier écrivain"

    with superuser_conn.cursor() as cur:
        cur.execute(
            "SELECT tenant FROM ingestion_control.resources WHERE resource_id = %s", (resource_id_a,)
        )
        assert cur.fetchone()[0] == "libre_terminale", (
            "le scope conservé est celui du premier écrivain — comportement documenté par ADR-0025, "
            "non corrigé dans ce lot (élargir la contrainte créerait un multi-tenant sans ADR dédié)"
        )


# --- 17. Scope obligatoire sur resources (en plus de ingestion_runs) ---


@pytest.mark.parametrize("missing_field", list(VALID_SCOPE))
def test_incomplete_scope_is_rejected_on_resources(
    clean_db: None, superuser_conn: psycopg.Connection, missing_field: str
) -> None:
    run_id = _insert_run(superuser_conn)
    scope = dict(VALID_SCOPE)
    del scope[missing_field]
    columns = ", ".join(scope) + ", run_id, dedup_key"
    placeholders = ", ".join(f"%({k})s" for k in scope) + ", %(run_id)s, %(dedup_key)s"
    with pytest.raises(psycopg.errors.NotNullViolation):
        with superuser_conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO ingestion_control.resources ({columns}) VALUES ({placeholders})",
                {**scope, "run_id": run_id, "dedup_key": "e" * 64},
            )
    superuser_conn.rollback()


def test_scope_dimensions_are_carried_directly_only_on_runs_and_resources(
    pg_container: dict[str, str],
) -> None:
    """Détermine précisément, en interrogeant PostgreSQL directement, quelles
    tables portent le scope en colonnes propres et lesquelles ne l'obtiennent
    que par clé étrangère (resource_id/run_id) — cf. ADR-0025."""
    conn = psycopg.connect(_superuser_dsn(pg_container))
    try:
        scope_dimensions = set(VALID_SCOPE)
        for table, expected in [
            ("ingestion_runs", True),
            ("resources", True),
            ("resource_candidates", False),
            ("artifacts", False),
            ("workflow_events", False),
        ]:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'ingestion_control' AND table_name = %s",
                    (table,),
                )
                columns = {row[0] for row in cur.fetchall()}
            carries_scope = scope_dimensions.issubset(columns)
            assert carries_scope is expected, (
                f"{table}: attendu carries_scope={expected}, colonnes de scope présentes={carries_scope}"
            )
    finally:
        conn.close()


# --- 18. Revue de clôture : claim borné aux états réclamables ---


def test_claim_rejects_terminal_or_forbidden_states() -> None:
    for forbidden in (
        ResourceState.RETRIEVAL_ELIGIBLE,
        ResourceState.REJECTED,
        ResourceState.QUARANTINED,
        ResourceState.DUPLICATE,
        ResourceState.SUPERSEDED,
        ResourceState.DEAD_LETTER,
        ResourceState.CANCELLED,
        ResourceState.FAILED,
    ):
        assert forbidden not in CLAIMABLE_STATES
        with pytest.raises(ValueError, match="non-claimable"):
            # Aucune connexion réelle nécessaire : la validation intervient
            # avant tout accès base (cf. claim_resource).
            claim_resource(
                conn=None,  # type: ignore[arg-type]
                eligible_states=(forbidden,),
                owner="worker",
            )


def test_claimable_states_exclude_only_the_expected_eight_states() -> None:
    excluded = set(ResourceState) - CLAIMABLE_STATES
    assert excluded == {
        ResourceState.RETRIEVAL_ELIGIBLE,
        ResourceState.FAILED,
        ResourceState.DEAD_LETTER,
        ResourceState.CANCELLED,
        ResourceState.REJECTED,
        ResourceState.QUARANTINED,
        ResourceState.DUPLICATE,
        ResourceState.SUPERSEDED,
    }


# --- 19. Détection de dérive de schéma (checksum) ---


def test_bootstrap_detects_registry_checksum_tampering(pg_container: dict[str, str]) -> None:
    conn = psycopg.connect(_superuser_dsn(pg_container), autocommit=True)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT sha256 FROM ingestion_control.schema_migrations WHERE version = 3"
            )
            real_sha256 = cur.fetchone()[0]
            cur.execute(
                "UPDATE ingestion_control.schema_migrations SET sha256 = repeat('0', 64) WHERE version = 3"
            )

        env = os.environ.copy()
        env.update({
            "PGHOST": pg_container["host"], "PGPORT": pg_container["port"],
            "PGUSER": PG_SUPERUSER, "PGPASSWORD": PG_SUPERUSER_PASSWORD,
            "PGDATABASE": pg_container["dbname"],
        })
        result = subprocess.run(
            [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
            capture_output=True, text=True, check=False,
        )
        assert result.returncode != 0
        assert "MIGRATION_CHECKSUM_MISMATCH" in result.stderr
    finally:
        # Restaure le checksum réel, inconditionnellement, pour ne pas
        # polluer les autres tests du module (conteneur Postgres partagé).
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.schema_migrations SET sha256 = %s WHERE version = 3",
                (real_sha256,),
            )
        conn.close()


__all__: list[str] = []
