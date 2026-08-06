"""LOT44e : primitives ingestion_control.jobs — PostgreSQL réel.

Périmètre strict : create_job, claim_job, complete_job, record_job_retry,
reap_expired_job_leases (ingestor.ingestion_control.jobs, migration 004).
Même convention Docker jetable que les suites LOT44b/44c/44d.
"""
from __future__ import annotations

import os
import secrets
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

from nexus_contracts.ingestion import ResourceScope  # noqa: E402

from ingestor.ingestion_control.jobs import (  # noqa: E402
    JobLeaseConflictError,
    claim_job,
    complete_job,
    create_job,
    find_or_create_job,
    reap_expired_job_leases,
    record_job_retry,
    set_job_resource_id,
)
from ingestor.ingestion_control.provisioning import create_resource  # noqa: E402

PG_IMAGE = "pgvector/pgvector:pg16"
PG_SUPERUSER = "raguser"
PG_SUPERUSER_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
PG_DB = "ragdb"
APP_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
MIGRATOR_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique

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


def _insert_resource(conn: psycopg.Connection, *, run_id: uuid.UUID) -> uuid.UUID:
    return create_resource(
        conn,
        run_id=run_id,
        dedup_key=f"dedup-{uuid.uuid4().hex}",
        scope=ResourceScope.model_validate(VALID_SCOPE),
    )


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


class TestFindOrCreateJob:
    """Revue PR#90 : idempotence réellement atomique sous concurrence —
    ``find_active_job_by_dedup_key`` suivi d'un ``create_job`` séparé
    laissait une fenêtre de course (SELECT non verrouillé, deux
    connexions concurrentes voient chacune "aucun doublon" et créent
    chacune un job)."""

    def test_first_call_creates_second_call_finds(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        dedup_key = "a" * 64

        job_id_1, created_1 = find_or_create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", dedup_key=dedup_key
        )
        app_conn.commit()
        assert created_1 is True

        job_id_2, created_2 = find_or_create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", dedup_key=dedup_key
        )
        app_conn.commit()
        assert created_2 is False
        assert job_id_2 == job_id_1

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingestion_control.jobs WHERE payload->>'dedup_key' = %s",
                (dedup_key,),
            )
            (count,) = cur.fetchone()
        assert count == 1

    def test_terminal_job_does_not_block_a_new_submission(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        dedup_key = "b" * 64

        job_id_1, created_1 = find_or_create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", dedup_key=dedup_key
        )
        app_conn.commit()
        assert created_1 is True

        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None and claim.job_id == job_id_1
        complete_job(app_conn, job_id=job_id_1, lease_token=claim.lease_token, status="succeeded")
        app_conn.commit()

        job_id_2, created_2 = find_or_create_job(
            app_conn, run_id=run_id, job_type="resource_pipeline", dedup_key=dedup_key
        )
        app_conn.commit()
        assert created_2 is True
        assert job_id_2 != job_id_1

    def test_concurrent_submissions_with_same_dedup_key_create_exactly_one_job(
        self, clean_db: None, app_conn: psycopg.Connection, pg_container: dict[str, str]
    ) -> None:
        """Preuve réelle sous concurrence : deux connexions PostgreSQL
        distinctes, deux threads, un seul ``dedup_key`` — jamais deux jobs
        actifs, quel que soit l'entrelacement réel des deux transactions."""
        import threading

        run_id = _insert_run(app_conn)
        app_conn.commit()
        dedup_key = "c" * 64

        results: list[tuple[uuid.UUID, bool]] = []
        errors: list[BaseException] = []
        start_barrier = threading.Barrier(2)

        def _attempt() -> None:
            conn = psycopg.connect(_app_dsn(pg_container), autocommit=False)
            try:
                start_barrier.wait(timeout=5)
                job_id, created = find_or_create_job(
                    conn, run_id=run_id, job_type="resource_pipeline", dedup_key=dedup_key
                )
                conn.commit()
                results.append((job_id, created))
            except BaseException as exc:  # noqa: BLE001 - capturé pour l'assertion du thread principal
                errors.append(exc)
            finally:
                conn.close()

        threads = [threading.Thread(target=_attempt) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert not errors, f"unexpected errors in concurrent threads: {errors}"
        assert len(results) == 2
        job_ids = {job_id for job_id, _created in results}
        created_flags = sorted(created for _job_id, created in results)
        assert len(job_ids) == 1, "les deux tentatives concurrentes doivent converger sur le même job"
        assert created_flags == [False, True], "exactement une tentative doit avoir créé le job"

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM ingestion_control.jobs WHERE payload->>'dedup_key' = %s",
                (dedup_key,),
            )
            (count,) = cur.fetchone()
        assert count == 1


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

    def test_rejects_non_positive_lease_duration(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        """Revue PR#90 : ``lease_duration_s <= 0`` créerait un bail déjà
        expiré au moment même de sa création, cassant la garantie de
        non-double-claim (n'importe quel autre appelant le verrait
        immédiatement éligible à un nouveau claim)."""
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()

        with pytest.raises(ValueError):
            claim_job(app_conn, owner="worker-1", lease_duration_s=0)
        with pytest.raises(ValueError):
            claim_job(app_conn, owner="worker-1", lease_duration_s=-5)

    def test_job_types_filter_leaves_other_types_available(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        """Revue PR#90 (Cubic P2) : un worker qui ne sait traiter qu'un
        sous-ensemble de types (``job_types=("resource_pipeline",)``, cf.
        ``ingestion_worker.runner.SUPPORTED_JOB_TYPES``) ne doit jamais
        réclamer un job d'un autre type — celui-ci doit rester disponible
        pour son propre consommateur."""
        run_id = _insert_run(app_conn)
        other_job_id = create_job(app_conn, run_id=run_id, job_type="planner_run")
        app_conn.commit()

        claim = claim_job(app_conn, owner="worker-1", job_types=("resource_pipeline",))
        assert claim is None

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM ingestion_control.jobs WHERE job_id = %s", (other_job_id,)
            )
            (status,) = cur.fetchone()
        assert status == "queued", "job of another type must remain untouched and claimable"

    def test_job_types_filter_still_claims_matching_type(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(app_conn, run_id=run_id, job_type="resource_pipeline")
        app_conn.commit()

        claim = claim_job(app_conn, owner="worker-1", job_types=("resource_pipeline",))
        assert claim is not None
        assert claim.job_id == job_id

    def test_job_types_rejects_empty_tuple(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        with pytest.raises(ValueError):
            claim_job(app_conn, owner="worker-1", job_types=())


class TestSetJobResourceId:
    """Revue PR#90 : ``set_job_resource_id`` exige désormais un
    ``lease_token`` valide et n'écrase jamais un rattachement existant vers
    une autre ressource — avant ce correctif, l'écriture était
    inconditionnelle (aucune vérification de bail ni de valeur actuelle)."""

    def test_attaches_resource_id_when_lease_valid(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="resource_pipeline")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        resource_id = _insert_resource(app_conn, run_id=run_id)
        app_conn.commit()
        set_job_resource_id(
            app_conn, job_id=claim.job_id, resource_id=resource_id, lease_token=claim.lease_token
        )
        app_conn.commit()

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_id FROM ingestion_control.jobs WHERE job_id = %s", (claim.job_id,)
            )
            (stored,) = cur.fetchone()
        assert stored == resource_id

    def test_idempotent_rewrite_of_same_resource_id_succeeds(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="resource_pipeline")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        resource_id = _insert_resource(app_conn, run_id=run_id)
        app_conn.commit()
        set_job_resource_id(
            app_conn, job_id=claim.job_id, resource_id=resource_id, lease_token=claim.lease_token
        )
        set_job_resource_id(
            app_conn, job_id=claim.job_id, resource_id=resource_id, lease_token=claim.lease_token
        )
        app_conn.commit()

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_id FROM ingestion_control.jobs WHERE job_id = %s", (claim.job_id,)
            )
            (stored,) = cur.fetchone()
        assert stored == resource_id

    def test_rejects_overwrite_with_a_different_resource_id(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="resource_pipeline")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        first_resource_id = _insert_resource(app_conn, run_id=run_id)
        app_conn.commit()
        set_job_resource_id(
            app_conn, job_id=claim.job_id, resource_id=first_resource_id,
            lease_token=claim.lease_token,
        )
        app_conn.commit()

        with pytest.raises(JobLeaseConflictError):
            set_job_resource_id(
                app_conn, job_id=claim.job_id, resource_id=uuid.uuid4(),
                lease_token=claim.lease_token,
            )

    def test_rejects_wrong_lease_token(self, clean_db: None, app_conn: psycopg.Connection) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="resource_pipeline")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        with pytest.raises(JobLeaseConflictError):
            set_job_resource_id(
                app_conn, job_id=claim.job_id, resource_id=uuid.uuid4(), lease_token=uuid.uuid4()
            )

    def test_rejects_after_lease_expired(
        self, clean_db: None, app_conn: psycopg.Connection, superuser_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="resource_pipeline")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        with superuser_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE job_id = %s",
                (claim.job_id,),
            )
        superuser_conn.commit()

        with pytest.raises(JobLeaseConflictError):
            set_job_resource_id(
                app_conn, job_id=claim.job_id, resource_id=uuid.uuid4(),
                lease_token=claim.lease_token,
            )


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

    def test_rejects_completion_after_lease_expired_even_without_reclaim(
        self, clean_db: None, app_conn: psycopg.Connection, superuser_conn: psycopg.Connection
    ) -> None:
        """Revue PR#90 : sémantique de bail stricte — un ``lease_token`` qui
        correspond encore ne suffit plus une fois ``lease_expires_at``
        dépassé, même si personne d'autre n'a encore réclamé le job (le
        reaper n'est pas encore passé). Distinct du test ci-dessus
        (mauvais token) et de ``test_stale_worker_cannot_complete_after_
        lease_reclaimed`` (token effacé par une reprise réelle) : ici le
        token en base est toujours exactement celui du worker, seule
        l'expiration est en cause."""
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        with superuser_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE job_id = %s",
                (claim.job_id,),
            )
        superuser_conn.commit()

        with pytest.raises(JobLeaseConflictError):
            complete_job(
                app_conn, job_id=claim.job_id, lease_token=claim.lease_token, status="succeeded"
            )

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, lease_token FROM ingestion_control.jobs WHERE job_id = %s",
                (claim.job_id,),
            )
            status, lease_token = cur.fetchone()
        assert status == "running"
        assert lease_token == claim.lease_token

    def test_stale_worker_cannot_complete_after_lease_reclaimed(
        self, clean_db: None, app_conn: psycopg.Connection, superuser_conn: psycopg.Connection
    ) -> None:
        """Même scénario que ci-dessus, mais via une vraie reprise par un
        second worker (reaper + reclaim), pas un lease_token arbitraire —
        preuve que A ne peut jamais terminer le job de B."""
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()

        claim_a = claim_job(app_conn, owner="worker-a")
        app_conn.commit()
        assert claim_a is not None

        with superuser_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE job_id = %s",
                (claim_a.job_id,),
            )
        assert len(reap_expired_job_leases(app_conn)) == 1
        app_conn.commit()

        claim_b = claim_job(app_conn, owner="worker-b")
        app_conn.commit()
        assert claim_b is not None

        with pytest.raises(JobLeaseConflictError):
            complete_job(
                app_conn, job_id=claim_a.job_id, lease_token=claim_a.lease_token, status="succeeded"
            )

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, claimed_by FROM ingestion_control.jobs WHERE job_id = %s",
                (claim_b.job_id,),
            )
            status, claimed_by = cur.fetchone()
        assert status == "running"
        assert claimed_by == "worker-b"


class TestRecordJobRetry:
    def test_retry_reschedules_and_requeues(self, clean_db: None, app_conn: psycopg.Connection) -> None:
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        outcome = record_job_retry(
            app_conn, job_id=claim.job_id, lease_token=claim.lease_token, error="download timeout"
        )
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

        outcome = record_job_retry(
            app_conn, job_id=claim.job_id, lease_token=claim.lease_token, error="fatal error"
        )
        app_conn.commit()

        assert outcome.exhausted is True
        assert outcome.next_attempt_at is None
        with app_conn.cursor() as cur:
            cur.execute("SELECT status FROM ingestion_control.jobs WHERE job_id = %s", (claim.job_id,))
            (status,) = cur.fetchone()
        assert status == "dead_letter"

    def test_rejects_retry_after_lease_expired_even_without_reclaim(
        self, clean_db: None, app_conn: psycopg.Connection, superuser_conn: psycopg.Connection
    ) -> None:
        """Revue PR#90 : même sémantique stricte que ``TestCompleteJob::
        test_rejects_completion_after_lease_expired_even_without_reclaim`` —
        le lease_token en base est toujours celui du worker (personne ne l'a
        encore réclamé), seule l'expiration est en cause."""
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()
        claim = claim_job(app_conn, owner="worker-1")
        app_conn.commit()
        assert claim is not None

        with superuser_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE job_id = %s",
                (claim.job_id,),
            )
        superuser_conn.commit()

        with pytest.raises(JobLeaseConflictError):
            record_job_retry(
                app_conn, job_id=claim.job_id, lease_token=claim.lease_token, error="too slow"
            )

    def test_stale_worker_cannot_record_retry_after_lease_reclaimed(
        self, clean_db: None, app_conn: psycopg.Connection, superuser_conn: psycopg.Connection
    ) -> None:
        """Scénario de concurrence explicite (contrainte LOT44e) : worker A
        réclame, son bail expire, le reaper le libère, worker B réclame le
        même job — A ne doit alors plus pouvoir planifier de retry avec son
        ancien lease_token, et le job de B ne doit pas être perturbé."""
        run_id = _insert_run(app_conn)
        create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()

        claim_a = claim_job(app_conn, owner="worker-a")
        app_conn.commit()
        assert claim_a is not None

        with superuser_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE job_id = %s",
                (claim_a.job_id,),
            )
        reaped = reap_expired_job_leases(app_conn)
        app_conn.commit()
        assert len(reaped) == 1

        claim_b = claim_job(app_conn, owner="worker-b")
        app_conn.commit()
        assert claim_b is not None
        assert claim_b.job_id == claim_a.job_id
        assert claim_b.lease_token != claim_a.lease_token

        with pytest.raises(JobLeaseConflictError):
            record_job_retry(
                app_conn, job_id=claim_a.job_id, lease_token=claim_a.lease_token,
                error="worker A was stale",
            )

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, claimed_by, lease_token FROM ingestion_control.jobs WHERE job_id = %s",
                (claim_b.job_id,),
            )
            status, claimed_by, lease_token = cur.fetchone()
        assert status == "running"
        assert claimed_by == "worker-b"
        assert lease_token == claim_b.lease_token


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


class TestWorkerCliReapsExpiredLeasesOnEachIteration:
    """Remédiation revue PR#90 (Codex) : avant ce correctif,
    ``reap_expired_job_leases``/``reap_expired_leases`` n'étaient invoquées
    par aucun code non-test — un conteneur worker qui s'arrête juste après
    ``claim_job()`` (avant complétion) laissait le job bloqué indéfiniment,
    y compris après redémarrage du conteneur, car ``run_worker_iteration``
    ne réclame que ``status='queued'``, jamais un ``'running'`` au bail
    expiré. Teste directement ``ingestion_worker.cli._reap_expired_leases``
    (la fonction réellement appelée dans la boucle de ``main()``, cf.
    ``cli.py``), pas seulement la primitive ``reap_expired_job_leases``
    elle-même (déjà couverte ci-dessus)."""

    def test_reaps_a_job_left_stuck_by_a_crashed_container(
        self, clean_db: None, app_conn: psycopg.Connection, superuser_conn: psycopg.Connection
    ) -> None:
        from ingestor.ingestion_worker import cli as worker_cli

        run_id = _insert_run(app_conn)
        job_id = create_job(app_conn, run_id=run_id, job_type="ingest_v2_upload")
        app_conn.commit()

        # Simule un conteneur A qui réclame puis s'arrête (crash) avant
        # complétion — jamais de complete_job()/record_job_retry() appelé.
        claim = claim_job(app_conn, owner="worker-A-before-crash", lease_duration_s=1)
        app_conn.commit()
        assert claim is not None

        with superuser_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET lease_expires_at = now() - interval '1 second' "
                "WHERE job_id = %s",
                (job_id,),
            )
        superuser_conn.commit()

        # "Redémarrage du conteneur" : exactement l'appel fait par
        # main() au début de chaque itération de sa boucle.
        worker_cli._reap_expired_leases(app_conn)

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, lease_token, claimed_by FROM ingestion_control.jobs "
                "WHERE job_id = %s",
                (job_id,),
            )
            status, lease_token, claimed_by = cur.fetchone()
        assert status == "queued"
        assert lease_token is None
        assert claimed_by is None

        # Le job redevient réellement réclamable par un nouveau worker.
        new_claim = claim_job(app_conn, owner="worker-B-after-restart")
        assert new_claim is not None
        assert new_claim.job_id == job_id


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
