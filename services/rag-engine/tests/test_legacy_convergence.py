from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from src.ingestor.engine_convergence_policy import (
    EngineConvergencePolicy,
    LegacyDisposition,
    load_engine_convergence_policy,
)
from src.ingestor.legacy_convergence import (
    LegacyCaptureError,
    LegacyReasonCode,
    prepare_legacy_capture,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ENGINE_ROOT / "tests" / "fixtures" / "legacy_convergence_capture_v1.jsonl"
POLICY_PATH = ENGINE_ROOT / "configs" / "engine_convergence_v1.yml"
MODULE_PATH = ENGINE_ROOT / "src" / "ingestor" / "legacy_convergence.py"
CLI_PATH = ENGINE_ROOT / "scripts" / "prepare_legacy_migration.py"
FORBIDDEN_CONTENT_KEYS = {"text", "document", "embedding", "embeddings"}


def _records() -> list[dict[str, Any]]:
    return [json.loads(line) for line in FIXTURE_PATH.read_text(encoding="utf-8").splitlines()]


def _write_records(path: Path, records: list[dict[str, Any]]) -> Path:
    path.write_text(
        "".join(f"{json.dumps(record, sort_keys=True, separators=(',', ':'))}\n" for record in records),
        encoding="utf-8",
    )
    return path


def _policy() -> EngineConvergencePolicy:
    return load_engine_convergence_policy(POLICY_PATH)


def _prepare(
    path: Path = FIXTURE_PATH,
    *,
    max_line_bytes: int = 65_536,
    max_total_bytes: int = 64 * 1024 * 1024,
    max_records: int = 1_000_000,
):
    return prepare_legacy_capture(
        path,
        policy=_policy(),
        max_line_bytes=max_line_bytes,
        max_total_bytes=max_total_bytes,
        max_records=max_records,
        now=datetime(2026, 8, 25, 12, tzinfo=UTC),
    )


def _delete_path(document: dict[str, Any], path: str) -> None:
    target: Any = document
    parts = path.split(".")
    for part in parts[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    if isinstance(target, list):
        del target[int(parts[-1])]
    else:
        del target[parts[-1]]


def _mapping_keys(value: Any) -> set[str]:
    if isinstance(value, dict):
        return set(value) | {
            key
            for nested in value.values()
            for key in _mapping_keys(nested)
        }
    if isinstance(value, list):
        return {key for nested in value for key in _mapping_keys(nested)}
    return set()


def test_fixture_contains_no_content_vectors_or_mutable_images() -> None:
    records = _records()

    assert records
    assert not FORBIDDEN_CONTENT_KEYS & {
        key for record in records for key in _mapping_keys(record)
    }
    header = records[0]
    assert all(
        set(image) == {"name", "digest"}
        and image["digest"].startswith("sha256:")
        and len(image["digest"]) == 71
        for image in header["images"]
    )


def test_capture_requires_producer_read_only_identity(tmp_path: Path) -> None:
    manifest = _prepare()

    assert manifest.producer.name == "nexus-legacy-readonly-export"
    assert manifest.producer.version == "1.0.0"
    assert manifest.producer.git_commit == "0123456789abcdef0123456789abcdef01234567"
    assert manifest.producer.captured_at == "2026-08-25T10:00:00Z"
    assert manifest.producer.valid_until == "2026-08-26T10:00:00Z"
    assert manifest.producer.capture_context == "SYNTHETIC_TEST"

    mutations = {
        "protocol": ("protocol_version", "UNKNOWN"),
        "producer": ("producer.name", ""),
        "version": ("producer.version", ""),
        "commit": ("producer.git_commit", "not-a-commit"),
        "instant": ("producer.captured_at", "2026-08-25"),
        "read-only": ("read_only_proof.writes_disabled", False),
    }
    for name, (field, value) in mutations.items():
        records = _records()
        target: dict[str, Any] = records[0]
        parts = field.split(".")
        for part in parts[:-1]:
            target = target[part]
        target[parts[-1]] = value
        with pytest.raises(LegacyCaptureError):
            _prepare(_write_records(tmp_path / f"invalid-{name}.jsonl", records))

    records = _records()
    records[0]["read_only_proof"]["mode"] = "writes_enabled"
    with pytest.raises(LegacyCaptureError):
        _prepare(_write_records(tmp_path / "write-enabled.jsonl", records))

    records = _records()
    records[0]["capture_context"] = "OPERATOR_READ_ONLY_CAPTURE"
    records[0]["producer"]["captured_at"] = "1970-01-01T00:00:00Z"
    records[0]["producer"]["valid_until"] = "1970-01-02T00:00:00Z"
    with pytest.raises(LegacyCaptureError, match="not fresh"):
        _prepare(_write_records(tmp_path / "stale.jsonl", records))

    records = _records()
    records[0]["capture_context"] = "ARBITRARY"
    with pytest.raises(LegacyCaptureError, match="context"):
        _prepare(_write_records(tmp_path / "unknown-context.jsonl", records))


def test_capture_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    raw = FIXTURE_PATH.read_bytes().replace(
        b'"writes_disabled":true',
        b'"writes_disabled":false,"writes_disabled":true',
        1,
    )
    capture = tmp_path / "duplicate-key.jsonl"
    capture.write_bytes(raw)

    with pytest.raises(LegacyCaptureError, match="duplicate key"):
        _prepare(capture)


def test_capture_requires_chroma_identity_dimension_counts_and_digests(
    tmp_path: Path,
) -> None:
    manifest = _prepare()

    assert manifest.chroma.service_id == "synthetic-legacy-chroma"
    assert manifest.chroma.volume_id == "synthetic-legacy-chroma-volume"
    assert manifest.chroma.embedding_dimension == 768
    assert len(manifest.chroma.collections) == len(_policy().discovered_legacy_collections)
    assert sum(item.object_count for item in manifest.chroma.collections) == 7

    for index, path in enumerate(
        (
            "chroma.service_id",
            "chroma.volume_id",
            "chroma.embedding_dimension",
            "chroma.collections.0.object_count",
            "chroma.collections.0.digest_sha256",
        )
    ):
        records = _records()
        _delete_path(records[0], path)
        with pytest.raises(LegacyCaptureError):
            _prepare(_write_records(tmp_path / f"invalid-chroma-{index}.jsonl", records))


def test_capture_requires_both_sqlite_consistent_backups(tmp_path: Path) -> None:
    manifest = _prepare()

    assert manifest.catalog_sqlite.identity == "catalog.sqlite"
    assert manifest.drive_sync_sqlite.identity == "drive_sync_state.db"
    assert manifest.catalog_sqlite.backup_method == "sqlite_backup_api"
    assert manifest.drive_sync_sqlite.backup_method == "quiesced_checkpoint"
    assert manifest.catalog_sqlite.integrity_check == "ok"
    assert manifest.drive_sync_sqlite.integrity_check == "ok"

    paths = (
        "sqlite.catalog",
        "sqlite.drive_sync",
        "sqlite.catalog.schema_version",
        "sqlite.catalog.wal_state",
        "sqlite.catalog.backup_method",
        "sqlite.catalog.integrity_check",
        "sqlite.catalog.digest_sha256",
    )
    for index, path in enumerate(paths):
        records = _records()
        _delete_path(records[0], path)
        with pytest.raises(LegacyCaptureError):
            _prepare(_write_records(tmp_path / f"invalid-sqlite-{index}.jsonl", records))


def test_capture_requires_pgvector_uploads_configs_images_and_models(
    tmp_path: Path,
) -> None:
    manifest = _prepare()

    assert manifest.pgvector.migration_head == "004"
    assert manifest.pgvector.service_id == "synthetic-pgvector-fixture"
    assert manifest.pgvector.database_id == "synthetic-empty-b"
    assert manifest.pgvector.object_count == 0
    assert manifest.assets.uploads.logical_root == "synthetic-legacy-uploads"
    assert manifest.assets.uploads.file_count == 3
    assert manifest.assets.config_file_count == 4
    assert {image.name for image in manifest.assets.images} == {
        "legacy-ingestor",
        "legacy-ui",
    }
    assert manifest.assets.models[0].dimension == 768

    paths = (
        "pgvector.service_id",
        "pgvector.database_id",
        "pgvector.migration_head",
        "pgvector.object_count",
        "pgvector.digest_sha256",
        "uploads.logical_root",
        "uploads.file_count",
        "uploads.digest_sha256",
        "configs.file_count",
        "configs.digest_sha256",
        "images.0.digest",
        "models.0.digest_sha256",
    )
    for index, path in enumerate(paths):
        records = _records()
        _delete_path(records[0], path)
        with pytest.raises(LegacyCaptureError):
            _prepare(_write_records(tmp_path / f"invalid-assets-{index}.jsonl", records))

    mutable_image = _records()
    mutable_image[0]["images"][0]["digest"] = "legacy-ingestor:latest"
    with pytest.raises(LegacyCaptureError):
        _prepare(_write_records(tmp_path / "mutable-image.jsonl", mutable_image))


def test_capture_rejects_oversized_line_without_echoing_content(tmp_path: Path) -> None:
    canary = "CANARY-CONTENT-MUST-NOT-LEAK"
    capture = tmp_path / "oversized.jsonl"
    capture.write_bytes((f'{{"{canary}":"' + "x" * 128 + '"}}\n').encode())

    with pytest.raises(LegacyCaptureError) as caught:
        _prepare(capture, max_line_bytes=64)

    assert canary not in str(caught.value)


def test_capture_bounds_total_bytes_and_record_count(tmp_path: Path) -> None:
    records = _records()
    capture = _write_records(tmp_path / "bounded.jsonl", records)

    with pytest.raises(LegacyCaptureError, match="capture is too large"):
        _prepare(capture, max_total_bytes=capture.stat().st_size - 1)
    with pytest.raises(LegacyCaptureError, match="too many records"):
        _prepare(capture, max_records=len(records) - 1)


@pytest.mark.parametrize("field", ["text", "embedding"])
def test_capture_rejects_forbidden_content_fields_without_echoing_values(
    tmp_path: Path,
    field: str,
) -> None:
    canary = "CANARY-RAW-CONTENT-MUST-NOT-LEAK"
    records = _records()
    records[1][field] = canary

    with pytest.raises(LegacyCaptureError) as caught:
        _prepare(_write_records(tmp_path / f"forbidden-{field}.jsonl", records))

    assert canary not in str(caught.value)


def test_invalid_json_retains_no_raw_payload_in_exception_chain(tmp_path: Path) -> None:
    canary = "CANARY-RAW-JSON-MUST-NOT-BE-RETAINED"
    capture = tmp_path / "invalid-json.jsonl"
    capture.write_text('{"record_type":"capture_header","broken":"' + canary)

    with pytest.raises(LegacyCaptureError) as caught:
        _prepare(capture)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    traceback = caught.value.__traceback__
    while traceback is not None:
        if Path(traceback.tb_frame.f_code.co_filename) == MODULE_PATH:
            assert canary not in repr(traceback.tb_frame.f_locals)
        traceback = traceback.tb_next


@pytest.mark.parametrize(
    ("record_index", "path"),
    (
        (0, "unexpected"),
        (0, "producer.unexpected"),
        (0, "chroma.collections.0.unexpected"),
        (1, "unexpected"),
        (1, "source.unexpected"),
        (1, "scope.unexpected"),
    ),
)
def test_capture_rejects_unknown_schema_fields(
    tmp_path: Path, record_index: int, path: str
) -> None:
    records = _records()
    target: Any = records[record_index]
    for part in path.split(".")[:-1]:
        target = target[int(part)] if isinstance(target, list) else target[part]
    target[path.split(".")[-1]] = "CANARY-UNKNOWN-FIELD"

    with pytest.raises(LegacyCaptureError, match="schema"):
        _prepare(_write_records(tmp_path / "unknown-field.jsonl", records))


def test_capture_rejects_invalid_object_sha256(tmp_path: Path) -> None:
    records = _records()
    records[1]["content_sha256"] = "not-a-sha256"

    with pytest.raises(LegacyCaptureError):
        _prepare(_write_records(tmp_path / "invalid-object-sha.jsonl", records))


def test_capture_requires_sealed_source_and_rights_evidence(tmp_path: Path) -> None:
    for field in (
        "source_snapshot_sha256",
        "provenance_evidence_sha256",
        "rights_evidence_sha256",
    ):
        records = _records()
        del records[1]["source"][field]
        with pytest.raises(LegacyCaptureError):
            _prepare(_write_records(tmp_path / f"missing-{field}.jsonl", records))


@pytest.mark.parametrize(
    "source_id",
    (
        "https://user:password@example.test/path",
        "operator-token-identifier",
        "x" * 129,
    ),
)
def test_capture_requires_bounded_opaque_source_ids(
    tmp_path: Path, source_id: str
) -> None:
    records = _records()
    records[1]["source"]["source_id"] = source_id

    with pytest.raises(LegacyCaptureError, match="source id"):
        _prepare(_write_records(tmp_path / "unsafe-source-id.jsonl", records))


def test_capture_rejects_sensitive_inventory_identifiers(tmp_path: Path) -> None:
    canary = "password:CANARY-SENSITIVE-INVENTORY"
    records = _records()
    records[0]["pgvector"]["database_id"] = canary

    with pytest.raises(LegacyCaptureError) as caught:
        _prepare(_write_records(tmp_path / "sensitive-identity.jsonl", records))

    assert canary not in str(caught.value)


def test_capture_rejects_wrong_source_object_count(tmp_path: Path) -> None:
    records = _records()
    records[0]["source_object_count"] += 1

    with pytest.raises(LegacyCaptureError):
        _prepare(_write_records(tmp_path / "wrong-source-count.jsonl", records))


def test_capture_requires_exact_policy_discovery(tmp_path: Path) -> None:
    records = _records()
    records[0]["discovered_collections"].pop()

    with pytest.raises(LegacyCaptureError):
        _prepare(_write_records(tmp_path / "incomplete-discovery.jsonl", records))


def test_capture_rejects_unknown_object_collection(tmp_path: Path) -> None:
    records = _records()
    records[1]["legacy_collection"] = "unknown_collection"

    with pytest.raises(LegacyCaptureError):
        _prepare(_write_records(tmp_path / "unknown-collection.jsonl", records))


def test_capture_reconciles_chroma_discovery_and_per_collection_counts(
    tmp_path: Path,
) -> None:
    records = _records()
    records[0]["chroma"]["collections"][0]["name"] = "unknown_collection"
    with pytest.raises(LegacyCaptureError):
        _prepare(_write_records(tmp_path / "unknown-inventory.jsonl", records))

    records = _records()
    records[0]["chroma"]["collections"][0]["object_count"] += 1
    with pytest.raises(LegacyCaptureError):
        _prepare(_write_records(tmp_path / "wrong-collection-count.jsonl", records))


def test_capture_applies_fail_closed_disposition_precedence() -> None:
    manifest = _prepare()
    items = {item.migration_id: item for item in manifest.items}

    assert (items["legacy-003"].disposition, items["legacy-003"].reason_code) == (
        LegacyDisposition.BLOCKED,
        LegacyReasonCode.SOURCE_UNAVAILABLE,
    )
    assert (items["legacy-007"].disposition, items["legacy-007"].reason_code) == (
        LegacyDisposition.QUARANTINE,
        LegacyReasonCode.NON_PUBLISHABLE,
    )
    assert (items["legacy-005"].disposition, items["legacy-005"].reason_code) == (
        LegacyDisposition.REVIEW_REQUIRED,
        LegacyReasonCode.RIGHTS_UNVERIFIED,
    )
    assert (items["legacy-006"].disposition, items["legacy-006"].reason_code) == (
        LegacyDisposition.REVIEW_REQUIRED,
        LegacyReasonCode.COLLECTION_AMBIGUOUS,
    )
    assert (items["legacy-001"].disposition, items["legacy-001"].reason_code) == (
        LegacyDisposition.REINGEST_GOVERNED,
        LegacyReasonCode.EXACT_SOURCE_AND_SCOPE,
    )
    assert items["legacy-001"].target_collection == (
        "rag_nexus_nsi_premiere_specialite"
    )
    assert items["legacy-004"].target_collection == (
        "rag_nexus_nsi_terminale_specialite"
    )
    assert all(
        empty.disposition is LegacyDisposition.IGNORE_EMPTY
        and empty.reason_code is LegacyReasonCode.EMPTY_COLLECTION_VERIFIED
        for empty in manifest.empty_collections
    )


def test_reingest_candidates_do_not_transport_governance_decisions() -> None:
    manifest = _prepare()
    reingest = next(
        item
        for item in manifest.items
        if item.disposition is LegacyDisposition.REINGEST_GOVERNED
    )

    keys = set(asdict(reingest))
    assert not {
        "rights_verified",
        "reviewed",
        "retrievable",
        "authorized",
        "authorization",
    } & keys


@pytest.mark.parametrize(
    ("mutation", "expected_disposition", "expected_reason"),
    (
        (
            lambda record: record.pop("scope"),
            LegacyDisposition.REVIEW_REQUIRED,
            LegacyReasonCode.SCOPE_INCOMPLETE,
        ),
        (
            lambda record: record["source"].update(provenance_complete=False),
            LegacyDisposition.REVIEW_REQUIRED,
            LegacyReasonCode.PROVENANCE_INCOMPLETE,
        ),
        (
            lambda record: record["source"].update(
                rights_verified=False, provenance_complete=False
            ),
            LegacyDisposition.REVIEW_REQUIRED,
            LegacyReasonCode.RIGHTS_UNVERIFIED,
        ),
        (
            lambda record: record["source"].update(
                recoverable=False, publishable=False
            ),
            LegacyDisposition.BLOCKED,
            LegacyReasonCode.SOURCE_UNAVAILABLE,
        ),
    ),
)
def test_capture_preserves_reason_precedence_for_incomplete_evidence(
    tmp_path: Path,
    mutation,
    expected_disposition: LegacyDisposition,
    expected_reason: LegacyReasonCode,
) -> None:
    records = _records()
    mutation(records[1])

    item = _prepare(_write_records(tmp_path / "precedence.jsonl", records)).items[0]

    assert (item.disposition, item.reason_code) == (
        expected_disposition,
        expected_reason,
    )


def test_capture_deduplicates_by_content_and_provenance_without_loss(
    tmp_path: Path,
) -> None:
    records = _records()
    capture = _write_records(
        tmp_path / "reversed.jsonl", [records[0], *reversed(records[1:])]
    )

    manifest = _prepare(capture)
    items = {item.migration_id: item for item in manifest.items}

    assert len(manifest.items) == records[0]["source_object_count"]
    assert set(items) == {record["migration_id"] for record in records[1:]}
    assert tuple(item.migration_id for item in manifest.items) == tuple(sorted(items))
    assert items["legacy-001"].duplicate_of is None
    assert items["legacy-002"].duplicate_of == "legacy-001"


def test_capture_does_not_deduplicate_conflicting_evidence(tmp_path: Path) -> None:
    records = _records()
    conflicting = json.loads(json.dumps(records[1]))
    conflicting["migration_id"] = "legacy-008"
    conflicting["source"]["rights_verified"] = False
    records[0]["source_object_count"] += 1
    records[0]["chroma"]["collections"][0]["object_count"] += 1
    records.append(conflicting)

    manifest = _prepare(_write_records(tmp_path / "conflicting.jsonl", records))
    items = {item.migration_id: item for item in manifest.items}

    assert items["legacy-008"].duplicate_of is None
    assert items["legacy-008"].disposition is LegacyDisposition.REVIEW_REQUIRED


def test_capture_deduplicates_same_passage_across_legacy_silos(tmp_path: Path) -> None:
    records = _records()
    cross_silo = json.loads(json.dumps(records[1]))
    cross_silo["migration_id"] = "legacy-008"
    cross_silo["legacy_collection"] = "nsi_corpus_v2"
    records[0]["source_object_count"] += 1
    records[0]["chroma"]["collections"][1]["object_count"] += 1
    records.append(cross_silo)

    manifest = _prepare(_write_records(tmp_path / "cross-silo.jsonl", records))
    items = {item.migration_id: item for item in manifest.items}

    assert items["legacy-008"].duplicate_of == "legacy-001"


def test_capture_does_not_deduplicate_across_different_silo_policies(
    tmp_path: Path,
) -> None:
    records = _records()
    quarantined = json.loads(json.dumps(records[1]))
    quarantined["migration_id"] = "legacy-008"
    quarantined["legacy_collection"] = "rag_web3"
    records[0]["source_object_count"] += 1
    records[0]["chroma"]["collections"][6]["object_count"] += 1
    records.append(quarantined)

    manifest = _prepare(_write_records(tmp_path / "different-policy.jsonl", records))
    items = {item.migration_id: item for item in manifest.items}

    assert items["legacy-008"].duplicate_of is None
    assert items["legacy-008"].disposition is LegacyDisposition.QUARANTINE


def test_capture_refuses_excessive_json_depth_without_raw_traceback(
    tmp_path: Path,
) -> None:
    canary = "CANARY-DEEP-JSON-MUST-NOT-BE-RETAINED"
    capture = tmp_path / "deep.jsonl"
    capture.write_text('{"nested":' * 1_200 + f'"{canary}"' + "}" * 1_200)

    with pytest.raises(LegacyCaptureError) as caught:
        _prepare(capture)

    traceback = caught.value.__traceback__
    while traceback is not None:
        if Path(traceback.tb_frame.f_code.co_filename) == MODULE_PATH:
            assert canary not in repr(traceback.tb_frame.f_locals)
        traceback = traceback.tb_next


def test_capture_refuses_oversized_json_integer_without_raw_traceback(
    tmp_path: Path,
) -> None:
    canary = "CANARY-HUGE-INTEGER-MUST-NOT-BE-RETAINED"
    capture = tmp_path / "huge-integer.jsonl"
    capture.write_text(f'{{"{canary}":' + "9" * 5_000 + "}")

    with pytest.raises(LegacyCaptureError) as caught:
        _prepare(capture)

    traceback = caught.value.__traceback__
    while traceback is not None:
        if Path(traceback.tb_frame.f_code.co_filename) == MODULE_PATH:
            assert canary not in repr(traceback.tb_frame.f_locals)
        traceback = traceback.tb_next


@pytest.mark.parametrize("field", ("migration_id", "canonical_span_id"))
def test_capture_rejects_sensitive_serialized_object_identifiers(
    tmp_path: Path, field: str
) -> None:
    canary = f"password:CANARY-{field}"
    records = _records()
    records[1][field] = canary

    with pytest.raises(LegacyCaptureError) as caught:
        _prepare(_write_records(tmp_path / f"sensitive-{field}.jsonl", records))

    assert canary not in str(caught.value)


def test_manifest_counts_every_source_object_and_disposition() -> None:
    manifest = _prepare()

    assert manifest.source_object_count == 7
    assert manifest.prepared_object_count == manifest.source_object_count
    assert manifest.duplicate_count == 1
    assert sum(dict(manifest.disposition_counts).values()) == (
        manifest.source_object_count
    )
    assert set(dict(manifest.disposition_counts)) == {
        disposition.value for disposition in LegacyDisposition
    }
    assert dict(manifest.disposition_counts)[LegacyDisposition.IGNORE_EMPTY.value] == 0


def test_manifest_seals_exact_input_and_canonical_output(tmp_path: Path) -> None:
    manifest = _prepare()
    copied_capture = tmp_path / "capture-copy.jsonl"
    copied_capture.write_bytes(FIXTURE_PATH.read_bytes())
    copied_manifest = _prepare(copied_capture)

    assert manifest.input_digest_sha256 == hashlib.sha256(
        FIXTURE_PATH.read_bytes()
    ).hexdigest()
    assert copied_manifest.input_digest_sha256 == manifest.input_digest_sha256
    assert copied_manifest.manifest_sha256 == manifest.manifest_sha256

    canonical_payload = asdict(manifest)
    manifest_digest = canonical_payload.pop("manifest_sha256")
    canonical_bytes = json.dumps(
        canonical_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    assert manifest_digest == hashlib.sha256(canonical_bytes).hexdigest()


def test_manifest_is_explicitly_non_migrating_and_contains_no_payload() -> None:
    manifest = _prepare()
    serialized = asdict(manifest)

    assert manifest.migration_complete is False
    assert not FORBIDDEN_CONTENT_KEYS & _mapping_keys(serialized)


def test_preparator_has_no_database_network_or_process_boundary() -> None:
    forbidden_modules = {
        "chromadb",
        "httpx",
        "psycopg",
        "requests",
        "socket",
        "subprocess",
        "urllib",
    }

    for path in (MODULE_PATH, CLI_PATH):
        tree = ast.parse(path.read_text(encoding="utf-8"))
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
        assert not forbidden_modules & imported_roots
        source = path.read_text(encoding="utf-8")
        assert "rag_chunks" not in source
