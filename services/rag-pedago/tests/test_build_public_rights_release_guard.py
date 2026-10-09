"""Le producteur réel refuse une candidate publique avant toute écriture."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from conftest import load_producer


def _candidate_documents() -> dict[Path, bytes]:
    release = Path("release/profile_gate")
    sha = "a" * 64
    artifact_raw = json.dumps({
        "artifacts": [{"artifact_id": sha, "content_sha256": sha,
                       "chunks": [{"chunk_id": sha}]}],
    }).encode()
    artifact_sha = hashlib.sha256(artifact_raw).hexdigest()
    subject_raw = json.dumps({
        "collection": "test",
        "artifact_registry": {"path": "../artifacts.release.json", "sha256": artifact_sha},
        "placements": [{"artifact_id": sha, "collection": "test", "visibility": "public"}],
    }).encode()
    aggregate_raw = json.dumps({
        "release_id": "new-student-public-successor",
        "promotion_status": "NOT_PROMOTABLE",
        "activation_status": "NO_PRODUCTION_ACTIVATION",
        "review_status": "PRE_REVIEW",
        "artifact_registry": {"path": "artifacts.release.json", "sha256": artifact_sha},
        "subjects": [{"path": "subjects/test.release.json", "collection": "test",
                      "sha256": hashlib.sha256(subject_raw).hexdigest()}],
        "expected_counts": {"subjects": 1, "unique_artifacts": 1,
                            "placements": 1, "unique_chunks": 1},
    }).encode()
    registry_raw = json.dumps({"releases": [{
        "release_id": "new-student-public-successor",
        "collections": ["test"],
        "manifest_path": "profile_gate/production-profile-gate.release.json",
        "expected_manifest_sha256": hashlib.sha256(aggregate_raw).hexdigest(),
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
    }]}).encode()
    return {
        release / "production-profile-gate.release.json": aggregate_raw,
        release / "artifacts.release.json": artifact_raw,
        release / "subjects/test.release.json": subject_raw,
        release.parent / "release-registry.json": registry_raw,
    }


def test_main_refuses_public_release_without_sealed_rights_pack_before_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    builder = load_producer()
    monkeypatch.setattr(builder, "load_and_validate_exclusion_registry", lambda *a, **k: None)
    monkeypatch.setattr(builder, "load_governed_currentness_authority", lambda *a, **k: object())
    monkeypatch.setattr(builder, "require_canonical_runtime", lambda: "6.14.2")
    monkeypatch.setattr(builder, "build_release", lambda **_: _candidate_documents())
    monkeypatch.setattr(builder, "_write_documents", lambda *a, **k: pytest.fail(
        "release publique écrite avant le gate de droits"
    ))
    output_dir = tmp_path / "never-written"
    with pytest.raises(ValueError, match="SOURCE_MIRROR_AND_HEAD_REQUIRED"):
        builder.main([
            "--release-mode", "rehearsal", "--output-dir", str(output_dir),
            "--servability-matrix", str(tmp_path / "matrix.json"),
            "--servability-matrix-sha256", "f" * 64,
        ])
    assert not output_dir.exists()
