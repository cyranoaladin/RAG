"""Contrat statique de la migration additive 020 d'identité de contrôle V2."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "infra/postgres/ingestion_control"
NAME = "020_successor_control_resource_identity"
MIGRATION = ROOT / "migrations" / f"{NAME}.sql"
ROLLBACK = ROOT / "rollbacks" / f"{NAME}.down.sql"


def test_head_and_files() -> None:
    assert (ROOT / "migrations/HEAD").read_text() == f"{NAME}\n"
    assert MIGRATION.is_file()
    assert ROLLBACK.is_file()


def test_predecessor_columns_keep_their_meaning_and_v2_is_complete() -> None:
    sql = MIGRATION.read_text()
    assert "successor_resource_id UUID" in sql
    assert "successor_artifact_id UUID" in sql
    assert "SEALED-RELEASE-ADOPTION-V1" in sql
    assert "SEALED-RELEASE-ADOPTION-V2" in sql
    assert "successor_resource_id <> resource_id" in sql
    assert "successor_artifact_id <> artifact_id" in sql


def test_both_artifact_owners_are_proven_by_composite_fks() -> None:
    sql = MIGRATION.read_text()
    assert "UNIQUE (artifact_id, resource_id)" in sql
    assert re.search(
        r"FOREIGN KEY \(artifact_id, resource_id\)\s+REFERENCES "
        r"ingestion_control\.artifacts \(artifact_id, resource_id\)", sql
    )
    assert re.search(
        r"FOREIGN KEY \(successor_artifact_id, successor_resource_id\)\s+"
        r"REFERENCES ingestion_control\.artifacts \(artifact_id, resource_id\)", sql
    )


def test_rollback_refuses_any_v2_evidence_under_lock() -> None:
    sql = ROLLBACK.read_text()
    assert sql.index("LOCK TABLE ingestion_control.sealed_release_adoptions") < sql.index(
        "rollback 020 refused"
    ) < sql.index("DROP COLUMN")
    assert "successor_resource_id IS NOT NULL" in sql
    assert "successor_artifact_id IS NOT NULL" in sql
    assert "SET LOCAL lock_timeout" in sql
    for path in (MIGRATION, ROLLBACK):
        assert not re.search(r"^\s*(BEGIN|COMMIT)\s*;", path.read_text(), re.M)
