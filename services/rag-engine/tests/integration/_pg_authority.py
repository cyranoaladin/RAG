"""Socle PostgreSQL réel partagé par les suites d'autorité LOT41A/LOT42.

Un conteneur ``pgvector/pgvector:pg16`` réel, migré par les VRAIS scripts
de bootstrap et de provisioning de rôles — jamais un schéma recréé à la
main dans le test, qui pourrait diverger de celui réellement déployé.

Les quatre rôles (migrator / app / authority / attestor) sont provisionnés
avec leurs privilèges de production exacts : les tests d'isolation (item K)
mesurent donc les vrais GRANT, pas une approximation.
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

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

#: Image épinglée par digest — jamais un tag mutable. La valeur est
#: celle déjà vérifiée et versionnée dans ``infra/docker-compose.v2.yml``
#: (source de vérité unique) : un test de gouvernance qui tournerait sur
#: une image différente de celle du runtime ne prouverait rien sur le
#: runtime.
PG_IMAGE = "pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc"
PG_SUPERUSER = "raguser"
PG_SUPERUSER_PASSWORD = secrets.token_urlsafe(24)
PG_DB = "ragdb"
APP_PASSWORD = secrets.token_urlsafe(24)
MIGRATOR_PASSWORD = secrets.token_urlsafe(24)
AUTHORITY_PASSWORD = secrets.token_urlsafe(24)
ATTESTOR_PASSWORD = secrets.token_urlsafe(24)

DOCKER_AVAILABLE = shutil.which("docker") is not None and (
    subprocess.run(["docker", "info"], capture_output=True, check=False).returncode == 0
)

requires_docker = pytest.mark.skipif(not DOCKER_AVAILABLE, reason="Docker not available")


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _wait_pg_isready(port: int, timeout_s: float = 90.0) -> None:
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


def start_ingestion_control_postgres(label: str) -> Iterator[dict[str, str]]:
    """Démarre, migre et provisionne une instance jetable. Toujours
    supprimée à la sortie, même sur échec."""
    container_name = f"nexus-{label}-{uuid.uuid4().hex[:10]}"
    port = free_port()
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
        env = {
            "PATH": os.environ["PATH"],
            "PGHOST": "127.0.0.1", "PGPORT": str(port), "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD, "PGDATABASE": PG_DB,
        }
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
            "INGESTION_CONTROL_AUTHORITY_PASSWORD": AUTHORITY_PASSWORD,
            "INGESTION_CONTROL_ATTESTOR_PASSWORD": ATTESTOR_PASSWORD,
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


def dsn_for(pg: dict[str, str], *, user: str, password: str) -> str:
    return (
        f"host={pg['host']} port={pg['port']} dbname={pg['dbname']} "
        f"user={user} password={password}"
    )


def superuser_dsn(pg: dict[str, str]) -> str:
    return dsn_for(pg, user=PG_SUPERUSER, password=PG_SUPERUSER_PASSWORD)


def app_dsn(pg: dict[str, str]) -> str:
    return dsn_for(pg, user="ingestion_control_app", password=APP_PASSWORD)


def authority_dsn(pg: dict[str, str]) -> str:
    return dsn_for(pg, user="ingestion_control_authority", password=AUTHORITY_PASSWORD)


def attestor_dsn(pg: dict[str, str]) -> str:
    return dsn_for(pg, user="ingestion_control_attestor", password=ATTESTOR_PASSWORD)


__all__ = [
    "APP_PASSWORD",
    "ATTESTOR_PASSWORD",
    "AUTHORITY_PASSWORD",
    "DOCKER_AVAILABLE",
    "ENGINE_ROOT",
    "MIGRATOR_PASSWORD",
    "PG_DB",
    "PG_SUPERUSER",
    "PG_SUPERUSER_PASSWORD",
    "app_dsn",
    "attestor_dsn",
    "authority_dsn",
    "dsn_for",
    "free_port",
    "requires_docker",
    "start_ingestion_control_postgres",
    "superuser_dsn",
]
