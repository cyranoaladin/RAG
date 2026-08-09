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


def _insert_minimal_authorization(
    conn: psycopg.Connection,
    *,
    authorization_id: str,
    protocol_version: str,
    allowed_content_sha256: list[str] | None,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
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
                evidence_reviewer, evidence_submitted_at, evidence_challenge,
                allowed_content_sha256
            ) VALUES (
                %s, %s, 'AUTHORIZE_INGESTION_SCOPE',
                'nexus', 'libre_terminale_philosophie', 'terminale', 'generale',
                'philosophie', 'libre', ARRAY['libre'], 'internal', '2026-2027',
                'BOEN_special_8_2019-07-25',
                repeat('a', 64), 'terminale-philosophie', '1.0.0', repeat('b', 64),
                ARRAY['eduscol.education.gouv.fr'], ARRAY['officiel_public'], ARRAY[]::text[],
                true, 'sha256:evidence', now() - interval '1 minute', now() + interval '1 day',
                'governance/authorizations/' || %s || '.json', repeat('c', 40), repeat('d', 64),
                'cyranoaladin/RAG', 96, repeat('e', 40), repeat('f', 40), 1,
                'abenrhouma', now(), 'NEXUS-TRUSTED-REVIEW-V1:' || repeat('0', 64),
                %s::text[]
            )
            """,
            (
                authorization_id,
                protocol_version,
                authorization_id,
                allowed_content_sha256,
            ),
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


class TestScopeAuthorizationContentAllowlistRollback:
    def test_rollback_009_refuses_v2_rows_and_leaves_boundary_intact(
        self, pg_container: dict[str, str]
    ) -> None:
        bootstrap = _run_bootstrap(pg_container)
        assert bootstrap.returncode == 0, bootstrap.stderr

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            _insert_minimal_authorization(
                conn,
                authorization_id="rollback-v2",
                protocol_version="LOT41A-V2",
                allowed_content_sha256=["1" * 64],
            )

            with pytest.raises(psycopg.errors.RaiseException, match="ROLLBACK_009_V2_DATA_PRESENT"):
                _apply_rollback_file(conn, version=9)
            conn.rollback()

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT allowed_content_sha256 FROM ingestion_control.scope_authorizations "
                    "WHERE authorization_id = 'rollback-v2'"
                )
                row = cur.fetchone()
                cur.execute(
                    "SELECT version FROM ingestion_control.schema_migrations WHERE version = 9"
                )
                registered = cur.fetchone()
            assert row == (["1" * 64],)
            assert registered == (9,)

    def test_rollback_009_preserves_v1_rows_restores_v1_schema_and_reapplies(
        self, pg_container: dict[str, str]
    ) -> None:
        bootstrap = _run_bootstrap(pg_container)
        assert bootstrap.returncode == 0, bootstrap.stderr

        with psycopg.connect(_superuser_dsn(pg_container)) as conn:
            _insert_minimal_authorization(
                conn,
                authorization_id="rollback-v1",
                protocol_version="LOT41A-V1",
                allowed_content_sha256=None,
            )
            _apply_rollback_file(conn, version=9)

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'ingestion_control.scope_authorizations'::regclass "
                    "AND conname = 'scope_authorizations_protocol_version_valid'"
                )
                protocol_constraint = cur.fetchone()
                cur.execute(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_schema = 'ingestion_control' "
                    "AND table_name = 'scope_authorizations' "
                    "AND column_name = 'allowed_content_sha256'"
                )
                allowlist_column = cur.fetchone()
                cur.execute(
                    "SELECT to_regprocedure("
                    "'ingestion_control._scope_authorizations_content_allowlist_canonical(text[])')"
                )
                helper = cur.fetchone()
                cur.execute(
                    "SELECT protocol_version FROM ingestion_control.scope_authorizations "
                    "WHERE authorization_id = 'rollback-v1'"
                )
                row = cur.fetchone()

            assert protocol_constraint == ("CHECK ((protocol_version = 'LOT41A-V1'::text))",)
            assert allowlist_column is None
            assert helper == (None,)
            assert row == ("LOT41A-V1",)

        reapply = _run_bootstrap(pg_container)
        assert reapply.returncode == 0, reapply.stderr
        assert "MIGRATIONS_APPLIED=1" in reapply.stdout
        assert "SCHEMA_HEAD=9" in reapply.stdout

        with psycopg.connect(_superuser_dsn(pg_container)) as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT protocol_version, allowed_content_sha256 "
                "FROM ingestion_control.scope_authorizations "
                "WHERE authorization_id = 'rollback-v1'"
            )
            row_after_reapply = cur.fetchone()
        assert row_after_reapply == ("LOT41A-V1", None)
