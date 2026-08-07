"""LOT44f (remédiation revue PR#90, passe 2, item E) : runner officiel de
rollback ``infra/scripts/rollback_ingestion_control_schema.sh`` — PostgreSQL
réel.

Périmètre strict : le runner shell lui-même (quiescence, transaction
unique, ordre de verrouillage canonique, garde de données, DROP/ALTER,
mise à jour de schema_migrations, commit uniquement si tout réussit) — pas
la correction SQL des fichiers ``.down.sql`` eux-mêmes, déjà couverte par
``test_lot44f_migration_rollback_rehearsal.py``.
"""
from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
ROLLBACK_SCRIPT = INFRA_ROOT / "scripts" / "rollback_ingestion_control_schema.sh"
MIGRATIONS_DIR = INFRA_ROOT / "postgres" / "ingestion_control" / "migrations"

sys.path.insert(0, str(ENGINE_ROOT / "src"))

from nexus_contracts.ingestion import ResourceScope  # noqa: E402
from nexus_contracts.resource_state import ResourceState  # noqa: E402

from ingestor.ingestion_control.claim import claim_resource  # noqa: E402
from ingestor.ingestion_control.jobs import claim_job, create_job  # noqa: E402
from ingestor.ingestion_control.provisioning import create_resource  # noqa: E402

PG_IMAGE = "pgvector/pgvector:pg16"
PG_SUPERUSER = "raguser"
PG_SUPERUSER_PASSWORD = secrets.token_urlsafe(24)  # revue PR#90 : jamais un litteral statique
PG_DB = "ragdb"

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available"),
]

_MIGRATION_VERSIONS = sorted(
    int(p.name.split("_", 1)[0])
    for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")
)
_HEAD = _MIGRATION_VERSIONS[-1]

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


@pytest.fixture
def pg_container() -> Iterator[dict[str, str]]:
    """Non ``scope='module'`` volontairement : ces tests mutent le schéma
    de façon destructive — un conteneur dédié par test."""
    container_name = f"nexus-lot44f-rollback-runner-{uuid.uuid4().hex[:10]}"
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
        assert f"SCHEMA_HEAD={_HEAD}" in bootstrap.stdout

        yield {"host": "127.0.0.1", "port": str(port), "dbname": PG_DB}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _env(pg_container: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "PGHOST": pg_container["host"], "PGPORT": pg_container["port"],
        "PGUSER": PG_SUPERUSER, "PGPASSWORD": PG_SUPERUSER_PASSWORD,
        "PGDATABASE": pg_container["dbname"],
    })
    return env


def _run_rollback(
    pg_container: dict[str, str], *, target_version: int
) -> subprocess.CompletedProcess[str]:
    env = _env(pg_container)
    env["TARGET_VERSION"] = str(target_version)
    return subprocess.run(
        [str(ROLLBACK_SCRIPT)], cwd=ENGINE_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )


def _superuser_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )


def _schema_head(pg_container: dict[str, str]) -> int:
    with psycopg.connect(_superuser_dsn(pg_container)) as conn, conn.cursor() as cur:
        cur.execute("SELECT COALESCE(max(version), 0) FROM ingestion_control.schema_migrations")
        (head,) = cur.fetchone()
    return head


class TestRollbackRunnerRange:
    def test_full_rollback_via_runner_then_full_reapply(
        self, pg_container: dict[str, str]
    ) -> None:
        result = _run_rollback(pg_container, target_version=0)
        assert result.returncode == 0, result.stderr
        assert "ROLLBACK_COMPLETE" in result.stdout
        assert "SCHEMA_HEAD=0" in result.stdout
        assert _schema_head(pg_container) == 0

        with psycopg.connect(_superuser_dsn(pg_container)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'ingestion_control' AND table_name != 'schema_migrations'"
            )
            remaining = cur.fetchall()
        assert remaining == []

        reapply = subprocess.run(
            [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=_env(pg_container),
            capture_output=True, text=True, check=False,
        )
        assert reapply.returncode == 0, reapply.stderr
        assert f"SCHEMA_HEAD={_HEAD}" in reapply.stdout

    def test_partial_rollback_via_runner_undoes_only_the_requested_range(
        self, pg_container: dict[str, str]
    ) -> None:
        # Cible fixe (jamais _HEAD - 2) : ce test vérifie le contenu précis
        # des migrations 005/006 (colonne artifacts.payload, contrainte
        # jobs_status_valid) — un ancrage relatif à _HEAD casserait
        # silencieusement à chaque migration ajoutée au-dessus de 006 (LOT41A/
        # LOT42, migrations 007/008), en annulant des tables sans rapport
        # plutôt que 005/006 eux-mêmes.
        target = 4  # annule 006 et 005 seulement, quel que soit _HEAD actuel
        result = _run_rollback(pg_container, target_version=target)
        assert result.returncode == 0, result.stderr
        assert f"SCHEMA_HEAD={target}" in result.stdout
        assert _schema_head(pg_container) == target

        with psycopg.connect(_superuser_dsn(pg_container)) as conn, conn.cursor() as cur:
            # 006 défait : la colonne payload doit avoir disparu.
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'ingestion_control' AND table_name = 'artifacts' "
                "AND column_name = 'payload'"
            )
            assert cur.fetchall() == []

            # 005 défait : jobs_status_valid doit à nouveau autoriser 'claimed'.
            cur.execute(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conname = 'jobs_status_valid' "
                "AND conrelid = 'ingestion_control.jobs'::regclass"
            )
            (constraint_def,) = cur.fetchone()
            assert "claimed" in constraint_def

            # 004 non défait : la table jobs doit toujours exister.
            cur.execute("SELECT to_regclass('ingestion_control.jobs')")
            (jobs_regclass,) = cur.fetchone()
            assert jobs_regclass is not None

    def test_rejects_target_version_not_below_current_head(
        self, pg_container: dict[str, str]
    ) -> None:
        result = _run_rollback(pg_container, target_version=_HEAD)
        assert result.returncode != 0
        assert "must be strictly less than the current schema head" in result.stderr
        assert _schema_head(pg_container) == _HEAD


class TestRollbackRunnerQuiescence:
    def test_refuses_when_a_job_is_running(self, pg_container: dict[str, str]) -> None:
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            run_id = _insert_run(conn)
            create_job(conn, run_id=run_id, job_type="ingest_v2_upload")
            conn.commit()
            claim = claim_job(conn, owner="worker-1")
            conn.commit()
            assert claim is not None  # status now 'running'

        result = _run_rollback(pg_container, target_version=_HEAD - 1)
        assert result.returncode != 0
        assert "INGESTION_NOT_QUIESCENT" in result.stderr
        assert _schema_head(pg_container) == _HEAD, "schema must be untouched when refused"

    def test_refuses_when_a_resource_holds_an_active_lease(
        self, pg_container: dict[str, str]
    ) -> None:
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            run_id = _insert_run(conn)
            create_resource(
                conn, run_id=run_id, dedup_key=f"dedup-{uuid.uuid4().hex}",
                scope=ResourceScope.model_validate(VALID_SCOPE),
            )
            conn.commit()
            claim = claim_resource(
                conn, eligible_states=(ResourceState.DISCOVERED,), owner="worker-1",
                lease_duration_s=300,
            )
            conn.commit()
            assert claim is not None

        result = _run_rollback(pg_container, target_version=_HEAD - 1)
        assert result.returncode != 0
        assert "INGESTION_NOT_QUIESCENT" in result.stderr
        assert _schema_head(pg_container) == _HEAD, "schema must be untouched when refused"

    def test_proceeds_once_the_lease_has_expired(self, pg_container: dict[str, str]) -> None:
        """Une ressource dont le bail est réellement expiré (pas seulement
        libéré) ne doit plus bloquer le rollback — la quiescence porte sur
        un bail *actif*, jamais sur l'existence passée d'un bail."""
        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            run_id = _insert_run(conn)
            create_resource(
                conn, run_id=run_id, dedup_key=f"dedup-{uuid.uuid4().hex}",
                scope=ResourceScope.model_validate(VALID_SCOPE),
            )
            conn.commit()
            claim = claim_resource(
                conn, eligible_states=(ResourceState.DISCOVERED,), owner="worker-1",
                lease_duration_s=1,
            )
            conn.commit()
            assert claim is not None

        time.sleep(2)

        result = _run_rollback(pg_container, target_version=_HEAD - 1)
        assert result.returncode == 0, result.stderr
        assert _schema_head(pg_container) == _HEAD - 1


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


class TestRollbackRunnerConcurrentWriteInterference:
    def test_concurrent_insert_blocks_until_rollback_transaction_ends(
        self, pg_container: dict[str, str]
    ) -> None:
        """Preuve directe que le verrou ACCESS EXCLUSIVE canonique bloque
        réellement une écriture concurrente pendant toute la durée de la
        transaction unique du runner — pas seulement au moment de son
        acquisition, comme le motif fautif ``psql -f`` (sans
        ``--single-transaction``) le permettait avant ce correctif (le
        verrou y était relâché entre deux instructions, laissant une
        fenêtre pour qu'une transaction concurrente s'intercale).

        Construction déterministe (pas de course contre la vitesse
        d'exécution du rollback, qui est un DDL quasi instantané et donc
        impossible à "attraper" par un simple sondage) :

        1. Une connexion "blocker" ouvre une transaction et exécute un
           simple ``SELECT`` sur ``jobs`` — acquiert et retient un verrou
           ``ACCESS SHARE`` pendant toute la durée de sa transaction
           (comportement documenté PostgreSQL : un verrou de table acquis
           par une instruction est retenu jusqu'à la fin de la transaction
           englobante, pas seulement de l'instruction).
        2. Le runner de rollback démarre : son premier ``LOCK TABLE ...
           ACCESS EXCLUSIVE`` entre nécessairement en conflit avec le
           verrou du blocker et se met en attente — garanti, sans course.
        3. Une fois cette attente confirmée via ``pg_locks`` (pas un délai
           arbitraire), une troisième connexion tente une écriture
           concurrente (INSERT dans jobs). Sémantique de file d'attente
           équitable de PostgreSQL (anti-famine documentée) : cette requête
           ROW EXCLUSIVE, bien que compatible avec l'ACCESS SHARE déjà
           accordé au blocker, doit à son tour attendre derrière la
           demande ACCESS EXCLUSIVE déjà en file — elle ne peut jamais la
           doubler.
        4. Le blocker relâche son verrou (commit) : le rollback obtient
           enfin son verrou, s'exécute, committe. L'INSERT, débloqué à son
           tour, doit alors réussir (jobs n'est pas supprimée par ce
           rollback partiel) — jamais rester bloqué indéfiniment, jamais
           échouer silencieusement."""
        blocker_conn = psycopg.connect(_superuser_dsn(pg_container), autocommit=False)
        with blocker_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM ingestion_control.jobs LIMIT 1")

        rollback_result: dict[str, subprocess.CompletedProcess[str]] = {}

        def _run_rollback_thread() -> None:
            rollback_result["proc"] = _run_rollback(pg_container, target_version=_HEAD - 1)

        rollback_thread = threading.Thread(target=_run_rollback_thread)
        rollback_thread.start()

        # Confirme que le rollback est bien en attente (pas encore
        # accordé) derrière le verrou du blocker.
        deadline = time.monotonic() + 10.0
        rollback_waiting = False
        with psycopg.connect(_superuser_dsn(pg_container), autocommit=True) as watcher_conn:
            while time.monotonic() < deadline:
                with watcher_conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM pg_locks "
                        "WHERE relation = 'ingestion_control.jobs'::regclass "
                        "AND mode = 'AccessExclusiveLock' AND NOT granted"
                    )
                    (count,) = cur.fetchone()
                if count > 0:
                    rollback_waiting = True
                    break
                time.sleep(0.02)
        assert rollback_waiting, "rollback never queued a pending ACCESS EXCLUSIVE request on jobs"

        insert_conn = psycopg.connect(_superuser_dsn(pg_container), autocommit=False)
        insert_thread_done = threading.Event()
        insert_error: dict[str, BaseException] = {}

        def _attempt_insert() -> None:
            try:
                run_id = _insert_run(insert_conn)
                with insert_conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO ingestion_control.jobs (job_id, run_id, job_type) "
                        "VALUES (%s, %s, %s)",
                        (uuid.uuid4(), run_id, "concurrent_write_probe"),
                    )
                insert_conn.commit()
            except BaseException as exc:  # noqa: BLE001 - capturé pour assertion dans le thread principal
                insert_error["exc"] = exc
            finally:
                insert_thread_done.set()

        insert_thread = threading.Thread(target=_attempt_insert)
        insert_thread.start()

        # Preuve de la file d'attente équitable : l'INSERT ne se termine
        # pas tant que le rollback (lui-même toujours en attente derrière
        # le blocker) n'a pas été servi en premier.
        blocked_confirmed = not insert_thread_done.wait(timeout=1.0)
        assert blocked_confirmed, (
            "concurrent INSERT completed before the queued rollback — "
            "PostgreSQL's fair lock queueing did not protect the rollback's request"
        )

        # Relâche le blocker : débloque le rollback, qui doit alors
        # s'exécuter et committer normalement.
        blocker_conn.rollback()
        blocker_conn.close()

        rollback_thread.join(timeout=30)
        insert_thread.join(timeout=10)

        result = rollback_result["proc"]
        assert result.returncode == 0, result.stderr
        assert "ROLLBACK_COMPLETE" in result.stdout

        assert insert_thread_done.is_set()
        if "exc" in insert_error:
            raise AssertionError(f"blocked INSERT failed after unblocking: {insert_error['exc']!r}")

        insert_conn.close()
