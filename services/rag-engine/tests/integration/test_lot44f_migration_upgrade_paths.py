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

import os
import secrets
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
INFRA_ROOT = ENGINE_ROOT / "infra"
MIGRATIONS_DIR = INFRA_ROOT / "postgres" / "ingestion_control" / "migrations"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"

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


class TestMigration004FKConstraintScoping:
    """Revue PR#90 (Cubic P1, revue incrémentale) : un nom de contrainte
    PostgreSQL n'est unique que par table, jamais par schéma — la garde
    d'idempotence de la migration 004 doit rester correcte même en
    présence d'une contrainte homonyme sur une autre table du même
    schéma."""

    def test_homonym_constraint_on_another_table_does_not_fool_the_guard(
        self, pg_container: dict[str, str]
    ) -> None:
        with _superuser_conn(pg_container) as conn:
            for version in (1, 2, 3):
                _apply_migration_file(conn, version)

            # Contrainte de même nom que celle attendue sur workflow_events,
            # mais posée ici sur resource_candidates -> artifacts (aucun
            # rapport avec jobs). Un simple filtre conname+connamespace la
            # confondrait avec la vraie contrainte attendue.
            with conn.cursor() as cur:
                cur.execute(
                    """
                    ALTER TABLE ingestion_control.resource_candidates
                        ADD CONSTRAINT workflow_events_job_id_fkey
                        FOREIGN KEY (resource_id) REFERENCES ingestion_control.resources (resource_id)
                    """
                )

            # La migration 004 doit tout de même créer la vraie FK sur
            # workflow_events, jamais la sauter à cause de l'homonyme.
            _apply_migration_file(conn, 4)

            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT pg_get_constraintdef(oid) FROM pg_constraint
                    WHERE conname = 'workflow_events_job_id_fkey'
                      AND conrelid = 'ingestion_control.workflow_events'::regclass
                    """
                )
                row = cur.fetchone()
            assert row is not None, "the real FK on workflow_events must exist"
            assert row[0] == "FOREIGN KEY (job_id) REFERENCES ingestion_control.jobs(job_id)"

    def test_mismatched_constraint_definition_on_the_right_table_is_rejected(
        self, pg_container: dict[str, str]
    ) -> None:
        """Cas plus subtil : une contrainte de même nom existe bien sur
        ``workflow_events``, mais avec une définition différente (ex. posée
        manuellement, ou héritage d'un schéma corrompu) — la migration ne
        doit jamais l'accepter silencieusement comme si c'était la bonne."""
        with _superuser_conn(pg_container) as conn:
            for version in (1, 2, 3):
                _apply_migration_file(conn, version)

            with conn.cursor() as cur:
                # resource_id n'existe pas sur workflow_events par défaut ;
                # on simule une contrainte mal définie via un nom identique
                # mais une cible différente (run_id -> ingestion_runs).
                cur.execute(
                    """
                    ALTER TABLE ingestion_control.workflow_events
                        ADD CONSTRAINT workflow_events_job_id_fkey
                        FOREIGN KEY (run_id) REFERENCES ingestion_control.ingestion_runs (run_id)
                    """
                )

            with pytest.raises(psycopg.errors.RaiseException, match="MIGRATION_004_FK_MISMATCH"):
                _apply_migration_file(conn, 4)


class TestMigration005ClaimedStatusBackfill:
    """Revue PR#90 (Cubic P1, revue incrémentale) : politique déterministe
    selon l'état réel du bail, jamais un backfill aveugle vers 'running' —
    une ligne 'claimed' sans bail actif deviendrait autrement 'running'
    mais plus jamais réclamable (claim_job ne sélectionne que 'queued')."""

    def _insert_run(self, conn: psycopg.Connection) -> object:
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
        return run_id

    def test_claimed_with_active_lease_becomes_running(
        self, pg_container: dict[str, str]
    ) -> None:
        with _superuser_conn(pg_container) as conn:
            for version in (1, 2, 3, 4):
                _apply_migration_file(conn, version)
            run_id = self._insert_run(conn)

            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ingestion_control.jobs "
                    "(job_id, run_id, job_type, status, claimed_by, lease_token, lease_expires_at) "
                    "VALUES (gen_random_uuid(), %s, 'resource_pipeline', 'claimed', "
                    "'worker-x', gen_random_uuid(), now() + interval '5 minutes') "
                    "RETURNING job_id",
                    (run_id,),
                )
                (job_id,) = cur.fetchone()

            _apply_migration_file(conn, 5)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, lease_token FROM ingestion_control.jobs WHERE job_id = %s",
                    (job_id,),
                )
                status, lease_token = cur.fetchone()
            assert status == "running"
            assert lease_token is not None, "an active lease must be preserved, not wiped"

    def test_claimed_with_expired_lease_becomes_queued_and_cleared(
        self, pg_container: dict[str, str]
    ) -> None:
        with _superuser_conn(pg_container) as conn:
            for version in (1, 2, 3, 4):
                _apply_migration_file(conn, version)
            run_id = self._insert_run(conn)

            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO ingestion_control.jobs "
                    "(job_id, run_id, job_type, status, claimed_by, lease_token, lease_expires_at) "
                    "VALUES (gen_random_uuid(), %s, 'resource_pipeline', 'claimed', "
                    "'worker-x', gen_random_uuid(), now() - interval '1 minute') "
                    "RETURNING job_id",
                    (run_id,),
                )
                (job_id,) = cur.fetchone()

            _apply_migration_file(conn, 5)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, claimed_by, lease_token, lease_expires_at "
                    "FROM ingestion_control.jobs WHERE job_id = %s",
                    (job_id,),
                )
                status, claimed_by, lease_token, lease_expires_at = cur.fetchone()
            assert status == "queued"
            assert claimed_by is None
            assert lease_token is None
            assert lease_expires_at is None

    def test_claimed_without_any_lease_becomes_queued_and_cleared(
        self, pg_container: dict[str, str]
    ) -> None:
        with _superuser_conn(pg_container) as conn:
            for version in (1, 2, 3, 4):
                _apply_migration_file(conn, version)
            run_id = self._insert_run(conn)

            with conn.cursor() as cur:
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
            assert status == "queued"


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

    def test_migration_006_fails_explicitly_on_preexisting_artifact_row(
        self, pg_container: dict[str, str]
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P3) : la migration 006 porte
        DEUX préflights de vacuité indépendants (``resource_candidates`` ET
        ``artifacts``, cf. le fichier de migration) — le test ci-dessus ne
        couvrait que le premier. Ce test exerce spécifiquement le second :
        ``artifacts`` non vide, ``resource_candidates`` vide, doit lui
        aussi être rejeté explicitement, jamais silencieusement accepté
        parce que la table sœur, elle, était vide."""
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
                    VALUES (gen_random_uuid(), %s, 'f' || repeat('e', 63), 't', 'c', 'terminale',
                            'generale', 'nsi', 'libre', ARRAY['libre'], 'internal', '2026-2027', 'v1')
                    RETURNING resource_id
                    """,
                    (run_id,),
                )
                (resource_id,) = cur.fetchone()
                # Seul artifacts reçoit une ligne — resource_candidates
                # reste vide, pour isoler précisément le second préflight.
                cur.execute(
                    """
                    INSERT INTO ingestion_control.artifacts
                        (artifact_id, resource_id, run_id, sha256, size_bytes, mime_declared,
                         mime_detected, original_url, final_url, collected_at)
                    VALUES (gen_random_uuid(), %s, %s, repeat('0', 64), 100, 'text/html',
                            'text/html', 'https://eduscol.education.fr/x',
                            'https://eduscol.education.fr/x', now())
                    """,
                    (resource_id, run_id),
                )

            with pytest.raises(
                psycopg.errors.RaiseException, match="MIGRATION_006_PREEXISTING_ROWS_artifacts"
            ):
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

    def test_lock_table_statement_precedes_the_vacuity_preflight_in_file_order(self) -> None:
        """Complément structurel à la preuve comportementale ci-dessous.

        Vérification empirique préalable (par expérimentation délibérée,
        retrait temporaire du ``LOCK TABLE`` puis ré-exécution du test de
        blocage comportemental) : celui-ci passe encore MÊME SANS le
        ``LOCK TABLE`` explicite, parce que l'``ALTER TABLE ADD COLUMN`` qui
        suit exige de toute façon un verrou ``ACCESS EXCLUSIVE`` implicite —
        un bloqueur externe qui contraint l'accès à la table fait donc
        toujours apparaître *une* attente sur ce verrou, qu'elle survienne
        avant ou après le bloc de préflight ``DO $nexus$``. ``pg_locks`` ne
        distingue pas *quelle* instruction du fichier est à l'origine d'une
        attente donnée — un test purement comportemental via verrouillage
        externe ne peut donc pas, à lui seul, prouver que le verrou est pris
        *avant* le préflight plutôt que seulement au moment de l'ALTER qui
        le suit. Cette vérification positionnelle explicite comble ce point
        aveugle : elle exige textuellement que ``LOCK TABLE`` apparaisse
        avant ``DO $nexus$`` dans le fichier — invariant qui, combiné à
        l'exécution en transaction unique (``apply_migration``/bootstrap),
        garantit que le verrou est bien détenu depuis avant le préflight."""
        sql = MIGRATIONS_DIR.glob("006_*.sql")
        (path,) = sql
        content = path.read_text(encoding="utf-8")
        lock_index = content.index("LOCK TABLE ingestion_control.resource_candidates")
        preflight_index = content.index("DO $nexus$")
        assert lock_index < preflight_index, (
            "LOCK TABLE must appear before the DO $nexus$ vacuity preflight block, "
            "not merely rely on the implicit lock taken later by ALTER TABLE"
        )

    def test_concurrent_write_is_blocked_from_preflight_through_end_of_migration(
        self, pg_container: dict[str, str]
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P1) : preuve directe que le
        ``LOCK TABLE ... ACCESS EXCLUSIVE`` pris en tête de la migration 006
        bloque réellement une écriture concurrente pendant toute la fenêtre
        préflight -> ALTER — pas seulement une preuve statique de présence
        du texte SQL. Même construction déterministe (verrou ACCESS SHARE
        préalable + file d'attente équitable PostgreSQL) que
        ``test_lot44f_rollback_runner.py::
        TestRollbackRunnerConcurrentWriteInterference`` : un DDL de ce type
        est quasi instantané, donc un simple sondage temporel serait
        intrinsèquement fragile."""
        setup_conn = _superuser_conn(pg_container)
        for version in (1, 2, 3, 4, 5):
            _apply_migration_file(setup_conn, version)
        setup_conn.close()

        blocker_conn = psycopg.connect(
            host=pg_container["host"], port=pg_container["port"], dbname=pg_container["dbname"],
            user=PG_SUPERUSER, password=PG_SUPERUSER_PASSWORD, autocommit=False,
        )
        with blocker_conn.cursor() as cur:
            cur.execute("SELECT 1 FROM ingestion_control.resource_candidates LIMIT 1")

        migration_result: dict[str, BaseException | None] = {"error": None}

        def _apply_migration_6() -> None:
            try:
                migration_conn = _superuser_conn(pg_container)
                try:
                    _apply_migration_file(migration_conn, 6)
                finally:
                    migration_conn.close()
            except BaseException as exc:  # noqa: BLE001 - capturé pour assertion côté thread principal
                migration_result["error"] = exc

        import threading

        migration_thread = threading.Thread(target=_apply_migration_6)
        migration_thread.start()

        deadline = time.monotonic() + 10.0
        migration_waiting = False
        with psycopg.connect(
            host=pg_container["host"], port=pg_container["port"], dbname=pg_container["dbname"],
            user=PG_SUPERUSER, password=PG_SUPERUSER_PASSWORD, autocommit=True,
        ) as watcher_conn:
            while time.monotonic() < deadline:
                with watcher_conn.cursor() as cur:
                    cur.execute(
                        "SELECT count(*) FROM pg_locks "
                        "WHERE relation = 'ingestion_control.resource_candidates'::regclass "
                        "AND mode = 'AccessExclusiveLock' AND NOT granted"
                    )
                    (count,) = cur.fetchone()
                if count > 0:
                    migration_waiting = True
                    break
                time.sleep(0.02)
        assert migration_waiting, (
            "migration 006 never queued a pending ACCESS EXCLUSIVE request on "
            "resource_candidates — the lock is not actually taken before the preflight"
        )

        insert_conn = psycopg.connect(
            host=pg_container["host"], port=pg_container["port"], dbname=pg_container["dbname"],
            user=PG_SUPERUSER, password=PG_SUPERUSER_PASSWORD, autocommit=False,
        )
        insert_done = threading.Event()
        insert_error: dict[str, BaseException] = {}

        def _attempt_insert() -> None:
            try:
                with insert_conn.cursor() as cur:
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
                        VALUES (gen_random_uuid(), %s, 'concurrent-probe-' || gen_random_uuid(),
                                't', 'c', 'terminale', 'generale', 'nsi', 'libre', ARRAY['libre'],
                                'internal', '2026-2027', 'v1')
                        RETURNING resource_id
                        """,
                        (run_id,),
                    )
                    (resource_id,) = cur.fetchone()
                    cur.execute(
                        """
                        INSERT INTO ingestion_control.resource_candidates
                            (candidate_id, resource_id, run_id, dedup_key, source_url,
                             canonical_url, domain, proposed_type_doc, discovered_at)
                        VALUES (gen_random_uuid(), %s, %s, 'concurrent-probe-' || gen_random_uuid(),
                                'https://eduscol.education.fr/y', 'https://eduscol.education.fr/y',
                                'eduscol.education.fr', 'cours', now())
                        """,
                        (resource_id, run_id),
                    )
                insert_conn.commit()
            except BaseException as exc:  # noqa: BLE001 - capturé pour assertion côté thread principal
                insert_error["exc"] = exc
            finally:
                insert_done.set()

        insert_thread = threading.Thread(target=_attempt_insert)
        insert_thread.start()

        blocked_confirmed = not insert_done.wait(timeout=1.0)
        assert blocked_confirmed, (
            "concurrent INSERT into resource_candidates completed before the queued "
            "migration — the preflight-to-ALTER window was not actually protected"
        )

        blocker_conn.rollback()
        blocker_conn.close()

        migration_thread.join(timeout=30)
        insert_thread.join(timeout=10)

        assert migration_result["error"] is None, f"migration 006 failed: {migration_result['error']!r}"
        assert insert_done.is_set()
        if "exc" in insert_error:
            raise AssertionError(f"blocked INSERT failed after unblocking: {insert_error['exc']!r}")

        insert_conn.close()


class TestConcurrentBootstrapInvocations:
    def test_two_simultaneous_bootstrap_runs_never_fail_on_duplicate_object_errors(
        self, pg_container: dict[str, str]
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P2) : avant ce correctif, la
        toute première création du schéma/registre
        (``registry_schema_sql``) s'exécutait hors de tout verrou —
        ``CREATE SCHEMA/TABLE IF NOT EXISTS`` n'est pas atomique contre une
        création concurrente en ``READ COMMITTED`` (comportement documenté
        PostgreSQL) : deux instances de ``bootstrap_ingestion_control_
        schema.sh`` démarrées en même temps sur un volume neuf pouvaient
        toutes deux voir "n'existe pas encore" et échouer l'une sur l'autre
        avec une erreur de clé dupliquée, au lieu d'un no-op silencieux
        pour la seconde. Ce test lance réellement deux instances du script
        en parallèle contre un volume neuf et exige que les DEUX
        réussissent (``BOOTSTRAP_COMPLETE``), jamais l'une des deux en
        échec."""
        env = os.environ.copy()
        env.update({
            "PGHOST": pg_container["host"], "PGPORT": pg_container["port"],
            "PGUSER": PG_SUPERUSER, "PGPASSWORD": PG_SUPERUSER_PASSWORD,
            "PGDATABASE": pg_container["dbname"],
        })

        results: list[subprocess.CompletedProcess[str]] = []

        def _run() -> None:
            results.append(
                subprocess.run(
                    [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
                    capture_output=True, text=True, check=False,
                )
            )

        import threading

        threads = [threading.Thread(target=_run) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert len(results) == 2
        for result in results:
            assert result.returncode == 0, (
                f"a concurrent bootstrap invocation failed instead of "
                f"serializing behind the advisory lock:\nstdout={result.stdout}\n"
                f"stderr={result.stderr}"
            )
            assert "BOOTSTRAP_COMPLETE" in result.stdout

        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute("SELECT version FROM ingestion_control.schema_migrations ORDER BY version")
            applied = [row[0] for row in cur.fetchall()]
        expected_versions = sorted(
            int(p.name.split("_", 1)[0]) for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")
        )
        assert applied == expected_versions, (
            "each migration must be applied exactly once despite two concurrent runners"
        )


def _insert_scope_authorization(
    conn: psycopg.Connection,
    *,
    authorization_id: str,
    protocol_version: str,
    allowed_content_sha256: object = None,
    include_allowlist: bool = True,
) -> None:
    allowlist_column = ", allowed_content_sha256" if include_allowlist else ""
    allowlist_value = ", %s::text[]" if include_allowlist else ""
    params: list[object] = [authorization_id, protocol_version, authorization_id]
    if include_allowlist:
        params.append(allowed_content_sha256)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO ingestion_control.scope_authorizations (
                authorization_id, protocol_version, decision,
                tenant, collection, niveau, voie, matiere, candidat, audience,
                visibility, school_year, programme_version,
                manifest_digest, profile_id, profile_version, profile_fingerprint,
                allowed_domains, rights_categories, exclusions,
                pii_absence_attested, pii_absence_evidence,
                valid_from, valid_until,
                artifact_path, artifact_blob_sha, authorization_digest,
                evidence_repository, evidence_pull_request,
                evidence_base_sha, evidence_head_sha, evidence_review_id,
                evidence_reviewer, evidence_submitted_at, evidence_challenge
                {allowlist_column}
            ) VALUES (
                %s, %s, 'AUTHORIZE_INGESTION_SCOPE',
                'nexus', 'libre_terminale_philosophie', 'terminale', 'generale',
                'philosophie', 'libre', ARRAY['libre'], 'internal', '2026-2027',
                'BOEN_special_8_2019-07-25',
                repeat('a', 64), 'terminale-philosophie', '1.0.0', repeat('b', 64),
                ARRAY['eduscol.education.gouv.fr'], ARRAY['officiel_public'], ARRAY[]::text[],
                true, 'sha256:evidence', now() - interval '1 minute', now() + interval '1 day',
                'governance/authorizations/' || %s || '.json',
                repeat('c', 40), repeat('d', 64),
                'cyranoaladin/RAG', 96, repeat('e', 40), repeat('f', 40), 1,
                'abenrhouma', now(), 'NEXUS-TRUSTED-REVIEW-V1:' || repeat('0', 64)
                {allowlist_value}
            )
            """,
            tuple(params),
        )


class TestScopeAuthorizationContentAllowlist:
    _SHA_A = "a" * 64
    _SHA_B = "b" * 64

    def test_existing_v1_row_survives_apply_and_valid_v2_is_accepted(
        self, pg_container: dict[str, str]
    ) -> None:
        with _superuser_conn(pg_container) as conn:
            for version in range(1, 9):
                _apply_migration_file(conn, version)
            _insert_scope_authorization(
                conn,
                authorization_id="existing-v1",
                protocol_version="LOT41A-V1",
                include_allowlist=False,
            )

            _apply_migration_file(conn, 9)
            _insert_scope_authorization(
                conn,
                authorization_id="valid-v2",
                protocol_version="LOT41A-V2",
                allowed_content_sha256=[self._SHA_A, self._SHA_B],
            )

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT authorization_id, protocol_version, allowed_content_sha256 "
                    "FROM ingestion_control.scope_authorizations ORDER BY authorization_id"
                )
                rows = cur.fetchall()
            assert rows == [
                ("existing-v1", "LOT41A-V1", None),
                ("valid-v2", "LOT41A-V2", [self._SHA_A, self._SHA_B]),
            ]

    @pytest.mark.parametrize(
        ("protocol_version", "allowlist"),
        [
            ("LOT41A-V2", None),
            ("LOT41A-V2", []),
            ("LOT41A-V2", ["g" * 64]),
            ("LOT41A-V2", ["A" * 64]),
            ("LOT41A-V2", ["a" * 64, "a" * 64]),
            ("LOT41A-V2", ["b" * 64, "a" * 64]),
            ("LOT41A-V2", f"[0:0]={{{'a' * 64}}}"),
            ("LOT41A-V2", f"{{{{{'a' * 64},{'b' * 64}}}}}"),
            ("LOT41A-V2", ["a" * 64, None]),
            ("LOT41A-V1", ["a" * 64]),
        ],
        ids=[
            "v2-null",
            "v2-empty",
            "v2-malformed",
            "v2-uppercase",
            "v2-duplicate",
            "v2-unsorted",
            "v2-lower-bound-zero",
            "v2-two-dimensional",
            "v2-null-member",
            "v1-populated",
        ],
    )
    def test_direct_sql_rejects_noncanonical_version_allowlist_combinations(
        self,
        pg_container: dict[str, str],
        protocol_version: str,
        allowlist: object,
    ) -> None:
        with _superuser_conn(pg_container) as conn:
            for version in range(1, 10):
                _apply_migration_file(conn, version)

            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_scope_authorization(
                    conn,
                    authorization_id="invalid-allowlist",
                    protocol_version=protocol_version,
                    allowed_content_sha256=allowlist,
                )

    def test_unknown_protocol_is_rejected(self, pg_container: dict[str, str]) -> None:
        with _superuser_conn(pg_container) as conn:
            for version in range(1, 10):
                _apply_migration_file(conn, version)

            with pytest.raises(psycopg.errors.CheckViolation):
                _insert_scope_authorization(
                    conn,
                    authorization_id="unknown-protocol",
                    protocol_version="LOT41A-V3",
                    allowed_content_sha256=[self._SHA_A],
                )
