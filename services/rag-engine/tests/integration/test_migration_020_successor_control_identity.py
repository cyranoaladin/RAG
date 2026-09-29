"""Migration 020 sur PostgreSQL jetable, avec les runners canoniques."""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

ENGINE_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from _pg_authority import (  # noqa: E402
    PG_SUPERUSER,
    PG_SUPERUSER_PASSWORD,
    adopter_dsn,
    attestor_dsn,
    requires_docker,
    start_ingestion_control_postgres,
    superuser_dsn,
)
from test_migration_016_release_identity import ressource_reelle  # noqa: E402
from test_migration_018_sealed_release_adoption import (  # noqa: E402
    _plan,
    lignes_acquises,
)

from ingestor.ingestion_control.sealed_release_adoption import persist_adoption  # noqa: E402

pytestmark = [pytest.mark.integration, requires_docker]
SCRIPTS = ENGINE_ROOT / "infra/scripts"


@pytest.fixture()
def pg() -> Iterator[dict[str, str]]:
    yield from start_ingestion_control_postgres("migration-020")


def _runner(pg: dict[str, str], name: str, *, target: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": os.environ["PATH"],
        "PGHOST": pg["host"], "PGPORT": pg["port"],
        "PGUSER": PG_SUPERUSER, "PGPASSWORD": PG_SUPERUSER_PASSWORD,
        "PGDATABASE": pg["dbname"],
    }
    if target is not None:
        env["TARGET_VERSION"] = target
    return subprocess.run(
        [str(SCRIPTS / name)], cwd=ENGINE_ROOT, env=env,
        capture_output=True, text=True, check=False,
    )


def _head(conn: psycopg.Connection[Any]) -> int:
    return conn.execute(
        "SELECT max(version) FROM ingestion_control.schema_migrations"
    ).fetchone()[0]


def _copy_row(
    conn: psycopg.Connection[Any], table: str, source_id: uuid.UUID,
    primary_key: str, replacements: dict[str, object],
) -> None:
    columns = [
        row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='ingestion_control' AND table_name=%s "
            "ORDER BY ordinal_position", (table,)
        ).fetchall()
    ]
    row = conn.execute(
        sql.SQL("SELECT * FROM ingestion_control.{} WHERE {}=%s").format(
            sql.Identifier(table), sql.Identifier(primary_key)
        ), (source_id,),
    ).fetchone()
    assert row is not None
    values = dict(zip(columns, row, strict=True))
    values.update(replacements)
    conn.execute(
        sql.SQL("INSERT INTO ingestion_control.{} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, values)),
            sql.SQL(", ").join(sql.Placeholder() for _ in values),
        ),
        tuple(Jsonb(value) if isinstance(value, dict) else value for value in values.values()),
    )


def _adoption_row(
    pg: dict[str, str], *, version: str = "SEALED-RELEASE-ADOPTION-V2"
) -> tuple[uuid.UUID, uuid.UUID]:
    fixture = ressource_reelle.__wrapped__(pg)  # type: ignore[attr-defined]
    predecessor_resource, predecessor_artifact = next(fixture)
    successor_resource, successor_artifact = uuid.uuid4(), uuid.uuid4()
    with psycopg.connect(superuser_dsn(pg)) as conn:
        _copy_row(conn, "resources", predecessor_resource, "resource_id", {
            "resource_id": successor_resource,
            "dedup_key": f"migration-020-successor-{successor_resource}",
        })
        _copy_row(conn, "artifacts", predecessor_artifact, "artifact_id", {
            "artifact_id": successor_artifact,
            "resource_id": successor_resource,
        })
        row = {
            "adoption_id": uuid.uuid4(),
            "adoption_version": version,
            "release_id": "test-successor-v2",
            "release_manifest_sha256": "2" * 64,
            "artifacts_release_sha256": "3" * 64,
            "candidate_inventory_sha256": "4" * 64,
            "artifact_transfer_manifest_sha256": "5" * 64,
            "currentness_evidence_sha256": "6" * 64,
            "pii_evidence_sha256": "7" * 64,
            "predecessor_release_id": "test-predecessor-v1",
            "predecessor_release_manifest_sha256": "8" * 64,
            "resource_id": predecessor_resource,
            "artifact_id": predecessor_artifact,
            "successor_resource_id": (
                successor_resource if version == "SEALED-RELEASE-ADOPTION-V2" else None
            ),
            "successor_artifact_id": (
                successor_artifact if version == "SEALED-RELEASE-ADOPTION-V2" else None
            ),
            "content_sha256": "a" * 64,
            "collection": "rag_nexus_nsi_terminale_specialite",
            "placement_id": "migration-020-placement",
            "currentness": "current",
            "adopted_by": "migration-020-test",
            "adoption_digest": "b" * 64,
        }
        conn.execute(
            sql.SQL("INSERT INTO ingestion_control.sealed_release_adoptions ({}) "
                    "VALUES ({})").format(
                sql.SQL(", ").join(map(sql.Identifier, row)),
                sql.SQL(", ").join(sql.Placeholder() for _ in row),
            ), tuple(row.values()),
        )
    fixture.close()
    return successor_resource, successor_artifact


def test_rollback_to_018_then_upgrade_and_replay_via_runners(pg: dict[str, str]) -> None:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        assert _head(conn) == 20
    rollback = _runner(pg, "rollback_ingestion_control_schema.sh", target="18")
    assert rollback.returncode == 0, rollback.stderr
    assert "SCHEMA_HEAD=18" in rollback.stdout
    with psycopg.connect(superuser_dsn(pg)) as conn:
        assert _head(conn) == 18
        assert conn.execute(
            "SELECT count(*) FROM information_schema.columns WHERE "
            "table_schema='ingestion_control' AND table_name='sealed_release_adoptions' "
            "AND column_name='successor_resource_id'"
        ).fetchone()[0] == 0
    fixture = lignes_acquises.__wrapped__(pg)  # type: ignore[attr-defined]
    contents = next(fixture)
    with psycopg.connect(attestor_dsn(pg)) as conn:
        assert persist_adoption(conn, lignes=_plan(conn, contents), adopted_by="banc") == (2, 0)
    fixture.close()
    upgrade = _runner(pg, "bootstrap_ingestion_control_schema.sh")
    assert upgrade.returncode == 0, upgrade.stderr
    assert "SCHEMA_HEAD=20" in upgrade.stdout
    with psycopg.connect(superuser_dsn(pg)) as conn:
        rows = conn.execute(
            "SELECT adoption_version, successor_resource_id, successor_artifact_id "
            "FROM ingestion_control.sealed_release_adoptions"
        ).fetchall()
        assert rows == [("SEALED-RELEASE-ADOPTION-V1", None, None)] * 2
    replay = _runner(pg, "bootstrap_ingestion_control_schema.sh")
    assert replay.returncode == 0, replay.stderr
    assert "SCHEMA_HEAD=20" in replay.stdout


def test_v2_row_owns_its_artifact_and_blocks_rollback(pg: dict[str, str]) -> None:
    successor_resource, successor_artifact = _adoption_row(pg)
    with psycopg.connect(superuser_dsn(pg)) as conn:
        assert conn.execute(
            "SELECT a.resource_id FROM ingestion_control.artifacts a "
            "WHERE a.artifact_id=%s", (successor_artifact,)
        ).fetchone()[0] == successor_resource
        assert _head(conn) == 20
    rollback = _runner(pg, "rollback_ingestion_control_schema.sh", target="19")
    assert rollback.returncode != 0
    assert "rollback 020 refused" in rollback.stderr
    with psycopg.connect(superuser_dsn(pg)) as conn:
        assert _head(conn) == 20
        assert conn.execute(
            "SELECT count(*) FROM ingestion_control.sealed_release_adoptions "
            "WHERE successor_resource_id=%s", (successor_resource,)
        ).fetchone()[0] == 1


def test_v1_row_remains_historical_and_rollback_preserves_it(pg: dict[str, str]) -> None:
    _adoption_row(pg, version="SEALED-RELEASE-ADOPTION-V1")
    with psycopg.connect(superuser_dsn(pg)) as conn:
        row = conn.execute(
            "SELECT adoption_version, successor_resource_id, successor_artifact_id "
            "FROM ingestion_control.sealed_release_adoptions"
        ).fetchone()
        assert row == ("SEALED-RELEASE-ADOPTION-V1", None, None)
    rollback = _runner(pg, "rollback_ingestion_control_schema.sh", target="19")
    assert rollback.returncode == 0, rollback.stderr
    with psycopg.connect(superuser_dsn(pg)) as conn:
        assert _head(conn) == 19
        assert conn.execute(
            "SELECT adoption_version FROM ingestion_control.sealed_release_adoptions"
        ).fetchone()[0] == "SEALED-RELEASE-ADOPTION-V1"


def test_v2_partial_identity_and_wrong_artifact_owner_are_refused(
    pg: dict[str, str],
) -> None:
    successor_resource, _ = _adoption_row(pg)
    with psycopg.connect(superuser_dsn(pg)) as conn:
        original = conn.execute(
            "SELECT adoption_id FROM ingestion_control.sealed_release_adoptions "
            "WHERE successor_resource_id=%s", (successor_resource,)
        ).fetchone()[0]
        with pytest.raises(psycopg.errors.CheckViolation) as exc:
            _copy_row(conn, "sealed_release_adoptions", original, "adoption_id", {
                "adoption_id": uuid.uuid4(), "release_id": "test-successor-other-v2",
                "successor_artifact_id": None,
            })
        assert exc.value.diag.constraint_name == "sealed_release_adoptions_version_identity_shape"
        conn.rollback()
        artifact = conn.execute(
            "SELECT successor_artifact_id FROM ingestion_control.sealed_release_adoptions "
            "WHERE adoption_id=%s", (original,)
        ).fetchone()[0]
        other_owner = uuid.uuid4()
        _copy_row(conn, "resources", successor_resource, "resource_id", {
            "resource_id": other_owner,
            "dedup_key": f"migration-020-other-{other_owner}",
        })
        other_artifact = uuid.uuid4()
        _copy_row(conn, "artifacts", artifact, "artifact_id", {
            "artifact_id": other_artifact,
            "resource_id": other_owner,
        })
        with pytest.raises(psycopg.errors.ForeignKeyViolation) as exc:
            _copy_row(conn, "sealed_release_adoptions", original, "adoption_id", {
                "adoption_id": uuid.uuid4(), "release_id": "test-successor-other-v2",
                "successor_artifact_id": other_artifact,
                "successor_resource_id": uuid.uuid4(),
            })
        assert exc.value.diag.constraint_name == "sealed_release_adoptions_successor_artifact_owner"


def test_adopter_role_can_only_append_its_control_facts(pg: dict[str, str]) -> None:
    with psycopg.connect(superuser_dsn(pg)) as conn:
        for table in (
            "ingestion_runs", "resources", "artifacts", "workflow_events",
            "artifact_attributions", "sealed_release_adoptions",
        ):
            relation = f"ingestion_control.{table}"
            assert conn.execute(
                "SELECT has_table_privilege('ingestion_control_adopter', %s, 'INSERT')",
                (relation,),
            ).fetchone()[0]
            for privilege in ("UPDATE", "DELETE", "TRUNCATE"):
                assert not conn.execute(
                    "SELECT has_table_privilege('ingestion_control_adopter', %s, %s)",
                    (relation, privilege),
                ).fetchone()[0]
        for table in ("jobs", "publication_attestations", "scope_authorizations"):
            assert not conn.execute(
                "SELECT has_table_privilege('ingestion_control_adopter', %s, 'INSERT')",
                (f"ingestion_control.{table}",),
            ).fetchone()[0]
    with psycopg.connect(adopter_dsn(pg)) as conn:
        assert conn.execute("SELECT current_user").fetchone()[0] == "ingestion_control_adopter"
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("UPDATE ingestion_control.resources SET last_error='forbidden'")
