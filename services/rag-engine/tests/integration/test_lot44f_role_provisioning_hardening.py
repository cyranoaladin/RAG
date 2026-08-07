"""Remédiation revue PR#90 (Cubic P1) : provision_ingestion_control_roles.sh
contre des rôles préexistants volontairement mal configurés — pas seulement
le chemin nominal (rôle absent) déjà couvert transitivement par les autres
suites d'intégration LOT44 via leur fixture ``pg_container``.

Périmètre strict : le script shell lui-même, contre un PostgreSQL jetable
réel — pas les primitives Python (hors périmètre de ce fichier).
"""
from __future__ import annotations

import os
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[2]
INFRA_ROOT = ENGINE_ROOT / "infra"
BOOTSTRAP_SCRIPT = INFRA_ROOT / "scripts" / "bootstrap_ingestion_control_schema.sh"
PROVISION_SCRIPT = INFRA_ROOT / "scripts" / "provision_ingestion_control_roles.sh"

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
    import uuid

    container_name = f"nexus-lot44f-role-hardening-{uuid.uuid4().hex[:10]}"
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
        # Ordre requis, déterminé empiriquement (LOT44f) : le schéma doit
        # exister avant que ce script puisse GRANT sur ses tables.
        bootstrap = subprocess.run(
            [str(BOOTSTRAP_SCRIPT)], cwd=ENGINE_ROOT, env=env,
            capture_output=True, text=True, check=False,
        )
        assert bootstrap.returncode == 0, bootstrap.stderr
        assert "BOOTSTRAP_COMPLETE" in bootstrap.stdout

        yield {"host": "127.0.0.1", "port": str(port), "dbname": PG_DB}
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True, check=False)


def _run_provision_script(pg_container: dict[str, str], **extra_env: str) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update({
        "PGHOST": pg_container["host"], "PGPORT": pg_container["port"],
        "PGUSER": PG_SUPERUSER, "PGPASSWORD": PG_SUPERUSER_PASSWORD,
        "PGDATABASE": pg_container["dbname"],
        "INGESTION_CONTROL_MIGRATOR_PASSWORD": "migrator-test-password-value",
        "INGESTION_CONTROL_APP_PASSWORD": "app-test-password-value",
        "INGESTION_CONTROL_AUTHORITY_PASSWORD": "authority-test-password-value",
        "INGESTION_CONTROL_ATTESTOR_PASSWORD": "attestor-test-password-value",
    })
    env.update(extra_env)
    return subprocess.run(
        [str(PROVISION_SCRIPT)], cwd=ENGINE_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )


def _superuser_conn(pg_container: dict[str, str]) -> psycopg.Connection:
    return psycopg.connect(
        host=pg_container["host"], port=pg_container["port"], dbname=pg_container["dbname"],
        user=PG_SUPERUSER, password=PG_SUPERUSER_PASSWORD, autocommit=True,
    )


class TestRoleCollisionRejected:
    def test_identical_app_and_migrator_role_is_rejected_before_any_db_write(
        self, pg_container: dict[str, str]
    ) -> None:
        result = _run_provision_script(
            pg_container,
            INGESTION_CONTROL_MIGRATOR_ROLE="same_role_name",
            INGESTION_CONTROL_APP_ROLE="same_role_name",
        )
        assert result.returncode != 0
        assert "must be distinct" in result.stderr

        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM pg_roles WHERE rolname = 'same_role_name'")
            (count,) = cur.fetchone()
        assert count == 0, "no role should have been created when validation fails first"

    def test_migrator_role_equal_to_pguser_is_rejected_before_any_db_write(
        self, pg_container: dict[str, str]
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P1) : PGUSER (connexion
        administrative externe, ``raguser`` ici) ne doit jamais coïncider
        avec le rôle de migration lui-même — sinon l'ALTER ROLE ...
        NOSUPERUSER ci-dessous retirerait ses propres privilèges au compte
        utilisé pour se connecter, en plein script."""
        result = _run_provision_script(
            pg_container,
            INGESTION_CONTROL_MIGRATOR_ROLE=PG_SUPERUSER,
        )
        assert result.returncode != 0
        assert "must not equal PGUSER" in result.stderr

        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (PG_SUPERUSER,))
            (is_super,) = cur.fetchone()
        assert is_super is True, "PGUSER's own role must never be altered by a rejected run"

    def test_app_role_equal_to_pguser_is_rejected_before_any_db_write(
        self, pg_container: dict[str, str]
    ) -> None:
        result = _run_provision_script(
            pg_container,
            INGESTION_CONTROL_APP_ROLE=PG_SUPERUSER,
        )
        assert result.returncode != 0
        assert "must not equal PGUSER" in result.stderr

        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute("SELECT rolsuper FROM pg_roles WHERE rolname = %s", (PG_SUPERUSER,))
            (is_super,) = cur.fetchone()
        assert is_super is True, "PGUSER's own role must never be altered by a rejected run"


class TestPreExistingMisconfiguredRoles:
    def test_nologin_migrator_role_is_reset_to_login(self, pg_container: dict[str, str]) -> None:
        """Un rôle laissé NOLOGIN par une intervention externe empêcherait
        toute connexion applicative — le provisioning doit le corriger,
        pas se contenter d'ignorer un rôle déjà présent."""
        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute(
                "CREATE ROLE ingestion_control_migrator NOLOGIN PASSWORD 'whatever-old-password'"
            )

        result = _run_provision_script(pg_container)
        assert result.returncode == 0, result.stderr
        assert "ROLES_PROVISIONED=1" in result.stdout

        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute("SELECT rolcanlogin FROM pg_roles WHERE rolname = 'ingestion_control_migrator'")
            (can_login,) = cur.fetchone()
        assert can_login is True

    def test_over_privileged_app_role_is_stripped_to_least_privilege(
        self, pg_container: dict[str, str]
    ) -> None:
        """Un rôle runtime laissé CREATEDB/CREATEROLE/REPLICATION par une
        dérive de configuration contournerait les protections de
        privilège minimal que ce script établit pour un rôle neuf — le
        provisioning doit les retirer sur un rôle déjà présent aussi."""
        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute(
                "CREATE ROLE ingestion_control_app LOGIN CREATEDB CREATEROLE "
                "PASSWORD 'whatever-old-password'"
            )

        result = _run_provision_script(pg_container)
        assert result.returncode == 0, result.stderr

        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT rolcreatedb, rolcreaterole, rolsuper, rolreplication, "
                "rolbypassrls, rolcanlogin FROM pg_roles WHERE rolname = 'ingestion_control_app'"
            )
            createdb, createrole, super_, replication, bypassrls, can_login = cur.fetchone()
        assert (createdb, createrole, super_, replication, bypassrls) == (False,) * 5
        assert can_login is True

    def test_preexisting_role_membership_is_revoked_and_set_role_refused(
        self, pg_container: dict[str, str]
    ) -> None:
        """Revue incrémentale PR#90 (Cubic P1) : un rôle app préexistant
        rendu membre d'un rôle privilégié tiers (ex. dérive manuelle) ne
        doit conserver aucune voie d'escalade via `SET ROLE` après le
        provisioning — la seule appartenance suffirait à contourner
        NOINHERIT, donc elle doit être révoquée, pas seulement neutralisée
        côté héritage."""
        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute("CREATE ROLE privileged_third_party_role NOLOGIN SUPERUSER")
            cur.execute(
                "CREATE ROLE ingestion_control_app LOGIN PASSWORD 'whatever-old-password'"
            )
            cur.execute("GRANT privileged_third_party_role TO ingestion_control_app")

        result = _run_provision_script(pg_container)
        assert result.returncode == 0, result.stderr

        with _superuser_conn(pg_container) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM pg_auth_members m "
                "JOIN pg_roles g ON g.oid = m.roleid "
                "WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = 'ingestion_control_app') "
                "AND g.rolname = 'privileged_third_party_role'"
            )
            (membership_count,) = cur.fetchone()
        assert membership_count == 0, "membership must be revoked, not merely left NOINHERIT"

        # Preuve directe par comportement, pas seulement par catalogue :
        # une connexion réelle en tant qu'ingestion_control_app ne peut
        # plus SET ROLE vers le rôle tiers.
        with psycopg.connect(
            host=pg_container["host"], port=pg_container["port"], dbname=pg_container["dbname"],
            user="ingestion_control_app", password="app-test-password-value", autocommit=True,
        ) as app_conn, app_conn.cursor() as cur:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                cur.execute("SET ROLE privileged_third_party_role")

    def test_password_visible_to_a_process_listing_is_never_the_real_secret(
        self, pg_container: dict[str, str]
    ) -> None:
        """Remédiation revue PR#90 (Cubic P1) : preuve directe que les mots
        de passe ne sont plus passés comme arguments visibles du processus
        psql — inspecte la ligne de commande psql réellement lancée (via
        ``ps``, capturée pendant l'exécution) et vérifie qu'aucun des deux
        mots de passe n'y apparaît."""
        import threading

        seen_cmdlines: list[str] = []
        stop = threading.Event()

        def _watch_ps() -> None:
            while not stop.is_set():
                out = subprocess.run(["ps", "-eo", "args"], capture_output=True, text=True)
                seen_cmdlines.append(out.stdout)
                time.sleep(0.05)

        watcher = threading.Thread(target=_watch_ps)
        watcher.start()
        try:
            result = _run_provision_script(pg_container)
        finally:
            stop.set()
            watcher.join(timeout=5)

        assert result.returncode == 0, result.stderr
        combined = "\n".join(seen_cmdlines)
        # Remédiation revue PR#90 (Cubic P3, revue incrémentale) : sans
        # cette assertion, le test pouvait passer de façon vacueuse — si le
        # thread d'observation n'avait, par pur hasard de minutage, jamais
        # capturé le moindre processus psql en cours d'exécution (script
        # trop rapide, ordonnancement défavorable), l'absence des mots de
        # passe dans des instantanés `ps` n'ayant JAMAIS vu psql ne prouve
        # rien du tout — un faux sentiment de sécurité. Exige explicitement
        # qu'au moins un instantané ait bien capturé le processus psql réel
        # lancé par ce script (identifié par son flag caractéristique
        # ``--single-transaction``, propre à ce script, pas seulement la
        # chaîne générique "psql" qui pourrait apparaître dans un tout
        # autre contexte du système sous test).
        assert "psql" in combined and "--single-transaction" in combined, (
            "the ps-watcher never actually observed the provisioning script's psql "
            "process — this test would pass vacuously without ever having exercised "
            "the password-visibility guarantee it claims to verify"
        )
        assert "migrator-test-password-value" not in combined
        assert "app-test-password-value" not in combined
