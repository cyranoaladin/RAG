"""Filtre de claim par release, exercé sur PostgreSQL jetable."""

from __future__ import annotations

import json
import secrets
import shutil
import socket
import subprocess
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import psycopg
import pytest

from ingestor.ingestion_control.jobs import claim_job, reap_expired_job_leases

MANIFEST_V4 = "4" * 64
MANIFEST_V5 = "5" * 64


def binding(release: str) -> dict[str, str]:
    return {"release_id": release, "release_manifest_sha256":
            MANIFEST_V4 if release == "v4" else MANIFEST_V5}


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    if not shutil.which("docker") or subprocess.run(
        ["docker", "info"], capture_output=True, check=False
    ).returncode:
        pytest.skip("Docker indisponible")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    name = f"nexus-release-claim-{uuid4().hex[:10]}"
    password = secrets.token_urlsafe(20)
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_USER=claim",
         "-e", f"POSTGRES_PASSWORD={password}", "-e", "POSTGRES_DB=claim",
         "-p", f"{port}:5432", "postgres:16-alpine"],
        check=True, capture_output=True,
    )
    try:
        value = f"host=127.0.0.1 port={port} dbname=claim user=claim password={password}"
        for _ in range(100):
            try:
                with psycopg.connect(value):
                    break
            except psycopg.OperationalError:
                time.sleep(0.1)
        else:
            raise RuntimeError("PostgreSQL jetable indisponible")
        with psycopg.connect(value, autocommit=True) as conn:
            conn.execute("CREATE SCHEMA ingestion_control")
            conn.execute("CREATE TABLE ingestion_control.resources (resource_id uuid PRIMARY KEY, run_id uuid NOT NULL, collection text NOT NULL)")
            conn.execute("CREATE TABLE ingestion_control.artifacts (artifact_id uuid PRIMARY KEY, resource_id uuid NOT NULL, run_id uuid NOT NULL)")
            conn.execute("CREATE TABLE ingestion_control.publication_attestations (attestation_id uuid PRIMARY KEY, resource_id uuid NOT NULL, artifact_id uuid NOT NULL, collection text NOT NULL, release_id text, release_manifest_sha256 text, protocol_version text NOT NULL, invalidated_at timestamptz)")
            conn.execute("CREATE TABLE ingestion_control.jobs (job_id uuid PRIMARY KEY, run_id uuid NOT NULL, resource_id uuid, job_type text NOT NULL, payload jsonb NOT NULL, status text NOT NULL DEFAULT 'queued', attempt_count integer NOT NULL DEFAULT 0, max_attempts integer NOT NULL DEFAULT 3, next_attempt_at timestamptz NOT NULL DEFAULT now(), last_error text, lease_token uuid, lease_expires_at timestamptz, claimed_by text, updated_at timestamptz NOT NULL DEFAULT now())")
        yield value
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)


@pytest.fixture
def conn(dsn: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(dsn, autocommit=True) as database:
        database.execute("TRUNCATE ingestion_control.jobs, ingestion_control.publication_attestations, ingestion_control.artifacts, ingestion_control.resources")
    with psycopg.connect(dsn) as database:
        yield database


def insert_job(
    conn: psycopg.Connection, *, release: str, collection: str = "hggsp_premiere",
    valid: bool = True, payload_overrides: dict[str, str] | None = None,
    manifest_sha256: str | None = None,
) -> tuple[UUID, UUID]:
    job_id, run_id, resource_id, artifact_id, attestation_id = (uuid4() for _ in range(5))
    payload = {
        "run_id": str(run_id), "resource_id": str(resource_id),
        "artifact_id": str(artifact_id), "publication_attestation_id": str(attestation_id),
        "dedup_key": f"publication:{attestation_id}",
    }
    payload.update(payload_overrides or {})
    conn.execute("INSERT INTO ingestion_control.resources VALUES (%s, %s, %s)",
                 (resource_id, run_id, collection))
    conn.execute("INSERT INTO ingestion_control.artifacts VALUES (%s, %s, %s)",
                 (artifact_id, resource_id, run_id))
    if valid:
        conn.execute(
            "INSERT INTO ingestion_control.publication_attestations VALUES (%s,%s,%s,%s,%s,%s,'LOT42-RELEASE-BATCH-V1',NULL)",
            (attestation_id, resource_id, artifact_id, collection, release,
             manifest_sha256 or binding(release)["release_manifest_sha256"]),
        )
    conn.execute(
        "INSERT INTO ingestion_control.jobs (job_id,run_id,resource_id,job_type,payload) VALUES (%s,%s,%s,'publication_resume',%s)",
        (job_id, run_id, resource_id, json.dumps(payload)),
    )
    conn.commit()
    return job_id, attestation_id


def state(conn: psycopg.Connection, job_id: UUID) -> tuple[str, int]:
    return conn.execute(
        "SELECT status, attempt_count FROM ingestion_control.jobs WHERE job_id=%s", (job_id,)
    ).fetchone()


def snapshot(conn: psycopg.Connection, job_id: UUID) -> dict[str, object]:
    raw = conn.execute(
        "SELECT row_to_json(j)::text FROM ingestion_control.jobs j WHERE job_id=%s", (job_id,)
    ).fetchone()[0]
    result = json.loads(raw)
    assert {"status", "attempt_count", "max_attempts", "next_attempt_at", "last_error",
            "lease_token", "lease_expires_at", "claimed_by", "updated_at"} <= result.keys()
    return result


def test_release_bound_claim_isolates_v4_and_successor(conn: psycopg.Connection) -> None:
    old, _ = insert_job(conn, release="v4")
    new, _ = insert_job(conn, release="v5")
    before = snapshot(conn, old)
    claimed = claim_job(conn, owner="successor", job_types=("publication_resume",),
                        collections=("hggsp_premiere",), **binding("v5"))
    assert claimed is not None and claimed.job_id == new
    conn.commit()
    after = snapshot(conn, old)
    assert before == after
    assert state(conn, old) == ("queued", 0)
    assert claim_job(conn, owner="v4", job_types=("publication_resume",), **binding("v4")).job_id == old


@pytest.mark.parametrize("overrides,valid", [
    ({"publication_attestation_id": "not-a-uuid"}, True),
    ({"publication_attestation_id": str(uuid4())}, True),
    ({"resource_id": str(uuid4())}, True),
    ({"run_id": str(uuid4())}, True),
    ({"artifact_id": str(uuid4())}, True),
    ({}, False),
])
def test_forged_or_missing_attestation_stays_queued(
    conn: psycopg.Connection, overrides: dict[str, str], valid: bool,
) -> None:
    job, _ = insert_job(conn, release="v5", payload_overrides=overrides, valid=valid)
    assert claim_job(conn, owner="successor", job_types=("publication_resume",), **binding("v5")) is None
    assert state(conn, job) == ("queued", 0)


def test_invalidated_and_wrong_collection_stay_queued(conn: psycopg.Connection) -> None:
    invalidated, attestation = insert_job(conn, release="v5")
    conn.execute("UPDATE ingestion_control.publication_attestations SET invalidated_at=now() WHERE attestation_id=%s", (attestation,))
    outside, _ = insert_job(conn, release="v5", collection="other")
    assert claim_job(conn, owner="successor", job_types=("publication_resume",),
                     collections=("hggsp_premiere",), **binding("v5")) is None
    assert state(conn, invalidated) == ("queued", 0)
    assert state(conn, outside) == ("queued", 0)


def test_unqualified_claim_preserves_historical_behavior(conn: psycopg.Connection) -> None:
    old, _ = insert_job(conn, release="v4", valid=False)
    assert claim_job(conn, owner="legacy", job_types=("publication_resume",)).job_id == old


def test_two_release_workers_never_claim_each_others_jobs(dsn: str, conn: psycopg.Connection) -> None:
    old, _ = insert_job(conn, release="v4")
    new, _ = insert_job(conn, release="v5")
    def worker(release: str) -> UUID | None:
        with psycopg.connect(dsn) as worker_conn:
            claim = claim_job(worker_conn, owner=release, job_types=("publication_resume",),
                              **binding(release))
            worker_conn.commit()
            return claim.job_id if claim else None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, ("v4", "v5")))
    assert results == [old, new]


def test_successor_reaper_leaves_expired_v4_job_byte_identical(conn: psycopg.Connection) -> None:
    old, _ = insert_job(conn, release="v4")
    new, _ = insert_job(conn, release="v5")
    outside, _ = insert_job(conn, release="v5", collection="other")
    wrong_manifest, _ = insert_job(conn, release="v5", manifest_sha256="a" * 64)
    for job in (old, new, outside, wrong_manifest):
        conn.execute(
            "UPDATE ingestion_control.jobs SET status='running', lease_token=%s, "
            "lease_expires_at=now()-interval '1 minute', claimed_by='prior' WHERE job_id=%s",
            (uuid4(), job),
        )
    conn.commit()
    before = snapshot(conn, old)
    before_outside = snapshot(conn, outside)
    before_wrong_manifest = snapshot(conn, wrong_manifest)
    reaped = reap_expired_job_leases(conn, collections=("hggsp_premiere",), **binding("v5"))
    conn.commit()
    after = snapshot(conn, old)
    after_outside = snapshot(conn, outside)
    after_wrong_manifest = snapshot(conn, wrong_manifest)
    assert before == after
    assert before_outside == after_outside
    assert before_wrong_manifest == after_wrong_manifest
    assert [item.job_id for item in reaped] == [new]


def test_same_release_concurrent_workers_do_not_double_claim(dsn: str, conn: psycopg.Connection) -> None:
    only, _ = insert_job(conn, release="v5")
    def worker(owner: str) -> UUID | None:
        with psycopg.connect(dsn) as worker_conn:
            claimed = claim_job(worker_conn, owner=owner, job_types=("publication_resume",),
                                **binding("v5"))
            worker_conn.commit()
            return claimed.job_id if claimed else None
    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(worker, ("one", "two")))
    assert claimed.count(only) == 1
    assert claimed.count(None) == 1


def test_same_release_wrong_manifest_stays_queued(conn: psycopg.Connection) -> None:
    job, _ = insert_job(conn, release="v5", manifest_sha256="a" * 64)
    assert claim_job(conn, owner="successor", job_types=("publication_resume",), **binding("v5")) is None
    assert state(conn, job) == ("queued", 0)


def test_reaper_rejects_collections_without_release_binding(conn: psycopg.Connection) -> None:
    old, _ = insert_job(conn, release="v4")
    before = snapshot(conn, old)
    with pytest.raises(ValueError, match="collections require release"):
        reap_expired_job_leases(conn, collections=("hggsp_premiere",))
    assert snapshot(conn, old) == before


def test_v4_attestation_id_forged_into_v5_payload_stays_queued(conn: psycopg.Connection) -> None:
    _old, old_attestation = insert_job(conn, release="v4")
    forged, _ = insert_job(
        conn, release="v5", payload_overrides={"publication_attestation_id": str(old_attestation)}
    )
    assert claim_job(conn, owner="successor", job_types=("publication_resume",), **binding("v5")) is None
    assert state(conn, forged) == ("queued", 0)


def test_old_v4_job_swapped_to_valid_v5_attestation_stays_queued(conn: psycopg.Connection) -> None:
    old, _ = insert_job(conn, release="v4")
    _new, new_attestation = insert_job(conn, release="v5")
    conn.execute(
        "UPDATE ingestion_control.jobs SET payload=jsonb_set(jsonb_set(payload, "
        "'{publication_attestation_id}', to_jsonb(%s::text)), '{dedup_key}', "
        "to_jsonb(%s::text)) WHERE job_id=%s",
        (str(new_attestation), f"publication:{new_attestation}", old),
    )
    conn.commit()
    before = snapshot(conn, old)
    assert claim_job(conn, owner="successor", job_types=("publication_resume",), **binding("v5")) is not None
    after = snapshot(conn, old)
    assert before == after


def test_broken_artifact_and_resource_run_lineage_stays_queued(conn: psycopg.Connection) -> None:
    artifact_job, artifact_attestation = insert_job(conn, release="v5")
    resource_job, resource_attestation = insert_job(conn, release="v5")
    conn.execute(
        "UPDATE ingestion_control.artifacts SET run_id=%s WHERE artifact_id=("
        "SELECT artifact_id FROM ingestion_control.publication_attestations WHERE attestation_id=%s)",
        (uuid4(), artifact_attestation),
    )
    conn.execute(
        "UPDATE ingestion_control.resources SET run_id=%s WHERE resource_id=("
        "SELECT resource_id FROM ingestion_control.publication_attestations WHERE attestation_id=%s)",
        (uuid4(), resource_attestation),
    )
    conn.commit()
    assert claim_job(conn, owner="successor", job_types=("publication_resume",), **binding("v5")) is None
    assert state(conn, artifact_job) == ("queued", 0)
    assert state(conn, resource_job) == ("queued", 0)
