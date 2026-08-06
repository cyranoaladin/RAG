"""Remédiation revue PR#90 (Cubic P1) : sécurité des migrations
ingestion_control contre une base *déjà peuplée* — pas seulement contre un
volume neuf (déjà couvert par ``test_lot44f_migration_rollback_rehearsal.
py`` et par ``bootstrap_ingestion_control_schema.sh`` lui-même, exercés
dans toutes les autres suites LOT44 via leur fixture ``pg_container``).

Aucune de ces situations n'est survenue en production (jamais déployé,
cf. ADR-0031) — ces tests protègent une future ré-application contre un
volume qui contiendrait déjà des données.
"""
from __future__ import annotations

import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = ENGINE_ROOT / "infra" / "postgres" / "ingestion_control" / "migrations"

PG_IMAGE = "pgvector/pgvector:pg16"
PG_SUPERUSER = "raguser"
PG_SUPERUSER_PASSWORD = "test-password"
PG_DB = "ragdb"

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available"),
]


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


@pytest.fixture
def pg_container() -> Iterator[dict[str, str]]:
    container_name = f"nexus-lot44f-upgrade-paths-{uuid.uuid4().hex[:10]}"
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
        yield {"host": "127.0.0.1", "port": str(port), "dbname": PG_DB}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _superuser_conn(pg_container: dict[str, str]) -> psycopg.Connection:
    return psycopg.connect(
        host=pg_container["host"], port=pg_container["port"], dbname=pg_container["dbname"],
        user=PG_SUPERUSER, password=PG_SUPERUSER_PASSWORD, autocommit=True,
    )


def _apply_migration_file(conn: psycopg.Connection, version: int) -> None:
    matches = list(MIGRATIONS_DIR.glob(f"{version:03d}_*.sql"))
    assert len(matches) == 1, f"expected exactly one migration file for {version}, found {matches}"
    sql = matches[0].read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)


class TestMigration005ClaimedStatusBackfill:
    def test_preexisting_claimed_row_is_backfilled_to_running(
        self, pg_container: dict[str, str]
    ) -> None:
        """Revue PR#90 : une ligne jobs.status='claimed' préexistante (le
        CHECK à 7 valeurs de 004 l'autorisait) ne doit plus jamais faire
        échouer la migration 005 — elle doit être réconciliée à 'running',
        pas laissée bloquer l'application de la contrainte à 6 valeurs."""
        with _superuser_conn(pg_container) as conn:
            for version in (1, 2, 3, 4):
                _apply_migration_file(conn, version)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ingestion_control.ingestion_runs
                        (tenant, collection, niveau, voie, matiere, candidat, audience,
                         visibility, school_year, programme_version, profile_version, trigger)
                    VALUES ('t', 'c', 'terminale', 'generale', 'nsi', 'libre', ARRAY['libre'],
                            'internal', '2026-2027', 'v1', 'v1', 'manual')
                    RETURNING run_id
                    """
                )
                (run_id,) = cur.fetchone()
                cur.execute(
                    "INSERT INTO ingestion_control.jobs (job_id, run_id, job_type, status) "
                    "VALUES (gen_random_uuid(), %s, 'resource_pipeline', 'claimed') "
                    "RETURNING job_id",
                    (run_id,),
                )
                (job_id,) = cur.fetchone()

            # Migration 005 ne doit pas échouer malgré la ligne 'claimed'.
            _apply_migration_file(conn, 5)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status FROM ingestion_control.jobs WHERE job_id = %s", (job_id,)
                )
                (status,) = cur.fetchone()
            assert status == "running"


class TestMigration006BlocksOnNonEmptyTable:
    def test_migration_006_fails_explicitly_on_preexisting_candidate_row(
        self, pg_container: dict[str, str]
    ) -> None:
        """Revue PR#90 : plutôt qu'un payload '{}' inutilisable sur une
        ligne préexistante, la migration doit échouer explicitement — un
        opérateur doit alors backfill/quarantaine délibérément."""
        with _superuser_conn(pg_container) as conn:
            for version in (1, 2, 3, 4, 5):
                _apply_migration_file(conn, version)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO ingestion_control.ingestion_runs
                        (tenant, collection, niveau, voie, matiere, candidat, audience,
                         visibility, school_year, programme_version, profile_version, trigger)
                    VALUES ('t', 'c', 'terminale', 'generale', 'nsi', 'libre', ARRAY['libre'],
                            'internal', '2026-2027', 'v1', 'v1', 'manual')
                    RETURNING run_id
                    """
                )
                (run_id,) = cur.fetchone()
                cur.execute(
                    """
                    INSERT INTO ingestion_control.resources
                        (resource_id, run_id, dedup_key, tenant, collection, niveau, voie,
                         matiere, candidat, audience, visibility, school_year, programme_version)
                    VALUES (gen_random_uuid(), %s, 'd' || repeat('e', 63), 't', 'c', 'terminale',
                            'generale', 'nsi', 'libre', ARRAY['libre'], 'internal', '2026-2027', 'v1')
                    RETURNING resource_id
                    """,
                    (run_id,),
                )
                (resource_id,) = cur.fetchone()
                cur.execute(
                    """
                    INSERT INTO ingestion_control.resource_candidates
                        (candidate_id, resource_id, run_id, dedup_key, source_url, canonical_url,
                         domain, proposed_type_doc, discovered_at)
                    VALUES (gen_random_uuid(), %s, %s, 'd' || repeat('e', 63),
                            'https://eduscol.education.fr/x', 'https://eduscol.education.fr/x',
                            'eduscol.education.fr', 'cours', now())
                    """,
                    (resource_id, run_id),
                )

            with pytest.raises(psycopg.errors.RaiseException, match="MIGRATION_006_PREEXISTING_ROWS"):
                _apply_migration_file(conn, 6)

    def test_migration_006_still_succeeds_on_empty_tables(
        self, pg_container: dict[str, str]
    ) -> None:
        with _superuser_conn(pg_container) as conn:
            for version in (1, 2, 3, 4, 5, 6):
                _apply_migration_file(conn, version)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'ingestion_control' "
                    "AND table_name = 'resource_candidates' AND column_name = 'payload'"
                )
                assert cur.fetchone() is not None
