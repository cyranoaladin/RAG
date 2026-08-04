"""LOT44e : primitives ingestion_control.jobs — PostgreSQL réel.

Périmètre strict : create_job, claim_job, complete_job, record_job_retry,
reap_expired_job_leases (ingestor.ingestion_control.jobs, migration 004).
Même convention Docker jetable que les suites LOT44b/44c/44d.
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.ingestion_control.jobs import (  # noqa: E402
    JobLeaseConflictError,
    claim_job,
    complete_job,
    create_job,
    reap_expired_job_leases,
    record_job_retry,
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
            capture_output=True, check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture(scope="module")
def pg_container() -> Iterator[dict[str, str]]:
    container_name = f"nexus-lot44e-jobs-{uuid.uuid4().hex[:10]}"
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
        check=True, capture_output=True,
    )
    try:
        _wait_pg_isready(port)
        env = os.environ.copy()
        env.update({
            "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD, "PGDATABASE": PG_DB,
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
def app_conn(pg_container: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_app_dsn(pg_container), autocommit=False) as conn:
        yield conn


@pytest.fixture
def clean_db(superuser_conn: psycopg.Connection) -> None:
    with superuser_conn.cursor() as cur:
        cur.execute(
            "TRUNCATE ingestion_control.jobs, ingestion_control.workflow_events, "
            "ingestion_control.artifacts, ingestion_control.resource_candidates, "
            "ingestion_control.resources, ingestion_control.ingestion_runs CASCADE"
        )


def _insert_run(conn: psycopg.Connection) -> uuid.UUID:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.ingestion_runs
                (tenant, collection, niveau, voie, matiere, candidat, audience,
                 visibility, school_year, programme_version, profile_version, trigger)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING run_id
            """,
            (
                VALID_SCOPE["tenant"], VALID_SCOPE["collection"], VALID_SCOPE["niveau"],
                VALID_SCOPE["voie"], VALID_SCOPE["matiere"], VALID_SCOPE["candidat"],
                VALID_SCOPE["audience"], VALID_SCOPE["visibility"], VALID_SCOPE["school_year"],
                VALID_SCOPE["programme_version"], "v1", "manual",
            ),
        )
        row = cur.fetchone()
        assert row is not None
        return row[0]


class TestCreateJob:
    def test_creates_queued_job(self, clean_db: None, app_conn: psycopg.Connection) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()

        with app_conn.cursor() as cur:
            cur.execute("SELECT status, resource_id FROM ingestion_control.jobs WHERE job_id = %s", (job_id,))
            status, resource_id = cur.fetchone()
        assert status == "queued"
        assert resource_id is None

    def test_blank_job_type_is_rejected(self, clean_db: None, app_conn: psycopg.Connection) -> None:
        run_id = _insert_run(app_conn)
        with pytest.raises(ValueError):
            create_job(app_conn, run_id=run_id, job_type="   ")


class TestClaimJob:
    def test_claims_queued_job_and_marks_running(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()

        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()

        assert claim is not None
        assert claim.job_id == job_id
        assert claim.run_id == run_id

        with app_conn.cursor() as cur:
            cur.execute("SELECT status, claimed_by FROM ingestion_control.jobs WHERE job_id = %s", (job_id,))
            status, claimed_by = cur.fetchone()
        assert status == "running"
        assert claimed_by == "worker-1"

    def test_returns_none_when_no_job_available(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        assert claim_job(app_conn, owner="worker-1") is None

    def test_two_concurrent_claims_never_get_the_same_job(
        self, clean_db: None, app_conn: psycopg.Connection, pg_container: dict[str, str]
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()

        conn_a = psycopg.connect(_app_dsn(pg_container), autocommit=False)
        conn_b = psycopg.connect(_app_dsn(pg_container), autocommit=False)
        try:
            claim_a = claim_job(conn_a, owner="worker-a")
            conn_a.commit()
            claim_b = claim_job(conn_b, owner="worker-b")
            conn_b.commit()

            assert claim_a is not None
            assert claim_a.job_id == job_id
            assert claim_b is None
        finally:
            conn_a.close()
            conn_b.close()

    def test_rejects_non_claimable_status(self, clean_db: None, app_conn: psycopg.Connection) -> None:
        with pytest.raises(ValueError):
            claim_job(app_conn, owner="worker-1", eligible_statuses=("succeeded",))


class TestCompleteJob:
    def test_succeeds_when_lease_matches(self, clean_db: None, app_conn: psycopg.Connection) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        complete_job(app_conn, job_id=claim.job_id, lease_token=claim.lease_token, status="succeeded")
        app_conn.commit()

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, lease_token FROM ingestion_control.jobs WHERE job_id = %s",
                (claim.job_id,),
            )
            status, lease_token = cur.fetchone()
        assert status == "succeeded"
        assert lease_token is None

    def test_rejects_completion_with_wrong_lease_token(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        with pytest.raises(JobLeaseConflictError):
            complete_job(app_conn, job_id=claim.job_id, lease_token=uuid.uuid4(), status="succeeded")


class TestRecordJobRetry:
    def test_retry_reschedules_and_requeues(self, clean_db: None, app_conn: psycopg.Connection) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        outcome = record_job_retry(app_conn, job_id=claim.job_id, error="download timeout")
        app_conn.commit()

        assert outcome.exhausted is False
        assert outcome.attempt_count == 1
        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, lease_token FROM ingestion_control.jobs WHERE job_id = %s",
                (claim.job_id,),
            )
            status, lease_token = cur.fetchone()
        assert status == "queued"
        assert lease_token is None

    def test_exhausted_retries_move_to_dead_letter(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()
        with app_conn.cursor() as cur:
            cur.execute("UPDATE ingestion_control.jobs SET max_attempts = 1 WHERE job_id = %s", (job_id,))
        app_conn.commit()

        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        outcome = record_job_retry(app_conn, job_id=claim.job_id, error="fatal error")
        app_conn.commit()

        assert outcome.exhausted is True
        assert outcome.next_attempt_at is None
        with app_conn.cursor() as cur:
            cur.execute("SELECT status FROM ingestion_control.jobs WHERE job_id = %s", (claim.job_id,))
            (status,) = cur.fetchone()
        assert status == "dead_letter"


class TestReapExpiredJobLeases:
    def test_expired_lease_is_released_and_requeued(
        self, clean_db: None, app_conn: psycopg.Connection, superuser_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1", lease_duration_s=1)
        app_conn.commit()
        assert claim is not None

        with superuser_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE job_id = %s",
                (job_id,),
            )

        reaped = reap_expired_job_leases(app_conn)
        app_conn.commit()

        assert len(reaped) == 1
        assert reaped[0].job_id == job_id
        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, lease_token FROM ingestion_control.jobs WHERE job_id = %s",
                (job_id,),
            )
            status, lease_token = cur.fetchone()
        assert status == "queued"
        assert lease_token is None

    def test_active_lease_is_never_touched(self, clean_db: None, app_conn: psycopg.Connection) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1", lease_duration_s=300)
        app_conn.commit()
        assert claim is not None

        reaped = reap_expired_job_leases(app_conn)
        assert reaped == []


class TestForeignKeyToWorkflowEvents:
    def test_workflow_events_job_id_must_reference_existing_job(
        self, clean_db: None, superuser_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(superuser_conn)
        with pytest.raises(psycopg.errors.ForeignKeyViolation):
            with superuser_conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ingestion_control.workflow_events "
                    "(run_id, job_id, event_type, actor) VALUES (%s, %s, 'test', 'test')",
                    (run_id, uuid.uuid4()),
                )
