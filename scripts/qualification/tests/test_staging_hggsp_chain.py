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
            # Forme V2 (migration 020) : resource_id/artifact_id nomment le
            # PRÉDÉCESSEUR V4 ; les identités successeur sont distinctes.
            conn.execute("""CREATE TABLE ingestion_control.sealed_release_adoptions (
                release_id text, adoption_version text, resource_id text, artifact_id text,
                successor_resource_id text, successor_artifact_id text)""")
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
                # Une ressource successeur V2 naît à state_version 0.
                conn.execute("INSERT INTO ingestion_control.resources VALUES (%s,%s,0,'NEEDS_REVIEW')",
                             (f"resource-{i}", "run-successor"))
                conn.execute("INSERT INTO ingestion_control.sealed_release_adoptions VALUES (%s,%s,%s,%s,%s,%s)",
                             (module.RELEASE, "SEALED-RELEASE-ADOPTION-V2", f"old-resource-{i}",
                              f"old-artifact-{i}", f"resource-{i}", f"artifact-{i}"))
            conn.execute("GRANT USAGE ON SCHEMA ingestion_control TO ingestion_control_app")
            # Privilèges RÉELS du rôle applicatif sur le staging (relus en direct) : SELECT seulement sur les
            # attestations et les adoptions, que le rôle attestor/adopter écrit. Accorder UPDATE partout
            # masquait que `FOR SHARE` sur ces tables exige UPDATE.
            conn.execute("GRANT SELECT ON ingestion_control.publication_attestations,"
                         " ingestion_control.sealed_release_adoptions TO ingestion_control_app")
            conn.execute("GRANT SELECT, INSERT, UPDATE ON ingestion_control.resources,"
                         " ingestion_control.jobs TO ingestion_control_app")
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


# ── filiation V2 : ensembles et identités, pas seulement « 74 » ──────────────


def _lineage_state() -> dict:
    adoptions = [{
        "adoption_version": "SEALED-RELEASE-ADOPTION-V2", "predecessor_release_id": module.V4_RELEASE,
        "collection": module.COLLECTIONS[i % 2],
        "predecessor_resource": f"old-r{i}", "predecessor_artifact": f"old-a{i}",
        "successor_resource": f"new-r{i}", "successor_artifact": f"new-a{i}",
        "resource_state": "NEEDS_REVIEW", "successor_collection": module.COLLECTIONS[i % 2],
        "successor_owner": f"new-r{i}", "successor_sha256": f"{i:064x}", "predecessor_sha256": f"{i:064x}",
    } for i in range(74)]
    v4_active = [{"resource_id": f"old-r{i}", "artifact_id": f"old-a{i}"} for i in range(74)]
    old_jobs = [{"job_id": f"j{i}", "attestation_id": f"a{i}", "status": "queued", "attempt_count": 0,
                 "max_attempts": 3, "next_attempt_at": None, "last_error": None, "leased": False}
                for i in range(74)]
    return {"adoptions": adoptions, "v4_active": v4_active, "old_jobs": old_jobs}


def _verify_lineage(monkeypatch: pytest.MonkeyPatch, state: dict) -> dict:
    monkeypatch.setattr(module, "OLD_JOBS_SHA256", module.old_job_fingerprint(_lineage_state()["old_jobs"]))
    reponses = iter((state["adoptions"], state["v4_active"], state["old_jobs"]))
    monkeypatch.setattr(module, "_rows", lambda *_a, **_k: next(reponses))

    class Connection:
        def execute(self, sql: str, *_a: object) -> object:
            return type("R", (), {"fetchone": lambda _s: (module.DATABASE, "ingestion_control_app")})()

        def rollback(self) -> None:
            pass

    return module.verify_v2_lineage(Connection())


def test_v2_lineage_accepts_exact_distinct_successors(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _verify_lineage(monkeypatch, _lineage_state())["adoptions"] == 74


@pytest.mark.parametrize("mutation", [
    "successor_is_predecessor", "missing_adoption", "v4_attestation_invalidated",
    "version_v1", "bytes_differ", "old_job_changed", "duplicate_successor",
])
def test_v2_lineage_refuses_confused_or_incomplete_identities(
    monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    state = _lineage_state()
    first = state["adoptions"][0]
    if mutation == "successor_is_predecessor":
        first["successor_resource"] = first["successor_owner"] = "old-r0"
    elif mutation == "missing_adoption":
        state["adoptions"].pop()
    elif mutation == "v4_attestation_invalidated":
        state["v4_active"].pop()
    elif mutation == "version_v1":
        first["adoption_version"] = "SEALED-RELEASE-ADOPTION-V1"
    elif mutation == "bytes_differ":
        first["successor_sha256"] = "f" * 64
    elif mutation == "old_job_changed":
        state["old_jobs"][0]["status"] = "running"
    else:
        state["adoptions"][1]["successor_resource"] = first["successor_resource"]
    with pytest.raises(module.HGGSPRefused, match="filiation V2"):
        _verify_lineage(monkeypatch, state)


# ── ensemble gouverné : attestations ACTIVES, jamais l'historique invalidé ───
#
# Le staging porte légitimement deux générations de 74 jobs HGGSP V4 : celle de
# la revue #257 (jobs annulés, attestations invalidées par DH) et celle de #262
# (jobs en file, attestations actives). L'autorité #270 et le contrôle DI ne
# protègent que la seconde. « Historique conservé » n'est pas « ensemble gouverné ».


def _function_calls(name: str) -> set[str]:
    tree = ast.parse((ROOT / "scripts/go_live/staging_hggsp_complementary.py").read_text(encoding="utf-8"))
    function = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
    return {c.func.id for c in ast.walk(function) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}


def test_three_guards_share_one_active_only_selection() -> None:
    source = (ROOT / "scripts/go_live/staging_hggsp_complementary.py").read_text(encoding="utf-8")
    selection = source.split("def _active_v4_hggsp_jobs", 1)[1].split("\ndef ", 1)[0]
    assert "pa.invalidated_at IS NULL" in selection
    assert "status = " not in selection and "j.status IN" not in selection  # le statut reste dans l'empreinte
    for guard in ("inspect_database", "enqueue_successor", "verify_v2_lineage"):
        assert "_active_v4_hggsp_jobs" in _function_calls(guard), guard
    # Aucune sélection ad hoc des anciens jobs ne subsiste hors de la fonction commune.
    rest = source.replace(selection, "")
    assert rest.count("pa.release_id = %s\n           AND pa.collection = ANY(%s)") == 0


def test_old_job_fingerprint_still_covers_status_and_attempts() -> None:
    base = [{"job_id": "j", "attestation_id": "a", "status": "queued", "attempt_count": 0,
             "max_attempts": 3, "next_attempt_at": None, "last_error": None, "leased": False}]
    for change in ({"status": "running"}, {"attempt_count": 1}, {"leased": True}, {"last_error": "x"}):
        assert module.old_job_fingerprint(base) != module.old_job_fingerprint([{**base[0], **change}])


def _pg_active_vs_historical_schema(conn: object) -> None:
    conn.execute("CREATE SCHEMA ingestion_control")
    conn.execute("""CREATE TABLE ingestion_control.publication_attestations (
        attestation_id text PRIMARY KEY, resource_id text, artifact_id text, content_sha256 text,
        collection text, release_id text, release_manifest_sha256 text,
        human_review_repository text, human_review_pull_request integer, human_review_head_sha text,
        invalidated_at timestamptz)""")
    conn.execute("""CREATE TABLE ingestion_control.resources (
        resource_id text PRIMARY KEY, run_id text, state_version integer, resource_state text,
        collection text)""")
    conn.execute("""CREATE TABLE ingestion_control.artifacts (
        artifact_id text PRIMARY KEY, resource_id text, sha256 text)""")
    conn.execute("""CREATE TABLE ingestion_control.sealed_release_adoptions (
        release_id text, adoption_version text, predecessor_release_id text, collection text,
        resource_id text, artifact_id text, successor_resource_id text, successor_artifact_id text)""")
    conn.execute("""CREATE TABLE ingestion_control.jobs (
        job_id text PRIMARY KEY, job_type text, payload jsonb, status text,
        attempt_count integer, max_attempts integer, next_attempt_at timestamptz,
        last_error text, lease_token text, lease_expires_at timestamptz)""")
    conn.execute("""CREATE TABLE ingestion_control.publication_commit_pins (
        publication_attestation_id text, publication_review_pull_request integer,
        publication_review_head_sha text)""")
    for i in range(74):
        collection = module.COLLECTIONS[i % 2]
        sha = f"{i:064x}"
        payload = lambda att: json.dumps({"publication_attestation_id": att})  # noqa: E731
        # Génération #257 : attestations invalidées, jobs annulés (DH).
        conn.execute("INSERT INTO ingestion_control.publication_attestations VALUES (%s,%s,%s,%s,%s,%s,'m','cyranoaladin/RAG',257,'h257',now())",
                     (f"hist-att-{i}", f"old-resource-{i}", f"old-artifact-{i}", sha, collection, module.V4_RELEASE))
        conn.execute("INSERT INTO ingestion_control.jobs VALUES (%s,'publication_resume',%s::jsonb,'cancelled',0,3,NULL,NULL,NULL,NULL)",
                     (f"hist-job-{i}", payload(f"hist-att-{i}")))
        # Génération #262 : mêmes placements, attestations actives, jobs en file.
        conn.execute("INSERT INTO ingestion_control.publication_attestations VALUES (%s,%s,%s,%s,%s,%s,'m','cyranoaladin/RAG',262,'h262',NULL)",
                     (f"act-att-{i}", f"old-resource-{i}", f"old-artifact-{i}", sha, collection, module.V4_RELEASE))
        conn.execute("INSERT INTO ingestion_control.jobs VALUES (%s,'publication_resume',%s::jsonb,'queued',0,3,NULL,NULL,NULL,NULL)",
                     (f"act-job-{i}", payload(f"act-att-{i}")))
        # Successeur V2 : identités distinctes, mêmes octets.
        conn.execute("INSERT INTO ingestion_control.publication_attestations VALUES (%s,%s,%s,%s,%s,%s,'m','cyranoaladin/RAG',262,'h262',NULL)",
                     (f"new-att-{i}", f"resource-{i}", f"artifact-{i}", sha, collection, module.RELEASE))
        conn.execute("INSERT INTO ingestion_control.resources VALUES (%s,'run-old',1,'RETRIEVAL_ELIGIBLE',%s)",
                     (f"old-resource-{i}", collection))
        conn.execute("INSERT INTO ingestion_control.resources VALUES (%s,'run-successor',0,'NEEDS_REVIEW',%s)",
                     (f"resource-{i}", collection))
        conn.execute("INSERT INTO ingestion_control.artifacts VALUES (%s,%s,%s)", (f"old-artifact-{i}", f"old-resource-{i}", sha))
        conn.execute("INSERT INTO ingestion_control.artifacts VALUES (%s,%s,%s)", (f"artifact-{i}", f"resource-{i}", sha))
        conn.execute("INSERT INTO ingestion_control.sealed_release_adoptions VALUES (%s,'SEALED-RELEASE-ADOPTION-V2',%s,%s,%s,%s,%s,%s)",
                     (module.RELEASE, module.V4_RELEASE, collection, f"old-resource-{i}", f"old-artifact-{i}",
                      f"resource-{i}", f"artifact-{i}"))


@pytest.mark.skipif(os.environ.get("NEXUS_HGGSP_PG") != "1", reason="PostgreSQL jetable opt-in")
def test_real_postgres_148_historical_jobs_74_governed(monkeypatch: pytest.MonkeyPatch) -> None:
    """74 invalidés/annulés + 74 actifs/en file : 148 en base, 74 gouvernés."""
    import psycopg

    sys.path.insert(0, str(ROOT / "scripts/go_live"))
    import staging_v4_partial_recovery as di  # noqa: PLC0415

    name = f"nexus-hggsp-active-{uuid4().hex[:10]}"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    subprocess.run(
        ["docker", "run", "-d", "--rm", "--name", name, "-e", "POSTGRES_PASSWORD=test-only",
         "-p", f"127.0.0.1:{port}:5432", "postgres:16-alpine"],
        capture_output=True, text=True, check=True,
    )
    try:
        base = f"postgresql://postgres:test-only@127.0.0.1:{port}"
        for _ in range(60):
            try:
                with psycopg.connect(f"{base}/postgres"):
                    break
            except psycopg.OperationalError:
                time.sleep(0.25)
        else:
            pytest.fail("PostgreSQL jetable indisponible")
        with psycopg.connect(f"{base}/postgres", autocommit=True) as conn:
            conn.execute("CREATE ROLE ingestion_control_app")
            conn.execute("CREATE ROLE rag_reader")
            conn.execute("CREATE DATABASE ragdb_profile_gate_v4")
        dsn = f"{base}/ragdb_profile_gate_v4"
        with psycopg.connect(dsn) as setup:
            _pg_active_vs_historical_schema(setup)
            setup.execute("GRANT USAGE ON SCHEMA ingestion_control TO ingestion_control_app")
            # Privilèges réels du rôle applicatif (cf. test d'enqueue) : lecture seule sur ce que d'autres rôles écrivent.
            setup.execute("GRANT SELECT ON ingestion_control.publication_attestations, ingestion_control.sealed_release_adoptions,"
                          " ingestion_control.artifacts, ingestion_control.publication_commit_pins TO ingestion_control_app")
            setup.execute("GRANT SELECT, INSERT, UPDATE ON ingestion_control.resources,"
                          " ingestion_control.jobs TO ingestion_control_app")
            setup.commit()
        admin = psycopg.connect(dsn, autocommit=True)

        def control() -> object:
            return psycopg.connect(dsn, options="-c role=ingestion_control_app")

        def jobs(prefix: str) -> list[dict]:
            return module._rows(admin, """
                SELECT j.job_id::text AS job_id, j.payload->>'publication_attestation_id' AS attestation_id,
                       j.status, j.attempt_count, j.max_attempts, j.next_attempt_at, j.last_error,
                       j.lease_token IS NOT NULL AS leased
                  FROM ingestion_control.jobs j WHERE j.job_id LIKE %s ORDER BY j.job_id""", (f"{prefix}%",))

        def hist_rows() -> list[dict]:
            return module._rows(admin, "SELECT * FROM ingestion_control.jobs WHERE job_id LIKE %s ORDER BY job_id", ("hist-job-%",)) + \
                module._rows(admin, "SELECT * FROM ingestion_control.publication_attestations WHERE attestation_id LIKE %s ORDER BY attestation_id", ("hist-att-%",))

        # État de départ : 148 jobs V4 HGGSP physiques, 74 gouvernés.
        assert admin.execute("SELECT count(*) FROM ingestion_control.jobs").fetchone()[0] == 148
        assert admin.execute("SELECT count(*) FROM ingestion_control.publication_attestations WHERE release_id=%s AND invalidated_at IS NOT NULL",
                             (module.V4_RELEASE,)).fetchone()[0] == 74
        assert {j["status"] for j in jobs("hist-job-")} == {"cancelled"}
        assert {j["status"] for j in jobs("act-job-")} == {"queued"}
        expected_active = jobs("act-job-")
        monkeypatch.setattr(module, "OLD_JOBS_SHA256", module.old_job_fingerprint(expected_active))
        history_before = hist_rows()

        # 1. La sélection canonique rend 74 (pas 148), avec l'empreinte des 74 actifs.
        with control() as conn:
            selected = module._active_v4_hggsp_jobs(conn)
        assert len(selected) == 74
        assert {j["job_id"] for j in selected} == {j["job_id"] for j in expected_active}
        assert module.old_job_fingerprint(selected) == module.OLD_JOBS_SHA256
        # Le défaut corrigé : la sélection sans filtre d'attestation active comptait l'historique.
        unfiltered = module._rows(admin, """
            SELECT j.job_id::text AS job_id FROM ingestion_control.jobs j
              JOIN ingestion_control.publication_attestations pa
                ON pa.attestation_id::text = j.payload->>'publication_attestation_id'
             WHERE j.job_type = 'publication_resume' AND pa.release_id = %s
               AND pa.collection = ANY(%s)""", (module.V4_RELEASE, list(module.COLLECTIONS)))
        assert len(unfiltered) == 148
        every_v4 = jobs("hist-job-") + jobs("act-job-")
        assert len(every_v4) == 148 and module.old_job_fingerprint(every_v4) != module.OLD_JOBS_SHA256

        # 2. Cohérence DI : même ensemble d'attestations/jobs que le contrôle des « jobs exclus ».
        perimetre = di.Perimetre(
            database="ragdb_profile_gate_v4", release_id=module.V4_RELEASE, release_manifest_sha256="m",
            repository="cyranoaladin/RAG", pull_request=262, head_sha="h262",
            exclues={c: "x" for c in module.COLLECTIONS}, attendu={})
        with control() as conn:
            etat = di.lire_etat(conn, perimetre)
        exclues = [a for a in etat.actives if a["collection"] in perimetre.exclues]
        par_attestation: dict[str, list[dict]] = {}
        for job in etat.jobs:
            par_attestation.setdefault(str(job["attestation_id"]), []).append(job)
        di_jobs = di._jobs_exclus(di.Partition(portee=[], exclues=exclues, jobs_par_attestation=par_attestation))
        assert len(exclues) == 74 and len(di_jobs) == 74
        assert {j["attestation_id"] for j in di_jobs} == {j["attestation_id"] for j in selected}
        assert {j["job_id"] for j in di_jobs} == {j["job_id"] for j in selected}
        assert di.empreinte_des_jobs_exclus(di_jobs) == module.old_job_fingerprint(selected)

        # 3. Les trois gardes acceptent ce contexte.
        monkeypatch.setattr(module, "_counts", lambda *_a, **_k: ({"c": 1}, {"c": 0}, {"c": 1}))
        with control() as ctl, psycopg.connect(dsn, options="-c role=rag_reader") as product:
            observation = module.inspect_database(
                ctl, product, review={}, owners={}, historical_unchanged=True)
        assert observation["old_v4_hggsp_jobs"] == 74
        assert observation["old_v4_hggsp_jobs_sha256"] == module.OLD_JOBS_SHA256

        with control() as conn:
            assert module.verify_v2_lineage(conn)["old_v4_jobs"] == 74

        def create_job(db: object, **kwargs: object) -> tuple[None, bool]:
            attestation = str(kwargs["payload"]["publication_attestation_id"])
            db.execute("""INSERT INTO ingestion_control.jobs
                VALUES (%s,'publication_resume',%s::jsonb,'queued',0,3,NULL,NULL,NULL,NULL)""",
                (f"successor-{attestation}", json.dumps(kwargs["payload"])))
            return None, True

        with control() as conn:
            assert module.enqueue_successor(conn, create_job=create_job) == {"created": 74, "already_queued": 0}
            conn.commit()
        assert admin.execute("SELECT count(*) FROM ingestion_control.jobs").fetchone()[0] == 222
        # Aucune garde ne touche à l'historique, ni aux 74 jobs actifs.
        assert hist_rows() == history_before
        assert jobs("act-job-") == expected_active

        # 4. Refus : dérive de l'ensemble actif ou d'un job actif.
        def refuses(message: str) -> None:
            with control() as conn, pytest.raises(module.HGGSPRefused, match=message):
                module.verify_v2_lineage(conn)
            with control() as conn, pytest.raises(module.HGGSPRefused, match=message):
                module.enqueue_successor(conn, create_job=create_job)
            with control() as ctl, psycopg.connect(dsn, options="-c role=rag_reader") as product:
                seen = module.inspect_database(ctl, product, review={}, owners={}, historical_unchanged=True)
            assert (seen["old_v4_hggsp_jobs"], seen["old_v4_hggsp_jobs_sha256"]) != (74, module.OLD_JOBS_SHA256)

        # 4a. une attestation active supplémentaire (avec son job)
        admin.execute("INSERT INTO ingestion_control.publication_attestations VALUES ('extra-att','old-resource-0','old-artifact-0',%s,%s,%s,'m','cyranoaladin/RAG',262,'h262',NULL)",
                      (f"{0:064x}", module.COLLECTIONS[0], module.V4_RELEASE))
        admin.execute("INSERT INTO ingestion_control.jobs VALUES ('extra-job','publication_resume','{\"publication_attestation_id\":\"extra-att\"}','queued',0,3,NULL,NULL,NULL,NULL)")
        refuses("anciens jobs V4|filiation V2")
        admin.execute("DELETE FROM ingestion_control.jobs WHERE job_id='extra-job'")
        admin.execute("DELETE FROM ingestion_control.publication_attestations WHERE attestation_id='extra-att'")
        # 4b. une attestation active manque (invalidée après coup)
        admin.execute("UPDATE ingestion_control.publication_attestations SET invalidated_at=now() WHERE attestation_id='act-att-0'")
        refuses("anciens jobs V4|filiation V2")
        # Une attestation historique invalidée n'entre jamais dans l'ensemble protégé.
        with control() as conn:
            assert "hist-job-0" not in {j["job_id"] for j in module._active_v4_hggsp_jobs(conn)}
            assert "act-job-0" not in {j["job_id"] for j in module._active_v4_hggsp_jobs(conn)}
        admin.execute("UPDATE ingestion_control.publication_attestations SET invalidated_at=NULL WHERE attestation_id='act-att-0'")
        # 4c. un des 74 jobs actifs change de statut : l'empreinte diverge
        admin.execute("UPDATE ingestion_control.jobs SET status='running' WHERE job_id='act-job-0'")
        refuses("anciens jobs V4|filiation V2")
        admin.execute("UPDATE ingestion_control.jobs SET status='queued' WHERE job_id='act-job-0'")
        # Retour à l'état initial : les gardes acceptent de nouveau.
        with control() as conn:
            assert module.verify_v2_lineage(conn)["old_v4_jobs"] == 74
        assert hist_rows() == history_before
        admin.close()
    finally:
        subprocess.run(["docker", "rm", "-f", "-v", name], capture_output=True, text=True, check=False)


def test_enqueue_locks_only_what_the_application_role_may_lock() -> None:
    """`FOR SHARE` exige UPDATE sur chaque table verrouillée. Le rôle applicatif n'a que SELECT sur les
    attestations et les adoptions : seule `resources` (où il peut écrire) est verrouillée."""
    source = (ROOT / "scripts/go_live/staging_hggsp_complementary.py").read_text(encoding="utf-8")
    fonction = source.split("def enqueue_successor(", 1)[1].split("\ndef ", 1)[0]
    assert "FOR SHARE OF r\n" in fonction
    for interdit in ("FOR SHARE OF pa", "FOR SHARE OF ad", "FOR UPDATE", "FOR NO KEY UPDATE", "FOR KEY SHARE"):
        assert interdit not in fonction, interdit
