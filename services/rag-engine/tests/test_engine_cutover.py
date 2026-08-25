from __future__ import annotations

import ast
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.ingestor.engine_cutover import EngineCutoverError, validate_engine_cutover

ENGINE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ENGINE_ROOT / "tests" / "fixtures" / "engine_cutover_no_go_v1.json"
MODULE_PATH = ENGINE_ROOT / "src" / "ingestor" / "engine_cutover.py"
FACT_EVIDENCE_TYPES = {
    "snapshot_restored_verified": "SNAPSHOT_RESTORE_VERIFICATION",
    "real_parity_executed": "REAL_PARITY_EXECUTION",
    "restore_rehearsal_verified": "RESTORE_REHEARSAL_VERIFICATION",
    "traffic_rollback_tested": "TRAFFIC_ROLLBACK_TEST",
    "cutover_authorized": "CUTOVER_AUTHORIZATION",
}


def _manifest() -> dict[str, Any]:
    document = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _write_manifest(path: Path, document: dict[str, Any]) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _validate(path: Path = FIXTURE_PATH):
    return validate_engine_cutover(
        path,
        now=datetime(2026, 8, 25, 12, tzinfo=UTC),
    )


def test_release_requires_git_sha_and_immutable_images(tmp_path: Path) -> None:
    decision = _validate()

    assert decision.release.git_commit == "0123456789abcdef0123456789abcdef01234567"
    assert tuple(image.name for image in decision.release.images) == (
        "rag-engine-v2",
        "rag-engine-legacy",
    )
    assert all(image.digest.startswith("sha256:") for image in decision.release.images)

    invalid_commit = _manifest()
    invalid_commit["release"]["git_commit"] = "main"
    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / "invalid-commit.json", invalid_commit))

    mutable_image = _manifest()
    mutable_image["release"]["images"][0]["digest"] = "rag-engine:latest"
    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / "mutable-image.json", mutable_image))


def test_engine_a_requires_chroma_inventory(tmp_path: Path) -> None:
    decision = _validate()

    assert decision.engine_a.chroma.service_id == "synthetic-legacy-chroma"
    assert decision.engine_a.chroma.embedding_dimension == 768
    assert decision.engine_a.chroma.collections[0].object_count == 7

    missing = _manifest()
    del missing["engine_a"]["chroma"]
    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / "missing-chroma.json", missing))


def test_engine_a_requires_two_distinct_sqlite_snapshots(tmp_path: Path) -> None:
    decision = _validate()

    assert decision.engine_a.catalog_sqlite.identity == "catalog.sqlite"
    assert decision.engine_a.drive_sync_sqlite.identity == "drive_sync_state.db"
    assert decision.engine_a.catalog_sqlite.integrity_check == "ok"
    assert decision.engine_a.drive_sync_sqlite.integrity_check == "ok"

    for field in ("catalog_sqlite", "drive_sync_sqlite"):
        missing = _manifest()
        del missing["engine_a"][field]
        with pytest.raises(EngineCutoverError):
            _validate(_write_manifest(tmp_path / f"missing-{field}.json", missing))


def test_engine_a_requires_uploads_configs_images_and_models(tmp_path: Path) -> None:
    assets = _validate().engine_a.assets

    assert assets.uploads.file_count == 3
    assert assets.config_file_count == 4
    assert assets.images[0].digest.startswith("sha256:")
    assert assets.models[0].dimension == 768

    for field in ("uploads", "configs", "images", "models"):
        missing = _manifest()
        del missing["engine_a"]["assets"][field]
        with pytest.raises(EngineCutoverError):
            _validate(_write_manifest(tmp_path / f"missing-{field}.json", missing))


def test_engine_b_requires_pgvector_inventory_and_migration_head(tmp_path: Path) -> None:
    pgvector = _validate().engine_b.pgvector

    assert pgvector.service_id == "synthetic-pgvector"
    assert pgvector.database_id == "synthetic-empty-b"
    assert pgvector.migration_head == "004"
    assert pgvector.object_count == 0

    for path in (("engine_b", "pgvector"), ("engine_b", "pgvector", "migration_head")):
        missing = _manifest()
        target: Any = missing
        for field in path[:-1]:
            target = target[field]
        del target[path[-1]]
        with pytest.raises(EngineCutoverError):
            _validate(_write_manifest(tmp_path / f"missing-{'-'.join(path)}.json", missing))


def test_engine_b_requires_sealed_pgvector_backup(tmp_path: Path) -> None:
    backup = _validate().engine_b.backup

    assert backup.method == "pg_dump_custom"
    assert backup.integrity_check == "verified"
    assert len(backup.digest_sha256) == 64

    missing = _manifest()
    del missing["engine_b"]["backup"]
    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / "missing-pgvector-backup.json", missing))


@pytest.mark.parametrize("field", ("writers_disabled", "scheduled_tasks_disabled"))
def test_quiescence_requires_disabled_writers_and_tasks(
    tmp_path: Path, field: str
) -> None:
    decision = _validate()

    assert decision.quiescence.writers_disabled is True
    assert decision.quiescence.scheduled_tasks_disabled is True

    live = _manifest()
    live["quiescence"][field] = False
    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / f"enabled-{field}.json", live))


def test_quiescence_requires_exact_capture_order(tmp_path: Path) -> None:
    assert _validate().quiescence.capture_order == (
        "chroma",
        "catalog.sqlite",
        "drive_sync_state.db",
        "uploads",
    )

    unordered = _manifest()
    unordered["quiescence"]["capture_order"].reverse()
    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / "unordered.json", unordered))


@pytest.mark.parametrize(
    "field",
    ("chroma_count", "catalog_count", "drive_sync_count", "uploads_count"),
)
def test_quiescence_requires_stable_counts(tmp_path: Path, field: str) -> None:
    decision = _validate()

    assert decision.quiescence.before == decision.quiescence.after
    assert decision.quiescence.mutation_free_until_decision is True

    changed = _manifest()
    changed["quiescence"]["after"][field] += 1
    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / f"changed-{field}.json", changed))


@pytest.mark.parametrize(
    "field",
    (
        "chroma_digest_sha256",
        "catalog_digest_sha256",
        "drive_sync_digest_sha256",
        "uploads_digest_sha256",
    ),
)
def test_quiescence_requires_stable_digests(tmp_path: Path, field: str) -> None:
    changed = _manifest()
    changed["quiescence"]["after"][field] = "0" * 64

    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / f"changed-{field}.json", changed))


def test_operator_quiescence_must_be_fresh(tmp_path: Path) -> None:
    operator = _manifest()
    operator["capture_context"] = "OPERATOR_READ_ONLY_CAPTURE"
    operator["quiescence"]["capture_mode"] = "QUIESCED_SNAPSHOT"
    decision = _validate(_write_manifest(tmp_path / "operator.json", operator))

    assert decision.capture_context == "OPERATOR_READ_ONLY_CAPTURE"
    assert decision.quiescence.capture_mode == "QUIESCED_SNAPSHOT"

    operator["quiescence"]["captured_at"] = "1970-01-01T00:00:00Z"
    operator["quiescence"]["valid_until"] = "1970-01-02T00:00:00Z"
    with pytest.raises(EngineCutoverError, match="fresh"):
        _validate(_write_manifest(tmp_path / "stale.json", operator))


def test_live_archive_cannot_declare_snapshot(tmp_path: Path) -> None:
    live = _manifest()
    live["capture_context"] = "OPERATOR_READ_ONLY_CAPTURE"
    live["quiescence"]["capture_mode"] = "LIVE"
    live["snapshot_declared"] = True

    with pytest.raises(EngineCutoverError, match="live"):
        _validate(_write_manifest(tmp_path / "live-declared.json", live))


def test_canary_and_rollback_targets_must_be_distinct(tmp_path: Path) -> None:
    topology = _validate().topology

    assert topology.active_target == "engine_a"
    assert topology.canary_target == "engine_b"
    assert topology.rollback_target == "engine_a"

    conflated = _manifest()
    conflated["topology"]["rollback_target"] = "engine_b"
    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / "same-target.json", conflated))


@pytest.mark.parametrize("field", ("timeout_seconds", "max_attempts"))
def test_smoke_probes_are_bounded(tmp_path: Path, field: str) -> None:
    probe = _validate().smokes[0]

    assert probe.timeout_seconds == 10
    assert probe.max_attempts == 3

    unbounded = _manifest()
    unbounded["smokes"][0][field] = 0
    with pytest.raises(EngineCutoverError):
        _validate(_write_manifest(tmp_path / f"unbounded-{field}.json", unbounded))


@pytest.mark.parametrize("fact_name", tuple(FACT_EVIDENCE_TYPES))
def test_positive_fact_refuses_substituted_evidence(
    tmp_path: Path, fact_name: str
) -> None:
    document = _manifest()
    evidence_types = tuple(FACT_EVIDENCE_TYPES.values())
    expected_type = FACT_EVIDENCE_TYPES[fact_name]
    substituted_type = next(item for item in evidence_types if item != expected_type)
    document["facts"][fact_name] = {
        "value": True,
        "evidence": {
            "evidence_type": substituted_type,
            "reference_id": "synthetic-evidence",
            "digest_sha256": "1" * 64,
        },
    }

    with pytest.raises(EngineCutoverError, match="exact evidence"):
        _validate(_write_manifest(tmp_path / f"substituted-{fact_name}.json", document))


@pytest.mark.parametrize("fact_name", tuple(FACT_EVIDENCE_TYPES))
def test_lot2_refuses_even_exact_positive_execution_facts(
    tmp_path: Path, fact_name: str
) -> None:
    document = _manifest()
    document["facts"][fact_name] = {
        "value": True,
        "evidence": {
            "evidence_type": FACT_EVIDENCE_TYPES[fact_name],
            "reference_id": "synthetic-evidence",
            "digest_sha256": "1" * 64,
        },
    }

    with pytest.raises(EngineCutoverError, match="Lot 2"):
        _validate(_write_manifest(tmp_path / f"positive-{fact_name}.json", document))


def test_nominal_lot2_lists_five_unsatisfied_gates_and_no_go() -> None:
    decision = _validate()

    assert decision.verdict == "NO_GO"
    assert tuple(gate.name for gate in decision.gates) == tuple(FACT_EVIDENCE_TYPES)
    assert all(gate.satisfied is False and gate.evidence is None for gate in decision.gates)


def test_verdict_refuses_ready_vocabulary(tmp_path: Path) -> None:
    document = _manifest()
    document["verdict"] = "READY"

    with pytest.raises(EngineCutoverError, match="readiness"):
        _validate(_write_manifest(tmp_path / "ready.json", document))


def test_verdict_refuses_go_live_ready_vocabulary(tmp_path: Path) -> None:
    document = _manifest()
    document["verdict"] = "GO_LIVE_READY"

    with pytest.raises(EngineCutoverError, match="readiness"):
        _validate(_write_manifest(tmp_path / "go-live-ready.json", document))


def test_verdict_refuses_readiness_synonym(tmp_path: Path) -> None:
    document = _manifest()
    document["verdict"] = "CUTOVER_READY"

    with pytest.raises(EngineCutoverError, match="readiness"):
        _validate(_write_manifest(tmp_path / "cutover-ready.json", document))


def test_verdict_is_exclusively_no_go(tmp_path: Path) -> None:
    document = _manifest()
    document["verdict"] = "BLOCKED"

    with pytest.raises(EngineCutoverError, match="NO_GO"):
        _validate(_write_manifest(tmp_path / "blocked.json", document))


def test_manifest_schema_refuses_unknown_root_fields(tmp_path: Path) -> None:
    document = _manifest()
    document["deploy_command"] = "synthetic-forbidden"

    with pytest.raises(EngineCutoverError, match="schema"):
        _validate(_write_manifest(tmp_path / "unknown-root.json", document))


def test_manifest_refuses_duplicate_json_keys(tmp_path: Path) -> None:
    raw = FIXTURE_PATH.read_text(encoding="utf-8").replace(
        '"verdict": "NO_GO"',
        '"verdict": "READY", "verdict": "NO_GO"',
    )
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text(raw, encoding="utf-8")

    with pytest.raises(EngineCutoverError, match="duplicate"):
        _validate(duplicate)


def test_validator_has_no_mutation_process_database_or_docker_primitives() -> None:
    tree = ast.parse(MODULE_PATH.read_text(encoding="utf-8"))
    forbidden_modules = {
        "asyncpg",
        "chromadb",
        "docker",
        "httpx",
        "psycopg",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 0
    }
    forbidden_calls = {
        "commit",
        "connect",
        "create_pool",
        "deploy",
        "execute",
        "executemany",
        "Popen",
        "rename",
        "replace",
        "restore",
        "run",
        "system",
        "unlink",
        "write_bytes",
        "write_text",
    }
    called_attributes = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }

    assert not forbidden_modules & imported_roots
    assert not forbidden_calls & called_attributes
    assert "rag_chunks" not in MODULE_PATH.read_text(encoding="utf-8")
