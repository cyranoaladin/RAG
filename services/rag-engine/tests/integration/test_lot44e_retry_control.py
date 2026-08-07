"""LOT44e (remédiation revue PR#90, passe 2) : ingestion_control.retry —
PostgreSQL réel.

Périmètre strict : record_retry (ingestor.ingestion_control.retry,
migration 002/003), en particulier la garde de bail
``lease_expires_at > clock_timestamp()`` (Cubic P2, revue incrémentale) —
aucun test ne couvrait encore cette primitive avant ce fichier (aucun
appelant réel n'existe non plus dans ce dépôt à ce stade, cf. docstring de
``retry.py``). Même convention Docker jetable que les suites LOT44b/44e/44f.
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
from nexus_contracts.resource_state import ResourceState  # noqa: E402

from ingestor.ingestion_control.claim import (  # noqa: E402
    ResourceLeaseConflictError,
    claim_resource,
)
from ingestor.ingestion_control.provisioning import create_resource  # noqa: E402
from ingestor.ingestion_control.retry import record_retry  # noqa: E402

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
    container_name = f"nexus-lot44e-retry-{uuid.uuid4().hex[:10]}"
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


def _app_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user=ingestion_control_app password={APP_PASSWORD}"
    )


def _superuser_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
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
def second_app_conn(pg_container: dict[str, str]) -> Iterator[psycopg.Connection]:
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


class TestRecordRetry:
    def test_rejects_retry_when_transaction_began_before_expiry_but_runs_after(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        """Preuve directe que ``record_retry`` utilise ``clock_timestamp()``
        et non ``now()`` (Cubic P2, revue incrémentale PR#90) : la
        transaction PostgreSQL de ce test commence (implicitement, à la
        première requête) *avant* l'expiration du bail — si la garde SQL
        utilisait encore ``now()`` (figé à l'heure de début de
        transaction), la comparaison ``now() > lease_expires_at`` resterait
        fausse même après l'expiration réelle, et cette assertion échouerait
        silencieusement (``record_retry`` réussirait à tort). Ce test a été
        vérifié en le faisant échouer délibérément contre une version
        temporairement repassée à ``now()`` avant d'être validé ici."""
        run_id = _insert_run(app_conn)
        resource_id = _insert_resource(app_conn, run_id=run_id)
        app_conn.commit()

        claim = claim_resource(
            app_conn,
            eligible_states=(ResourceState.DISCOVERED,),
            owner="worker-1",
            lease_duration_s=2,
        )
        assert claim is not None
        assert claim.resource_id == resource_id
        # Toujours dans la même transaction (aucun commit) : le bail
        # expirera réellement (horloge murale) avant que cette transaction
        # ne se termine.

        time.sleep(3)  # l'horloge murale dépasse lease_expires_at

        with pytest.raises(ResourceLeaseConflictError):
            record_retry(
                app_conn,
                resource_id=resource_id,
                lease_token=claim.lease_token,
                error="fetch timeout (test)",
            )

    def test_stale_worker_cannot_record_retry_after_lease_reclaimed(
        self,
        clean_db: None,
        app_conn: psycopg.Connection,
        second_app_conn: psycopg.Connection,
    ) -> None:
        """Un second worker qui réclame la ressource après expiration réelle
        du premier bail (commit + nouvelle réclamation) doit être seul
        détenteur : le premier worker, qui tente ``record_retry`` avec son
        ancien ``lease_token``, doit être rejeté sans jamais écraser le
        second bail en cours."""
        run_id = _insert_run(app_conn)
        resource_id = _insert_resource(app_conn, run_id=run_id)
        app_conn.commit()

        first_claim = claim_resource(
            app_conn,
            eligible_states=(ResourceState.DISCOVERED,),
            owner="worker-1",
            lease_duration_s=1,
        )
        assert first_claim is not None
        app_conn.commit()

        time.sleep(2)  # bail du premier worker réellement expiré

        second_claim = claim_resource(
            second_app_conn,
            eligible_states=(ResourceState.DISCOVERED,),
            owner="worker-2",
            lease_duration_s=300,
        )
        assert second_claim is not None
        assert second_claim.resource_id == resource_id
        assert second_claim.lease_token != first_claim.lease_token
        second_app_conn.commit()

        with pytest.raises(ResourceLeaseConflictError):
            record_retry(
                app_conn,
                resource_id=resource_id,
                lease_token=first_claim.lease_token,
                error="stale worker retry attempt (test)",
            )

    def test_active_lease_retry_increments_attempt_count_and_sets_next_attempt(
        self, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        resource_id = _insert_resource(app_conn, run_id=run_id)
        app_conn.commit()

        claim = claim_resource(
            app_conn,
            eligible_states=(ResourceState.DISCOVERED,),
            owner="worker-1",
            lease_duration_s=300,
        )
        assert claim is not None

        outcome = record_retry(
            app_conn,
            resource_id=resource_id,
            lease_token=claim.lease_token,
            error="transient fetch error (test)",
        )
        app_conn.commit()

        assert outcome.resource_id == resource_id
        assert outcome.attempt_count == 1
        assert outcome.exhausted is False
        assert outcome.next_attempt_at is not None

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT claimed_by, lease_token, lease_expires_at, attempt_count "
                "FROM ingestion_control.resources WHERE resource_id = %s",
                (resource_id,),
            )
            claimed_by, lease_token, lease_expires_at, attempt_count = cur.fetchone()
        assert claimed_by is None
        assert lease_token is None
        assert lease_expires_at is None
        assert attempt_count == 1
