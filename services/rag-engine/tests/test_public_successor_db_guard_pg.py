"""Le lecteur public interroge le vrai schéma 020 dans une base jetable."""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import psycopg
import pytest
from psycopg.types.json import Jsonb

ENGINE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_ROOT / "src"))
sys.path.insert(0, str(ENGINE_ROOT / "tests/integration"))

from _pg_authority import (  # noqa: E402
    APP_PASSWORD,
    ATTESTOR_PASSWORD,
    AUTHORITY_PASSWORD,
    MIGRATOR_PASSWORD,
    PG_SUPERUSER,
    PG_SUPERUSER_PASSWORD,
    requires_docker,
    superuser_dsn,
)
from test_migration_016_release_identity import (  # noqa: E402
    AUTORISATION_DE_TEST,
    SHA,
)

from ingestor.ingestion_control.release_batch_attestation import (  # noqa: E402
    measure_release_batch_facts,
)
from ingestor.ingestion_worker.attest_publication_cli import (  # noqa: E402
    _INSERT_ATTESTATION,
    _evenements_de,
)
from ingestor.public_successor_db_guard import (  # noqa: E402
    PublicSuccessorDBRefused,
    require_public_successor_live_controls,
    require_public_successor_startup_lot42,
)

pytestmark = [pytest.mark.integration, requires_docker]
pytest_plugins = ("test_migration_016_release_identity",)

COLLECTION = "rag_nexus_nsi_terminale_specialite"
RELEASE_ID = "student-public-schema-fixture"
MANIFEST = "e" * 64
ARTIFACTS = "4" * 64
INVENTORY = "d" * 64
TRANSFER = "1" * 64
REVIEW_DIGEST = "b" * 64
REVIEW_ID = "public-schema-fixture"
SOURCE_PLACEMENT = "3" * 64
PLACEMENT = "2" * 64
REVIEW_BINDING = ("c" * 40, "d" * 40, "8" * 40, 17, f"NEXUS-TRUSTED-REVIEW-V1:{SHA}")


def _verdict() -> SimpleNamespace:
    return SimpleNamespace(
        release_id=RELEASE_ID,
        content_manifest_sha256=MANIFEST,
        artifact_registry_sha256=ARTIFACTS,
        counts={"subjects": 1, "unique_artifacts": 1, "placements": 1, "unique_chunks": 1},
        authorization_review_evidence_by_id=((
            COLLECTION, AUTORISATION_DE_TEST, SHA, REVIEW_DIGEST,
        ),),
        transfer_manifest_sha256=TRANSFER,
        publication_batch_review_id=REVIEW_ID,
        publication_batch_review_digest=REVIEW_DIGEST,
        publication_batch_review_binding=REVIEW_BINDING,
        expires_at_utc=datetime.now(UTC) + timedelta(minutes=5),
    )


def test_public_lot42_real_schema_and_post_startup_invalidation(
    pg: dict[str, str], ressource_reelle: tuple[object, object],
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une vraie ligne batch passe, puis une invalidation en base ferme la requête."""
    from ingestor import public_successor_db_guard as guard

    resource_id, artifact_id = ressource_reelle
    monkeypatch.setattr(guard, "_expected_lot42_population", lambda *_: (
        {(COLLECTION, SHA, SOURCE_PLACEMENT): (
            PLACEMENT, "official_snapshot", ARTIFACTS, "https://example.test/source", 1,
        )}, INVENTORY,
    ))
    payload = {
        "release_id": RELEASE_ID,
        "release_manifest_sha256": MANIFEST,
        "artifacts_release_sha256": ARTIFACTS,
        "candidate_inventory_sha256": INVENTORY,
        "artifact_transfer_manifest_sha256": TRANSFER,
        "source_placement_id": SOURCE_PLACEMENT,
        "placement_id": PLACEMENT,
        "currentness": "official_snapshot",
        "provenance_artifact_url": "https://example.test/source",
        "chunk_count": 1,
        "scope_authorization_id": AUTORISATION_DE_TEST,
        "review_status": "reviewed",
        "placement_status": "active",
        "media_type": "text/plain; charset=utf-8",
    }
    now = datetime.now(UTC)
    with psycopg.connect(superuser_dsn(pg)) as conn:
        conn.execute(
            "UPDATE ingestion_control.artifacts SET payload = %s "
            "WHERE artifact_id = %s", (Jsonb(payload), artifact_id),
        )
        conn.execute(
            "UPDATE ingestion_control.scope_authorizations SET "
            "authorization_digest = %s, review_evidence = %s, "
            "review_evidence_digest = %s, valid_from = %s, valid_until = %s "
            "WHERE authorization_id = %s",
            (SHA, Jsonb({"protocol_version": "NEXUS-SEALED-TRUSTED-REVIEW-EVIDENCE-V1"}),
             REVIEW_DIGEST, now - timedelta(minutes=1), now + timedelta(minutes=5),
             AUTORISATION_DE_TEST),
        )
        facts = measure_release_batch_facts(conn, release_id=RELEASE_ID)
        assert facts.placements == 1
        assert facts.artifacts_release_sha256 == ARTIFACTS
        conn.execute(
            "INSERT INTO ingestion_control.workflow_events "
            "(run_id, resource_id, event_type, actor) "
            "SELECT run_id, resource_id, 'public_schema_fixture', 'fixture' "
            "FROM ingestion_control.resources WHERE resource_id = %s",
            (resource_id,),
        )
        events = _evenements_de(conn, resource_id)
        assert events
        conn.execute(_INSERT_ATTESTATION, {
            "resource_id": resource_id, "artifact_id": artifact_id,
            "content_sha256": SHA, "canonical_url": None,
            "collection": COLLECTION,
            "scope_authorization_id": AUTORISATION_DE_TEST,
            "profile_id": COLLECTION,
            "profile_version": "v2-livraison-319",
            "profile_fingerprint": facts.artifacts_release_sha256,
            "manifest_digest": facts.release_manifest_sha256,
            "rights_status": "public_allowed", "rights_assessed_at": now,
            "quality_passed": True, "quality_report_digest": "9" * 64,
            "quality_assessed_at": now,
            "gate_passed": True, "gate_name": "public-fixture", "gate_evaluated_at": now,
            "evidence_event_ids": events,
            "review_id": REVIEW_ID,
            "review_artifact_path": (
                f"governance/publication-reviews/{REVIEW_ID}-{REVIEW_DIGEST}.json"
            ),
            "review_artifact_blob_sha": REVIEW_BINDING[2],
            "attestation_digest": REVIEW_DIGEST,
            "human_review_repository": "cyranoaladin/RAG",
            "human_review_pull_request": 325,
            "human_review_base_sha": REVIEW_BINDING[0],
            "human_review_head_sha": REVIEW_BINDING[1],
            "human_review_review_id": REVIEW_BINDING[3],
            "human_review_reviewer": "abenrhouma",
            "human_review_submitted_at": now,
            "human_review_challenge": REVIEW_BINDING[4],
            "protocol_version": "LOT42-RELEASE-BATCH-V1",
            "attributed_facts_digest": None,
            "release_id": RELEASE_ID,
            "release_manifest_sha256": facts.release_manifest_sha256,
            "artifacts_release_sha256": facts.artifacts_release_sha256,
            "candidate_inventory_sha256": facts.candidate_inventory_sha256,
            "artifact_transfer_manifest_sha256": facts.artifact_transfer_manifest_sha256,
            "release_batch_review_digest": REVIEW_DIGEST,
        })
        verdict = _verdict()
        require_public_successor_startup_lot42(conn, verdict, tmp_path)
        require_public_successor_live_controls(conn, verdict)
        conn.execute(
            "UPDATE ingestion_control.publication_attestations SET "
            "invalidated_at = now(), invalidated_reason = 'fixture revocation' "
            "WHERE release_id = %s", (RELEASE_ID,),
        )
        with pytest.raises(PublicSuccessorDBRefused, match="LOT42 invalidation"):
            require_public_successor_live_controls(conn, verdict)
        conn.rollback()


def test_public_reader_real_schema_select_only(pg: dict[str, str]) -> None:
    """Le provisionnement opt-in ne donne jamais d'écriture au lecteur API."""
    role = "banc_public_successor_reader"
    with psycopg.connect(superuser_dsn(pg)) as conn:
        conn.execute(f"CREATE ROLE {role}")
    result = subprocess.run(
        [str(ENGINE_ROOT / "infra/scripts/provision_ingestion_control_roles.sh")],
        env={
            "PATH": os.environ["PATH"],
            "PGHOST": pg["host"], "PGPORT": pg["port"],
            "PGDATABASE": pg["dbname"], "PGUSER": PG_SUPERUSER,
            "PGPASSWORD": PG_SUPERUSER_PASSWORD,
            "INGESTION_CONTROL_MIGRATOR_PASSWORD": MIGRATOR_PASSWORD,
            "INGESTION_CONTROL_APP_PASSWORD": APP_PASSWORD,
            "INGESTION_CONTROL_AUTHORITY_PASSWORD": AUTHORITY_PASSWORD,
            "INGESTION_CONTROL_ATTESTOR_PASSWORD": ATTESTOR_PASSWORD,
            "INGESTION_CONTROL_PUBLIC_READER_ROLE": role,
        },
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stderr
    with psycopg.connect(superuser_dsn(pg)) as conn:
        for table in (
            "resources", "artifacts", "sealed_release_adoptions",
            "scope_authorizations", "publication_attestations",
            "revoked_review_evidence",
        ):
            privileges = conn.execute(
                "SELECT has_table_privilege(%s, %s, 'SELECT'), "
                "has_table_privilege(%s, %s, 'INSERT'), "
                "has_table_privilege(%s, %s, 'UPDATE'), "
                "has_table_privilege(%s, %s, 'DELETE')",
                (role, f"ingestion_control.{table}") * 4,
            ).fetchone()
            assert privileges == (True, False, False, False), table
