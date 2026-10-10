"""L'ingestion de A requiert une phase INGESTION signée et exacte."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/rag-engine/src"))

from ingestor.ingestion_worker import sealed_release_ingestion_cli as cli  # noqa: E402
from ingestor.ingestion_worker.sealed_release_ingestion import (  # noqa: E402
    SealedReleaseIngestionError,
)

RELEASE = (
    ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
    / "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)
ANCHOR = (
    ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
)
ANCHOR_SHA = "159e6e25fa493325304f8c790dd67113b4c6ced72a2fa696a60799a9fe7255a0"


def _receipt(tmp_path: Path) -> tuple[Path, str]:
    anchor = json.loads(ANCHOR.read_bytes())
    index = json.loads((RELEASE / "preparation-index.json").read_bytes())
    receipt = {
        "kind": "NEXUS_PUBLIC_SUCCESSOR_PREISSUANCE_CHECKPOINT_V1",
        "status": "CHECKPOINT_ONLY_NOT_SCOPE_AUTHORITY",
        "content_anchor_sha256": ANCHOR_SHA,
        "content_manifest_sha256": anchor["content_manifest_sha256"],
        "manifest_relative_path": "release/profile_gate/production-profile-gate.release.json",
        "preparation_index_sha256": anchor["preparation_index_sha256"],
        "private_cas_index_sha256": index["private_cas_manifest_sha256"],
        "source_currentness_valid_until_utc": index[
            "source_currentness_valid_until_utc"
        ],
        "subject_sha256_by_collection": {
            row["collection"]: row["subject_sha256"] for row in anchor["subjects"]
        },
    }
    path = tmp_path / "preissuance.json"
    path.write_bytes((json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def _readiness(receipt_sha: str, *, phase: str | None = "INGESTION") -> object:
    return SimpleNamespace(manifest=SimpleNamespace(
        allowed_release_id="student-public-successor-20261010-fcc84331e7700042",
        allowed_release_manifest_sha256=(
            "b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78"
        ),
        public_successor_phase=phase,
        public_successor_content_anchor_digest=ANCHOR_SHA,
        public_successor_phase_authority_digest=receipt_sha,
    ))


def test_worker_a_refuses_a_without_signed_ingestion_phase(tmp_path: Path) -> None:
    receipt, digest = _receipt(tmp_path)
    with pytest.raises(SealedReleaseIngestionError, match="INGESTION"):
        cli._require_public_candidate_ingestion_authority(
            _readiness(digest, phase=None), RELEASE / "profile_gate", ANCHOR,
            receipt, digest,
        )


def test_worker_a_refuses_receipt_not_bound_to_signed_phase(tmp_path: Path) -> None:
    receipt, digest = _receipt(tmp_path)
    with pytest.raises(SealedReleaseIngestionError, match="phase authority"):
        cli._require_public_candidate_ingestion_authority(
            _readiness("a" * 64), RELEASE / "profile_gate", ANCHOR,
            receipt, digest,
        )


def test_worker_a_refuses_changed_receipt_even_when_digest_recomputed(tmp_path: Path) -> None:
    receipt, _ = _receipt(tmp_path)
    payload = json.loads(receipt.read_bytes())
    payload["private_cas_index_sha256"] = "a" * 64
    receipt.write_bytes((json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode())
    digest = hashlib.sha256(receipt.read_bytes()).hexdigest()
    with pytest.raises(SealedReleaseIngestionError, match="checkpoint"):
        cli._require_public_candidate_ingestion_authority(
            _readiness(digest), RELEASE / "profile_gate", ANCHOR,
            receipt, digest,
        )


def test_worker_a_accepts_a_for_ingestion_only_with_exact_signed_inputs(tmp_path: Path) -> None:
    receipt, digest = _receipt(tmp_path)
    content = cli._require_public_candidate_ingestion_authority(
        _readiness(digest), RELEASE / "profile_gate", ANCHOR,
        receipt, digest,
    )
    assert content.content_anchor_sha256 == ANCHOR_SHA
    assert content.expected_counts == {
        "subjects": 11, "unique_artifacts": 253, "placements": 377,
        "unique_chunks": 3975,
    }
    assert content.activation_allowed is False
