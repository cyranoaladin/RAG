"""LOT43 : migrations pgvector automatiques sur une base PostgreSQL vraiment vierge.

Test d'intégration réel (pas de commande-double) : démarre un vrai conteneur
``pgvector/pgvector:pg16`` sur un volume neuf, applique ``init.sql`` (ce que
fait ``docker-entrypoint-initdb.d`` en production), puis exécute
``bootstrap_pgvector_schema.sh`` et vérifie l'état réel du schéma en base.

Nécessite Docker. Marqué ``integration`` : ignoré si Docker n'est pas
disponible (cohérent avec la convention DATABASE_URL_TEST des autres tests
d'intégration de ce dépôt).
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Generator, Iterator
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_pgvector_schema.sh"
INIT_SQL = INFRA_ROOT / "postgres" / "init.sql"
MIGRATIONS_DIR = INFRA_ROOT / "postgres" / "migrations"

PG_IMAGE = "pgvector/pgvector:pg16"
PG_USER = "raguser"
PG_PASSWORD = "test-password"
PG_DB = "ragdb"

_DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker not available — skip real Postgres bootstrap test"),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_pg_isready(port: int, timeout_s: float = 60.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = subprocess.run(
            ["pg_isready", "-h", "127.0.0.1", "-p", str(port), "-U", PG_USER],
            capture_output=True,
            check=False,
        )
        if result.returncode == 0:
            return
        time.sleep(0.5)
    raise TimeoutError(f"Postgres not ready on port {port} after {timeout_s}s")


@pytest.fixture
def fresh_pgvector_container() -> Generator[dict[str, str], None, None]:
    container_name = f"nexus-lot43-migration-test-{uuid.uuid4().hex[:10]}"
    port = _free_port()
    subprocess.run(
        [
            "docker", "run", "-d", "--rm",
            "--name", container_name,
            "-e", f"POSTGRES_USER={PG_USER}",
            "-e", f"POSTGRES_PASSWORD={PG_PASSWORD}",
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
        env.update(
            {
                "PGHOST": "127.0.0.1",
                "PGPORT": str(port),
                "PGUSER": PG_USER,
                "PGPASSWORD": PG_PASSWORD,
                "PGDATABASE": PG_DB,
            }
        )
        # Simule docker-entrypoint-initdb.d : applique init.sql sur le volume neuf.
        subprocess.run(
            ["psql", "-X", "-q", "-v", "ON_ERROR_STOP=1", "-f", str(INIT_SQL)],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        yield env
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _run_bootstrap(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(BOOTSTRAP_SCRIPT)],
        cwd=ENGINE_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _connect(env: dict[str, str]) -> Iterator[psycopg.Connection]:
    return psycopg.connect(
        host=env["PGHOST"], port=env["PGPORT"], user=env["PGUSER"],
        password=env["PGPASSWORD"], dbname=env["PGDATABASE"],
    )


def test_bootstrap_reaches_declared_head_on_freshly_initialized_volume(
    fresh_pgvector_container: dict[str, str],
) -> None:
    env = fresh_pgvector_container

    result = _run_bootstrap(env)

    assert result.returncode == 0, result.stderr
    assert "BOOTSTRAP_COMPLETE" in result.stdout
    assert "SCHEMA_VERIFICATION=OK" in result.stdout

    declared_head = int((MIGRATIONS_DIR / "HEAD").read_text().strip().split("_", 1)[0])
    assert f"SCHEMA_HEAD={declared_head}" in result.stdout

    with _connect(env) as conn, conn.cursor() as cur:
        cur.execute("SELECT version, file_name FROM rag_schema_migrations ORDER BY version;")
        rows = cur.fetchall()
        assert [r[0] for r in rows] == [1, 2, 3]

        cur.execute(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_schema='public' AND table_name='rag_chunks'
              AND column_name IN ('tenant', 'candidat', 'visibility', 'school_year', 'programme_version')
            ORDER BY column_name;
            """
        )
        profile_columns = {r[0] for r in cur.fetchall()}
        assert profile_columns == {
            "tenant", "candidat", "visibility", "school_year", "programme_version",
        }


def test_bootstrap_is_idempotent_on_rerun(fresh_pgvector_container: dict[str, str]) -> None:
    env = fresh_pgvector_container

    first = _run_bootstrap(env)
    assert first.returncode == 0, first.stderr

    second = _run_bootstrap(env)

    assert second.returncode == 0, second.stderr
    assert "MIGRATIONS_APPLIED=0" in second.stdout
    assert "MIGRATIONS_ADOPTED=0" in second.stdout
    assert "BOOTSTRAP_COMPLETE" in second.stdout

    with _connect(env) as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM rag_schema_migrations;")
        assert cur.fetchone()[0] == 3


def test_bootstrap_fails_explicitly_on_registry_checksum_mismatch(
    fresh_pgvector_container: dict[str, str],
) -> None:
    env = fresh_pgvector_container

    first = _run_bootstrap(env)
    assert first.returncode == 0, first.stderr

    with _connect(env) as conn, conn.cursor() as cur:
        cur.execute(
            "UPDATE rag_schema_migrations SET sha256 = repeat('0', 64) WHERE version = 3;"
        )
        conn.commit()

    tampered = _run_bootstrap(env)

    assert tampered.returncode != 0
    assert "MIGRATION_CHECKSUM_MISMATCH" in tampered.stderr
