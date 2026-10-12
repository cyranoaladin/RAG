"""Mettre en file les placements du successeur public sous C signé et LOT42 live."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import psycopg
from psycopg import IsolationLevel

from ingestor.ingestion_control.attestation import attest_runtime_role
from ingestor.ingestion_control.db import get_ingestion_control_dsn
from ingestor.ingestion_control.jobs import find_or_create_job as _find_or_create_job
from ingestor.ingestion_control.release_batch_attestation import (
    MeasuredReleaseBatchFacts,
    measure_release_batch_facts,
    require_facts_match_catalog,
)
from ingestor.public_successor_db_guard import (
    require_public_successor_live_controls,
    require_public_successor_pinned_db,
    require_public_successor_startup_lot42,
)

from .public_text_publication_resume_cli import _verified_runtime

_JOB_TYPE = "publication_resume"
_STATE = "NEEDS_REVIEW"
_ROWS = """
SELECT pa.attestation_id, pa.resource_id, pa.artifact_id, pa.content_sha256,
       pa.collection, r.run_id, r.state_version, r.resource_state, a.run_id
  FROM ingestion_control.publication_attestations pa
  JOIN ingestion_control.resources r ON r.resource_id = pa.resource_id
  JOIN ingestion_control.artifacts a ON a.artifact_id = pa.artifact_id
 WHERE pa.release_id = %s AND pa.release_manifest_sha256 = %s
   AND pa.protocol_version = 'LOT42-RELEASE-BATCH-V1'
   AND pa.invalidated_at IS NULL
   AND a.resource_id = pa.resource_id
   AND a.run_id = r.run_id
   AND a.sha256 = pa.content_sha256
   AND a.payload->>'release_id' = %s
   AND r.collection = pa.collection
 ORDER BY pa.collection, pa.resource_id
"""


def enqueue_public_successor_jobs(
    conn: Any,
    rows: Sequence[tuple[object, ...]],
    *,
    facts: MeasuredReleaseBatchFacts,
    collections: set[str],
    expected_placements: int,
    find_or_create_job: Callable[..., tuple[UUID, bool]] = _find_or_create_job,
) -> int:
    """Valider toute la population avant le premier INSERT, puis exiger du neuf."""
    expected: Mapping[UUID, tuple[UUID, str, str, str]] = facts.par_ressource
    if (
        expected_placements <= 0 or len(expected) != expected_placements
        or len(rows) != expected_placements or not collections
    ):
        raise ValueError("public LOT42 placement population incomplete")
    seen_resources: set[UUID] = set()
    seen_attestations: set[UUID] = set()
    observed_collections: set[str] = set()
    for row in rows:
        if len(row) != 9:
            raise ValueError("public LOT42 job row malformed")
        attestation, resource, artifact, sha, collection, run, version, state, artifact_run = row
        if (
            not isinstance(attestation, UUID) or not isinstance(resource, UUID)
            or not isinstance(artifact, UUID) or not isinstance(run, UUID)
            or artifact_run != run
            or not isinstance(sha, str) or not isinstance(collection, str)
            or type(version) is not int or version < 0 or state != _STATE
            or resource in seen_resources or attestation in seen_attestations
            or collection not in collections
            or expected.get(resource, ())[:3] != (artifact, sha, collection)
        ):
            raise ValueError("public LOT42 job target differs from sealed facts")
        seen_resources.add(resource)
        seen_attestations.add(attestation)
        observed_collections.add(collection)
    if seen_resources != set(expected) or observed_collections != collections:
        raise ValueError("public LOT42 job coverage differs from C")
    attestation_ids = [str(row[0]) for row in rows]
    dedup_keys = [f"publication:{attestation_id}" for attestation_id in attestation_ids]
    existing = conn.execute(
        """
        SELECT job_id FROM ingestion_control.jobs
         WHERE payload->>'dedup_key' = ANY(%s)
            OR payload->>'publication_attestation_id' = ANY(%s)
         LIMIT 1
        """,
        (dedup_keys, attestation_ids),
    ).fetchone()
    if existing is not None:
        raise ValueError("public successor publication job already exists")
    for attestation, resource, artifact, _sha, collection, run, version, _state, _artifact_run in rows:
        _, created = find_or_create_job(
            conn, run_id=run, collection=collection, job_type=_JOB_TYPE,
            dedup_key=f"publication:{attestation}", resource_id=resource,
            payload={
                "resource_id": str(resource), "run_id": str(run),
                "expected_state_version": version,
                "publication_attestation_id": str(attestation),
                "artifact_id": str(artifact),
            },
        )
        if not created:
            raise ValueError("public successor publication job already exists")
    return len(rows)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-successor-bundle-root", required=True, type=Path)
    parser.add_argument("--expected-role", required=True)
    args = parser.parse_args(argv)
    root = args.public_successor_bundle_root
    try:
        if args.expected_role != "ingestion_control_app":
            raise ValueError("public enqueue requires ingestion_control_app")
        signed, verdict, authorities = _verified_runtime(root)
        if (
            signed.release_id != verdict.release_id
            or signed.manifest_sha256 != verdict.content_manifest_sha256
            or len(verdict.subject_sha256_by_collection) != 11
            or datetime.now(UTC) >= verdict.expires_at_utc
        ):
            raise ValueError("signed PUBLICATION and C differ or expired")
        with psycopg.connect(get_ingestion_control_dsn()) as conn:
            attest_runtime_role(conn, expected_role=args.expected_role)
            conn.rollback()
            conn.isolation_level = IsolationLevel.SERIALIZABLE
            require_public_successor_pinned_db(conn, verdict, root, signed.target_pin_sha256)
            require_public_successor_startup_lot42(conn, verdict, root)
            require_public_successor_live_controls(conn, verdict)
            facts = measure_release_batch_facts(conn, release_id=verdict.release_id)
            require_facts_match_catalog(facts, authorities.sealed_release_catalog)
            rows = conn.execute(
                _ROWS,
                (verdict.release_id, verdict.content_manifest_sha256, verdict.release_id),
            ).fetchall()
            created = enqueue_public_successor_jobs(
                conn, rows, facts=facts,
                collections=set(verdict.subject_sha256_by_collection),
                expected_placements=verdict.counts["placements"],
            )
            if datetime.now(UTC) >= verdict.expires_at_utc:
                raise ValueError("C expired before job commit")
            conn.commit()
        print(f"PUBLIC_SUCCESSOR_PUBLICATION_JOBS_CREATED={created}")
        return 0
    except Exception as error:  # noqa: BLE001 - frontière d'exécution fail-closed
        print(f"PUBLIC_SUCCESSOR_ENQUEUE_REFUSED: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
