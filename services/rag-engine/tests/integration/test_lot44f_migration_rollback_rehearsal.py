"""LOT44f/ADR-0029 : répétition complète migration -> rollback -> migration
sur PostgreSQL réel.

Périmètre strict : ferme la dette documentée par l'audit go-live
(``docs/reports/rag_project_global_state_2026-08-04.md``, section 11) —
« rollback absent pour 001 et 004 ». Ce test rejoue les six rollbacks
(006..001, ordre inverse strict) sur une base fraîchement bootstrappée,
vérifie que le schéma est réellement vidé, puis réapplique le bootstrap
en entier pour prouver que la chaîne de migrations reste rejouable après
un rollback complet — pas seulement que chaque fichier ``.down.sql``
s'exécute sans erreur SQL.

Aucune donnée applicative n'est insérée dans ce test : chaque garde
``ROLLBACK_00X_DATA_PRESENT`` doit donc passer silencieusement — si l'une
d'elles levait, ce serait un signe que le bootstrap lui-même insère des
données de test résiduelles, jamais attendu ici.
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
MIGRATIONS_DIR = INFRA_ROOT / "postgres" / "ingestion_control" / "migrations"
ROLLBACKS_DIR = INFRA_ROOT / "postgres" / "ingestion_control" / "rollbacks"

sys.path.insert(0, str(ENGINE_ROOT / "src"))

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

#: Ordre de rollback : inverse strict de l'ordre d'application, dérivé des
#: fichiers de migration réellement présents (jamais une liste codée en dur
#: qui pourrait diverger silencieusement d'une future migration ajoutée).
_MIGRATION_VERSIONS = sorted(
    int(p.name.split("_", 1)[0])
    for p in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql")
)


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
    """Non ``scope='module'`` volontairement : ce test mute le schéma de
    façon destructive (DROP TABLE) — un conteneur dédié par test, jamais
    partagé avec d'autres suites."""
    container_name = f"nexus-lot44f-rollback-rehearsal-{uuid.uuid4().hex[:10]}"
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


def _bootstrap_env(pg_container: dict[str, str]) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "PGHOST": pg_container["host"], "PGPORT": pg_container["port"],
        "PGUSER": PG_SUPERUSER, "PGPASSWORD": PG_SUPERUSER_PASSWORD,
        "PGDATABASE": pg_container["dbname"],
    })
    return env


def _run_bootstrap(pg_container: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=_bootstrap_env(pg_container),
        capture_output=True, text=True, check=False,
    )


def _superuser_dsn(pg_container: dict[str, str]) -> str:
    return (
        f"host={pg_container['host']} port={pg_container['port']} "
        f"dbname={pg_container['dbname']} user={PG_SUPERUSER} password={PG_SUPERUSER_PASSWORD}"
    )


def _apply_rollback_file(conn: psycopg.Connection, *, version: int) -> None:
    matches = list(ROLLBACKS_DIR.glob(f"{version:03d}_*.down.sql"))
    assert len(matches) == 1, f"expected exactly one rollback file for version {version}, found {matches}"
    sql = matches[0].read_text(encoding="utf-8")
    with conn.cursor() as cur:
        cur.execute(sql)
        cur.execute(
            "DELETE FROM ingestion_control.schema_migrations WHERE version = %s", (version,)
        )
    conn.commit()


class TestFullRollbackRehearsal:
    def test_apply_all_rollback_all_reapply_all(self, pg_container: dict[str, str]) -> None:
        assert _MIGRATION_VERSIONS == list(range(1, len(_MIGRATION_VERSIONS) + 1)), (
            "migration numbering must be contiguous from 1 — precondition of this rehearsal"
        )

        first_bootstrap = _run_bootstrap(pg_container)
        assert first_bootstrap.returncode == 0, first_bootstrap.stderr
        assert f"SCHEMA_HEAD={_MIGRATION_VERSIONS[-1]}" in first_bootstrap.stdout

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version FROM ingestion_control.schema_migrations ORDER BY version")
                applied_before = [row[0] for row in cur.fetchall()]
            assert applied_before == _MIGRATION_VERSIONS

            # Rollback en ordre inverse strict — jamais un ordre arbitraire :
            # chaque .down.sql suppose que les migrations plus récentes ont
            # déjà été défaites (ex. 004.down.sql suppose jobs vide, lui-même
            # nécessite que 005/006 — qui ne touchent que jobs/candidates —
            # aient déjà été rejouées).
            for version in reversed(_MIGRATION_VERSIONS):
                _apply_rollback_file(conn, version=version)

            with conn.cursor() as cur:
                cur.execute("SELECT version FROM ingestion_control.schema_migrations")
                remaining = cur.fetchall()
            assert remaining == [], "schema_migrations must be empty after a full rollback"

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'ingestion_control' AND table_name != 'schema_migrations'"
                )
                remaining_tables = cur.fetchall()
            assert remaining_tables == [], (
                f"expected no ingestion_control tables left besides schema_migrations, "
                f"found {remaining_tables}"
            )

        # Réapplication complète depuis un schéma vidé : la chaîne de
        # migrations doit rester intégralement rejouable après un rollback
        # total, pas seulement idempotente sur un schéma déjà à jour.
        second_bootstrap = _run_bootstrap(pg_container)
        assert second_bootstrap.returncode == 0, second_bootstrap.stderr
        assert f"MIGRATIONS_APPLIED={len(_MIGRATION_VERSIONS)}" in second_bootstrap.stdout
        assert f"SCHEMA_HEAD={_MIGRATION_VERSIONS[-1]}" in second_bootstrap.stdout

        with psycopg.connect(_superuser_dsn(pg_container)) as conn, conn.cursor() as cur:
            cur.execute("SELECT version FROM ingestion_control.schema_migrations ORDER BY version")
            applied_after = [row[0] for row in cur.fetchall()]
        assert applied_after == _MIGRATION_VERSIONS
