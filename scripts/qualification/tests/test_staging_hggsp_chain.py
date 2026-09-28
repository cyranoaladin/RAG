"""Gardes purs du complément HGGSP ; aucune base ni aucun hôte réel."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import json
import os
import socket
import subprocess
import sys
import time
from uuid import uuid4
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location(
    "staging_hggsp_complementary", ROOT / "scripts/go_live/staging_hggsp_complementary.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def observations() -> dict:
    return {
        "database": "ragdb_profile_gate_v4",
        "v4": {"collections": 9, "unique_artifacts": 263, "placements": 405, "unique_chunks": 5678},
        "successor": {"collections": 0, "unique_artifacts": 0, "placements": 0, "unique_chunks": 0},
        "old_v4_hggsp_jobs": 74,
        "old_v4_hggsp_jobs_sha256": module.OLD_JOBS_SHA256,
        "v4_active_attestations": 479,
        "v4_published_jobs": 405,
        "successor_jobs": 0,
        "successor_succeeded_jobs": 0,
        "successor_attestations": 0,
        "successor_collections": list(module.COLLECTIONS),
        "review_262": {"state": "open", "draft": False, "approved": True, "head_sha": module.REVIEW_HEAD},
        "legacy_unchanged": True,
    }


def test_preflight_initial_accepts_exact_state() -> None:
    module.exiger_preflight(observations(), phase="prepare")


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("v4", "unique_chunks"), 5677),
        (("successor", "placements"), 1),
        (("old_v4_hggsp_jobs",), 73),
        (("old_v4_hggsp_jobs_sha256",), "0" * 64),
        (("v4_active_attestations",), 478),
        (("v4_published_jobs",), 404),
        (("successor_jobs",), 1),
        (("successor_collections",), ["rag_nexus_hggsp_premiere_specialite", "third"]),
        (("review_262", "state"), "closed"),
        (("review_262", "approved"), False),
        (("review_262", "head_sha"), "0" * 40),
        (("legacy_unchanged",), False),
    ],
)
def test_preflight_rejects_drift(path: tuple[str, ...], value: object) -> None:
    data = observations()
    target = data
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(module.HGGSPRefused):
        module.exiger_preflight(data, phase="prepare")


def test_enqueue_and_publication_cardinalities() -> None:
    data = observations()
    data["successor_attestations"] = 74
    module.exiger_preflight(data, phase="enqueue")
    data["successor_jobs"] = 74
    module.exiger_preflight(data, phase="publish")
    data["successor_jobs"] = 75
    with pytest.raises(module.HGGSPRefused):
        module.exiger_preflight(data, phase="publish")


def test_replay_after_record_or_enqueue_commit_is_idempotently_admissible() -> None:
    data = observations()
    data["successor_attestations"] = 74
    module.exiger_preflight(data, phase="record_replay")
    module.exiger_preflight(data, phase="enqueue_replay")
    data["successor_jobs"] = 74
    module.exiger_preflight(data, phase="enqueue_replay")
    with pytest.raises(module.HGGSPRefused):
        module.exiger_preflight(data, phase="enqueue")


def test_attestation_stage_requires_74_active_attestations() -> None:
    data = observations()
    with pytest.raises(module.HGGSPRefused):
        module.exiger_preflight(data, phase="attested")
    data["successor_attestations"] = 74
    module.exiger_preflight(data, phase="attested")


def test_union_requires_exact_successor_and_preserves_v4() -> None:
    data = observations()
    data["successor_attestations"] = data["successor_jobs"] = 74
    data["successor"] = dict(module.EXPECTED_SUCCESSOR)
    data["union"] = dict(module.EXPECTED_UNION)
    data["successor_succeeded_jobs"] = 74
    module.exiger_preflight(data, phase="verify")
    data["successor_succeeded_jobs"] = 73
    with pytest.raises(module.HGGSPRefused):
        module.exiger_preflight(data, phase="verify")
    data["successor_succeeded_jobs"] = 74
    data["union"]["unique_chunks"] -= 1
    with pytest.raises(module.HGGSPRefused):
        module.exiger_preflight(data, phase="verify")


def test_historical_snapshot_digest_must_be_measured_twice() -> None:
    assert module.legacy_unchanged("a" * 64, "a" * 64)
    assert not module.legacy_unchanged("a" * 64, "b" * 64)
    with pytest.raises(module.HGGSPRefused):
        module.legacy_unchanged("a" * 64, "")


def _allow_synthetic_old_jobs(monkeypatch: pytest.MonkeyPatch) -> None:
    old = [{
        "job_id": str(i), "attestation_id": f"v4-{i}", "status": "queued",
        "attempt_count": 0, "max_attempts": 3, "next_attempt_at": None,
        "last_error": None, "leased": False,
    } for i in range(74)]
    monkeypatch.setattr(module, "OLD_JOBS_SHA256", module.old_job_fingerprint(old))
    monkeypatch.setattr(module, "_rows", lambda _conn, _sql, params=(): old if params[0] == module.V4_RELEASE else [])


@pytest.mark.parametrize("count", [73, 75])
def test_enqueue_rejects_wrong_successor_count_without_creating_jobs(
    count: int, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_synthetic_old_jobs(monkeypatch)
    class Cursor:
        def __init__(self, rows: list[tuple]) -> None:
            self.rows = rows

        def fetchone(self) -> tuple[str, str]:
            return (module.DATABASE, "ingestion_control_app")

        def fetchall(self) -> list[tuple]:
            return self.rows

    class Connection:
        def __init__(self) -> None:
            self.statements: list[str] = []

        def execute(self, sql: str, params: tuple = ()) -> Cursor:
            self.statements.append(sql)
            rows = [
                (f"new-att-{i}", f"new-resource-{i}", f"artifact-{i}",
                 module.COLLECTIONS[i % 2], "run-successor", 1, "NEEDS_REVIEW")
                for i in range(count)
            ]
            return Cursor(rows)

    conn = Connection()
    created: list[dict] = []
    with pytest.raises(module.HGGSPRefused):
        module.enqueue_successor(conn, create_job=lambda *_a, **kw: created.append(kw))
    assert created == []
    assert all("UPDATE" not in sql.upper() and "DELETE" not in sql.upper() for sql in conn.statements)


def test_enqueue_creates_74_new_attestation_keys_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _allow_synthetic_old_jobs(monkeypatch)
    initial_rows = module._rows
    keys: list[str] = []
    monkeypatch.setattr(
        module, "_rows",
        lambda conn, sql, params=(): [
            {"job_id": f"job-{i}", "attestation_id": f"successor-att-{i}", "status": "queued"}
            for i in range(74)
        ] if params and params[0] == module.RELEASE and len(keys) == 74
        else initial_rows(conn, sql, params),
    )
    class Cursor:
        def __init__(self, rows: list[tuple]) -> None:
            self.rows = rows

        def fetchone(self) -> tuple[str, str]:
            return (module.DATABASE, "ingestion_control_app")

        def fetchall(self) -> list[tuple]:
            return self.rows

    class Connection:
        def execute(self, _sql: str, _params: tuple = ()) -> Cursor:
            return Cursor([
                (f"successor-att-{i}", f"resource-{i}", f"artifact-{i}",
                 module.COLLECTIONS[i % 2], "run", 1, "NEEDS_REVIEW")
                for i in range(74)
            ])

    def create(_conn: object, **kwargs: object) -> tuple[None, bool]:
        keys.append(str(kwargs["dedup_key"]))
        return None, True

    result = module.enqueue_successor(Connection(), create_job=create)
    assert result == {"created": 74, "already_queued": 0}
    assert len(set(keys)) == 74
    assert all(key.startswith("publication:successor-att-") for key in keys)


def test_enqueue_refuses_dedup_returns_without_74_relational_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_synthetic_old_jobs(monkeypatch)

    class Cursor:
        def fetchone(self) -> tuple[str, str]:
            return module.DATABASE, "ingestion_control_app"

        def fetchall(self) -> list[tuple[str, str, str, str, str, int, str]]:
            return [
                (f"successor-att-{i}", f"resource-{i}", f"artifact-{i}",
                 module.COLLECTIONS[i % 2], "run", 1, "NEEDS_REVIEW")
                for i in range(74)
            ]

    class Connection:
        def execute(self, _sql: str, _params: tuple = ()) -> Cursor:
            return Cursor()

    with pytest.raises(module.HGGSPRefused, match="relationnels"):
        module.enqueue_successor(Connection(), create_job=lambda *_a, **_kw: (None, False))


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_enqueue_replay_never_creates_second_job_for_existing_attestations(
    monkeypatch: pytest.MonkeyPatch, status: str,
) -> None:
    _allow_synthetic_old_jobs(monkeypatch)
    original_rows = module._rows
    existing = [
        {"job_id": f"job-{i}", "attestation_id": f"successor-att-{i}",
         "status": status if i == 0 else "queued"}
        for i in range(74)
    ]
    monkeypatch.setattr(
        module, "_rows",
        lambda conn, sql, params=(): existing if params and params[0] == module.RELEASE
        else original_rows(conn, sql, params),
    )

    class Cursor:
        def fetchone(self) -> tuple[str, str]:
            return module.DATABASE, "ingestion_control_app"

        def fetchall(self) -> list[tuple[str, str, str, str, str, int, str]]:
            return [
                (f"successor-att-{i}", f"resource-{i}", f"artifact-{i}",
                 module.COLLECTIONS[i % 2], "run", 1, "NEEDS_REVIEW")
                for i in range(74)
            ]

    class Connection:
        def execute(self, _sql: str, _params: tuple = ()) -> Cursor:
            return Cursor()

    created: list[object] = []
    if status == "failed":
        with pytest.raises(module.HGGSPRefused, match="statut"):
            module.enqueue_successor(Connection(), create_job=lambda *_a, **kw: created.append(kw))
    else:
        assert module.enqueue_successor(
            Connection(), create_job=lambda *_a, **kw: created.append(kw)
        ) == {"created": 0, "already_queued": 74}
    assert not created


def test_enqueue_refuses_changed_old_jobs_before_any_creation(monkeypatch: pytest.MonkeyPatch) -> None:
    class Connection:
        def execute(self, _sql: str, _params: tuple = ()) -> object:
            class Cursor:
                @staticmethod
                def fetchone() -> tuple[str, str]:
                    return module.DATABASE, "ingestion_control_app"

            return Cursor()

    monkeypatch.setattr(module, "_rows", lambda *_args: [{"job_id": "tampered"}])
    created: list[object] = []
    with pytest.raises(module.HGGSPRefused, match="anciens jobs V4"):
        module.enqueue_successor(Connection(), create_job=lambda *_a, **kw: created.append(kw))
    assert created == []


def test_direct_enqueue_cli_is_closed() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/go_live/staging_hggsp_complementary.py"),
         "--enqueue-successor"],
        cwd=ROOT, capture_output=True, text=True, check=False,
    )
    assert result.returncode != 0
    assert "unrecognized arguments: --enqueue-successor" in result.stderr


def test_worker_arguments_use_exact_two_collections_and_bounded_pacing() -> None:
    sys.path.insert(0, str(ROOT / "scripts/go_live"))
    try:
        args = module.worker_arguments(ROOT, transfer_sha256="a" * 64, embedding_root="/models/test")
    finally:
        sys.path.pop(0)
    # Charge uniquement les définitions du parseur canonique : importer le paquet
    # déclencherait toutes les dépendances du worker, inutiles pour cette preuve.
    worker_dir = ROOT / "services/rag-engine/src/ingestor/ingestion_worker"
    cli_tree = ast.parse((worker_dir / "multilevel_publication_resume_cli.py").read_text())
    authority_tree = ast.parse((worker_dir / "multilevel_runtime_authority.py").read_text())
    review_tree = ast.parse((worker_dir / "runtime_authority.py").read_text())
    names = {"_positive_int", "_finite_non_negative_float", "_non_blank", "_build_arg_parser"}
    definitions = [node for node in cli_tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    definitions += [node for node in authority_tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "add_multilevel_runtime_authority_arguments"]
    definitions += [node for node in review_tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "add_review_authority_arguments"]
    authority_args = next(node.value for node in authority_tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name)
                                  and target.id == "_MULTILEVEL_RUNTIME_FILE_ARGUMENTS"
                                  for target in node.targets))
    def review_args(name: str) -> object:
        value = next(node.value for node in review_tree.body if isinstance(node, ast.Assign)
                     and any(isinstance(target, ast.Name) and target.id == name for target in node.targets))
        return ast.literal_eval(value)

    namespace = {
        "argparse": argparse,
        "Path": Path,
        "DEFAULT_POLL_INTERVAL_S": 5.0,
        "DEFAULT_RATE_LIMIT_MAX_WAIT_S": 900.0,
        "DEFAULT_MAX_CONSECUTIVE_RATE_LIMITS": 3,
        "_MULTILEVEL_RUNTIME_FILE_ARGUMENTS": ast.literal_eval(authority_args),
        "_REVIEW_AUTHORITY_DIGEST_ONLY_ARGUMENTS": review_args("_REVIEW_AUTHORITY_DIGEST_ONLY_ARGUMENTS"),
        "_REVIEW_AUTHORITY_ARGUMENTS": review_args("_REVIEW_AUTHORITY_ARGUMENTS"),
    }
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(worker_dir), "exec"), namespace)
    parsed = namespace["_build_arg_parser"]().parse_args(args)
    assert parsed.collection == list(module.COLLECTIONS)
    assert parsed.release_registry_sha256 == module.MIXED_REGISTRY_SHA256
    assert parsed.release_registry_path == Path("/repo") / module.MIXED_REGISTRY
    assert parsed.min_job_interval_s == 60
    assert parsed.rate_limit_max_wait_s == 900
    assert parsed.max_consecutive_rate_limits == 3
    assert parsed.max_idle_polls == 5
    assert parsed.max_iterations == 272


@pytest.mark.skipif(os.environ.get("NEXUS_HGGSP_PG") != "1", reason="PostgreSQL jetable opt-in")
def test_real_postgres_mixed_union_and_read_only() -> None:
    """Un vrai PostgreSQL jetable mesure tout le produit, pas un échantillon."""
    import psycopg

    name = f"nexus-hggsp-chain-{uuid4().hex[:10]}"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    image = "postgres:16-alpine"
    started = subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_PASSWORD=test-only",
         "-p", f"127.0.0.1:{port}:5432", image], capture_output=True, text=True, check=True
    )
    assert started.stdout.strip()
    try:
        dsn = f"postgresql://postgres:test-only@127.0.0.1:{port}/postgres"
        for _ in range(60):
            try:
                with psycopg.connect(dsn):
                    break
            except psycopg.OperationalError:
                time.sleep(0.25)
        else:
            pytest.fail("PostgreSQL jetable indisponible")
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE DATABASE ragdb_profile_gate_v4")
        dsn = f"postgresql://postgres:test-only@127.0.0.1:{port}/ragdb_profile_gate_v4"
        with psycopg.connect(dsn) as conn:
            conn.execute("CREATE TABLE rag_artifacts (artifact_id text)")
            conn.execute("CREATE TABLE rag_artifact_placements (collection text, artifact_id text, placement_id text)")
            conn.execute("CREATE TABLE rag_chunks (artifact_id text, chunk_id text)")
            owners = module.mixed_owners(ROOT)
            v4_collections = sorted(k for k, owner in owners.items() if owner == module.V4_RELEASE)
            artifacts_v4 = [f"v4-{i:03d}" for i in range(263)]
            artifacts_h = [f"h-{i:03d}" for i in range(52)]
            conn.cursor().executemany(
                "INSERT INTO rag_artifacts VALUES (%s)", [(artifact,) for artifact in artifacts_v4 + artifacts_h]
            )
            placements = [
                (v4_collections[i % 9], artifacts_v4[i % 263], f"v4-p-{i}") for i in range(405)
            ] + [
                (module.COLLECTIONS[i % 2], artifacts_h[i % 52], f"h-p-{i}") for i in range(74)
            ]
            conn.cursor().executemany("INSERT INTO rag_artifact_placements VALUES (%s,%s,%s)", placements)
            chunks = [
                (artifacts_v4[i % 263], f"v4-c-{i}") for i in range(5678)
            ] + [
                (artifacts_h[i % 52], f"h-c-{i}") for i in range(2590)
            ]
            conn.cursor().executemany("INSERT INTO rag_chunks VALUES (%s,%s)", chunks)
            conn.commit()
            conn.execute("SET TRANSACTION READ ONLY")
            assert module._counts(conn, owners=owners) == (
                module.EXPECTED_V4, module.EXPECTED_SUCCESSOR, module.EXPECTED_UNION
            )
            with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
                conn.execute("DELETE FROM rag_chunks")
            conn.rollback()
            assert conn.execute("SELECT count(*) FROM rag_chunks").fetchone()[0] == 8268
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, check=False)


@pytest.mark.skipif(os.environ.get("NEXUS_HGGSP_PG") != "1", reason="PostgreSQL jetable opt-in")
def test_real_postgres_enqueue_preserves_same_collection_v4_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Les 74 nouveaux jobs arrivent via les attestations V5 ; V4 reste identique."""
    import psycopg

    name = f"nexus-hggsp-enqueue-{uuid4().hex[:10]}"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_PASSWORD=test-only",
         "-p", f"127.0.0.1:{port}:5432", "postgres:16-alpine"],
        capture_output=True, text=True, check=True,
    )
    try:
        dsn = f"postgresql://postgres:test-only@127.0.0.1:{port}/postgres"
        for _ in range(60):
            try:
                with psycopg.connect(dsn):
                    break
            except psycopg.OperationalError:
                time.sleep(0.25)
        else:
            pytest.fail("PostgreSQL jetable indisponible")
        with psycopg.connect(dsn, autocommit=True) as conn:
            conn.execute("CREATE ROLE ingestion_control_app")
            conn.execute("CREATE DATABASE ragdb_profile_gate_v4")
        dsn = f"postgresql://postgres:test-only@127.0.0.1:{port}/ragdb_profile_gate_v4"
        with psycopg.connect(dsn) as conn:
            conn.execute("CREATE SCHEMA ingestion_control")
            conn.execute("""CREATE TABLE ingestion_control.publication_attestations (
                attestation_id text PRIMARY KEY, resource_id text, artifact_id text,
                collection text, release_id text, invalidated_at timestamptz)""")
            conn.execute("""CREATE TABLE ingestion_control.resources (
                resource_id text PRIMARY KEY, run_id text, state_version integer,
                resource_state text)""")
            conn.execute("""CREATE TABLE ingestion_control.sealed_release_adoptions (
                release_id text, resource_id text, artifact_id text)""")
            conn.execute("""CREATE TABLE ingestion_control.jobs (
                job_id text PRIMARY KEY, job_type text, payload jsonb, status text,
                attempt_count integer, max_attempts integer, next_attempt_at timestamptz,
                last_error text, lease_token text)""")
            for i in range(74):
                collection = module.COLLECTIONS[i % 2]
                conn.execute("INSERT INTO ingestion_control.publication_attestations VALUES (%s,%s,%s,%s,%s,NULL)",
                             (f"old-att-{i}", f"old-resource-{i}", f"old-artifact-{i}",
                              collection, module.V4_RELEASE))
                conn.execute("INSERT INTO ingestion_control.jobs VALUES (%s,'publication_resume',%s::jsonb,'queued',0,3,NULL,NULL,NULL)",
                             (f"old-job-{i}", json.dumps({"publication_attestation_id": f"old-att-{i}"})))
                conn.execute("INSERT INTO ingestion_control.publication_attestations VALUES (%s,%s,%s,%s,%s,NULL)",
                             (f"new-att-{i}", f"resource-{i}", f"artifact-{i}",
                              collection, module.RELEASE))
                conn.execute("INSERT INTO ingestion_control.resources VALUES (%s,%s,1,'NEEDS_REVIEW')",
                             (f"resource-{i}", "run-successor"))
                conn.execute("INSERT INTO ingestion_control.sealed_release_adoptions VALUES (%s,%s,%s)",
                             (module.RELEASE, f"resource-{i}", f"artifact-{i}"))
            conn.execute("GRANT USAGE ON SCHEMA ingestion_control TO ingestion_control_app")
            conn.execute("GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA ingestion_control TO ingestion_control_app")
            conn.commit()
            old_sql = """SELECT j.job_id::text AS job_id,
                j.payload->>'publication_attestation_id' AS attestation_id,
                j.status, j.attempt_count, j.max_attempts, j.next_attempt_at,
                j.last_error, j.lease_token IS NOT NULL AS leased
                FROM ingestion_control.jobs j
                JOIN ingestion_control.publication_attestations pa
                  ON pa.attestation_id::text = j.payload->>'publication_attestation_id'
                WHERE pa.release_id = %s ORDER BY j.job_id"""
            old_before = module._rows(conn, old_sql, (module.V4_RELEASE,))
            monkeypatch.setattr(module, "OLD_JOBS_SHA256", module.old_job_fingerprint(old_before))
            conn.execute("SET ROLE ingestion_control_app")

            def create_job(db: object, **kwargs: object) -> tuple[None, bool]:
                attestation = str(kwargs["payload"]["publication_attestation_id"])
                existing = db.execute(
                    "SELECT 1 FROM ingestion_control.jobs WHERE job_id=%s", (f"successor-{attestation}",)
                ).fetchone()
                if existing:
                    return None, False
                db.execute("""INSERT INTO ingestion_control.jobs
                    VALUES (%s,'publication_resume',%s::jsonb,'queued',0,3,NULL,NULL,NULL)""",
                    (f"successor-{attestation}", json.dumps(kwargs["payload"])))
                return None, True

            assert module.enqueue_successor(conn, create_job=create_job) == {
                "created": 74, "already_queued": 0,
            }
            conn.commit()
            assert module._rows(conn, old_sql, (module.V4_RELEASE,)) == old_before
            assert conn.execute("SELECT count(*) FROM ingestion_control.jobs").fetchone()[0] == 148
            assert module.enqueue_successor(conn, create_job=create_job) == {
                "created": 0, "already_queued": 74,
            }
            assert module._rows(conn, old_sql, (module.V4_RELEASE,)) == old_before
            conn.execute("UPDATE ingestion_control.jobs SET status='succeeded' WHERE job_id=%s",
                         ("successor-new-att-0",))
            assert module.enqueue_successor(conn, create_job=create_job) == {
                "created": 0, "already_queued": 74,
            }
            assert conn.execute("SELECT count(*) FROM ingestion_control.jobs").fetchone()[0] == 148
            conn.execute("UPDATE ingestion_control.jobs SET status='failed' WHERE job_id=%s",
                         ("successor-new-att-0",))
            with pytest.raises(module.HGGSPRefused, match="statut"):
                module.enqueue_successor(conn, create_job=create_job)
            assert conn.execute("SELECT count(*) FROM ingestion_control.jobs").fetchone()[0] == 148
            assert module._rows(conn, old_sql, (module.V4_RELEASE,)) == old_before
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, text=True, check=False)
