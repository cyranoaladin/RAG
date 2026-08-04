"""LOT44e : E2E réel — job -> worker -> huit stages -> événements PostgreSQL.

Périmètre strict : ``run_worker_iteration`` (ingestion_worker.runner) sur
PostgreSQL réel, à partir d'un job créé exactement comme ``/ingest/v2``
serait censé le faire (même forme de payload). Réseau et téléchargement
toujours des doublures (``validate_destination``/``safe_fetch`` injectés,
jamais la vraie garde SSRF) ; stockage réel sur disque temporaire
(``tmp_path``, filesystem local, pas de simulation).

Preuves centrales :
- la chaîne complète progresse jusqu'à ``QUALITY_CHECKED`` (jamais
  ``ROUTED``) ;
- **tous** les événements ``workflow_events`` de l'exécution portent le
  **même** ``job_id`` ;
- le retry/backoff fonctionne réellement (échec de téléchargement ->
  ``record_job_retry`` -> nouvelle tentative réussie) ;
- aucun profil de production n'est utilisé : le registre est chargé depuis
  un répertoire temporaire.
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

import httpx
import psycopg
import pytest
import yaml

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

sys.path.insert(0, str(ENGINE_ROOT / "src"))

from ingestor.ingestion_control.jobs import create_job  # noqa: E402
from ingestor.ingestion_worker.runner import WorkerDeps, run_worker_iteration  # noqa: E402
from ingestor.ingestion_worker.storage import (  # noqa: E402
    make_filesystem_artifact_reader,
    make_filesystem_artifact_store,
)
from ingestor.ssrf_guard import SSRFValidationError  # noqa: E402

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


def _profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "profile_version": "v1",
        "enabled": True,
        "scope": VALID_SCOPE,
        "title": "NSI Terminale Spécialité",
        "owner": "equipe-nsi",
        "expected_topics": ["algorithmique"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["eduscol.education.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 10,
        "max_documents_per_run": 20,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.1,
    }
    payload.update(overrides)
    return payload


def _job_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "scope": VALID_SCOPE,
        "dedup_key": "e" * 64,
        "source_url": "https://eduscol.education.fr/nsi/algo",
        "canonical_url": "https://eduscol.education.fr/nsi/algo",
        "domain": "eduscol.education.fr",
        "proposed_type_doc": "cours",
        "profile_version": "v1",
        "license": "CC-BY-SA",
    }
    payload.update(overrides)
    return payload


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
    container_name = f"nexus-lot44e-worker-e2e-{uuid.uuid4().hex[:10]}"
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


@pytest.fixture
def app_conn(pg_container: dict[str, str]) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_app_dsn(pg_container), autocommit=False) as conn:
        yield conn


@pytest.fixture
def clean_db(pg_container: dict[str, str]) -> None:
    dsn = (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
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


def _write_profile(profiles_dir: Path) -> None:
    profiles_dir.mkdir(parents=True, exist_ok=True)
    (profiles_dir / "nsi.yml").write_text(yaml.safe_dump(_profile_payload()), encoding="utf-8")


def _worker_deps(tmp_path: Path, *, safe_fetch, owner: str = "worker-e2e") -> WorkerDeps:
    profiles_dir = tmp_path / "profiles"
    _write_profile(profiles_dir)
    return WorkerDeps(
        owner=owner,
        profiles_dir=profiles_dir,
        artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
        artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
        validate_destination=lambda url: url,
        safe_fetch=safe_fetch,
    )


def _fake_safe_fetch_success(url: str, *, max_bytes: int, **kwargs: object) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/html"},
        content=b"<p>Cours d'algorithmique pour la terminale.</p>",
        request=httpx.Request("GET", url),
    )


class TestWorkerE2E:
    def test_full_chain_reaches_quality_checked_with_consistent_job_id(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="ingest_v2_upload", payload=_job_payload()
        )
        app_conn.commit()

        deps = _worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_success)
        outcome = run_worker_iteration(app_conn, deps=deps)

        assert outcome.worked is True
        assert outcome.status == "succeeded"
        assert outcome.job_id == job_id
        assert outcome.error is None

        with app_conn.cursor() as cur:
            cur.execute("SELECT status FROM ingestion_control.jobs WHERE job_id = %s", (job_id,))
            (status,) = cur.fetchone()
        assert status == "succeeded"

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT resource_state FROM ingestion_control.resources WHERE run_id = %s",
                (run_id,),
            )
            (resource_state,) = cur.fetchone()
        assert resource_state == "QUALITY_CHECKED"

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT job_id, event_type, to_state FROM ingestion_control.workflow_events "
                "WHERE run_id = %s ORDER BY occurred_at",
                (run_id,),
            )
            rows = cur.fetchall()

        assert len(rows) >= 6, "attendu au moins 6 transitions (Scout..QualityAgent, Fetcher=2)"
        job_ids_seen = {row[0] for row in rows}
        assert job_ids_seen == {job_id}, "tous les événements doivent porter le même job_id"
        to_states = [row[2] for row in rows]
        assert "ROUTED" not in to_states
        assert to_states[-1] == "QUALITY_CHECKED"

    def test_no_job_available_returns_worked_false(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        deps = _worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_success)
        outcome = run_worker_iteration(app_conn, deps=deps)
        assert outcome.worked is False
        assert outcome.job_id is None

    def test_blocked_url_causes_retry_not_a_crash(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="ingest_v2_upload", payload=_job_payload()
        )
        app_conn.commit()

        def blocking_validate_destination(url: str) -> str:
            raise SSRFValidationError(f"blocked: {url}")

        profiles_dir = tmp_path / "profiles"
        _write_profile(profiles_dir)
        deps = WorkerDeps(
            owner="worker-e2e",
            profiles_dir=profiles_dir,
            artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
            artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
            validate_destination=blocking_validate_destination,
            safe_fetch=_fake_safe_fetch_success,
        )

        outcome = run_worker_iteration(app_conn, deps=deps)

        assert outcome.worked is True
        assert outcome.status == "retried"
        assert outcome.job_id == job_id
        assert "blocked" in (outcome.error or "")

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, attempt_count, lease_token FROM ingestion_control.jobs "
                "WHERE job_id = %s",
                (job_id,),
            )
            status, attempt_count, lease_token = cur.fetchone()
        assert status == "queued"
        assert attempt_count == 1
        assert lease_token is None

    def test_retry_then_success_on_second_iteration(
        self, tmp_path: Path, clean_db: None, app_conn: psycopg.Connection
    ) -> None:
        """Retry/backoff réel : première itération échoue (téléchargement
        qui lève), seconde itération (après recalage manuel de
        next_attempt_at, pour ne pas dépendre du délai réel) réussit."""
        run_id = _insert_run(app_conn)
        job_id = create_job(
            app_conn, run_id=run_id, job_type="ingest_v2_upload", payload=_job_payload()
        )
        app_conn.commit()

        def failing_safe_fetch(url: str, *, max_bytes: int, **kwargs: object) -> httpx.Response:
            raise RuntimeError("transient network failure")

        profiles_dir = tmp_path / "profiles"
        _write_profile(profiles_dir)
        failing_deps = WorkerDeps(
            owner="worker-e2e", profiles_dir=profiles_dir,
            artifact_store=make_filesystem_artifact_store(tmp_path / "artifacts"),
            artifact_reader=make_filesystem_artifact_reader(tmp_path / "artifacts"),
            validate_destination=lambda url: url,
            safe_fetch=failing_safe_fetch,
        )

        first_outcome = run_worker_iteration(app_conn, deps=failing_deps)
        assert first_outcome.status == "retried"

        with app_conn.cursor() as cur:
            cur.execute(
                "UPDATE ingestion_control.jobs SET next_attempt_at = now() WHERE job_id = %s",
                (job_id,),
            )
        app_conn.commit()

        succeeding_deps = _worker_deps(tmp_path, safe_fetch=_fake_safe_fetch_success)
        second_outcome = run_worker_iteration(app_conn, deps=succeeding_deps)

        assert second_outcome.status == "succeeded"
        assert second_outcome.job_id == job_id

        with app_conn.cursor() as cur:
            cur.execute(
                "SELECT status, attempt_count FROM ingestion_control.jobs WHERE job_id = %s",
                (job_id,),
            )
            status, attempt_count = cur.fetchone()
        assert status == "succeeded"
        assert attempt_count == 1
