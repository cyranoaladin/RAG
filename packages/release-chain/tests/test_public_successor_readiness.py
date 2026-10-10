"""The public candidate's authority and numeric lineage remain fail-closed."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from nexus_release_chain.release_readiness import (
    _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS,
    ReleaseReadinessError,
    _parse_v2_artifact_registry,
    load_release_expectation,
)

REPO = Path(__file__).resolve().parents[3]
CANDIDATES = list((REPO / "services/rag-pedago/data/releases").glob(
    "prerentree_2026_2027/profile_gate_student_public_v1/release-*/profile_gate"
))
assert len(CANDIDATES) == 1
CANDIDATE = CANDIDATES[0]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def test_candidate_authority_is_rejected_after_mode_change(tmp_path: Path) -> None:
    release = tmp_path / "profile_gate"
    shutil.copytree(CANDIDATE, release)
    aggregate_path = release / "production-profile-gate.release.json"
    aggregate = json.loads(aggregate_path.read_bytes())
    assert aggregate["release_mode"] == "candidate"
    aggregate.update(release_mode="production", promotion_status="PROMOTABLE",
                     activation_status="PRODUCTION_ACTIVATION_ALLOWED",
                     review_status="REVIEWED")
    aggregate_path.write_bytes(_canonical(aggregate))
    with pytest.raises(ReleaseReadinessError, match="authorit|candidate|successor"):
        load_release_expectation(aggregate_path, _sha(aggregate_path))


def _reseal_as_public_successor(tmp_path: Path) -> Path:
    release = tmp_path / "profile_gate"
    shutil.copytree(CANDIDATE, release)
    aggregate_path = release / "production-profile-gate.release.json"
    aggregate = json.loads(aggregate_path.read_bytes())
    release_id = "student-public-successor-schema-test"
    authorities = {name: "a" * 64 for name in _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS}
    aggregate.update(
        release_id=release_id, release_mode="public_successor",
        promotion_status="PROMOTABLE", activation_status="PRODUCTION_ACTIVATION_ALLOWED",
        review_status="REVIEWED", authorities=authorities,
    )
    registry_path = release / "artifacts.release.json"
    registry = json.loads(registry_path.read_bytes())
    registry["release_id"] = release_id
    registry_path.write_bytes(_canonical(registry))
    aggregate["artifact_registry"]["sha256"] = _sha(registry_path)
    for ref in aggregate["subjects"]:
        subject_path = release / ref["path"]
        subject = json.loads(subject_path.read_bytes())
        subject["release_id"] = f"{release_id}-{ref['collection']}"
        subject["authorities"] = authorities
        subject["artifact_registry"]["sha256"] = _sha(registry_path)
        subject["profile"]["manifest_digest"] = authorities["public_profile_manifest_sha256"]
        subject_path.write_bytes(_canonical(subject))
        ref["sha256"] = _sha(subject_path)
    aggregate_path.write_bytes(_canonical(aggregate))
    return aggregate_path


def test_public_successor_requires_complete_authorities_and_external_verification(
    tmp_path: Path,
) -> None:
    path = _reseal_as_public_successor(tmp_path)
    with pytest.raises(ReleaseReadinessError, match="external evidence verification unavailable"):
        load_release_expectation(path, _sha(path))
    aggregate = json.loads(path.read_bytes())
    aggregate["authorities"].pop("observed_transfer_receipt_sha256")
    path.write_bytes(_canonical(aggregate))
    with pytest.raises(ReleaseReadinessError, match="public successor.*authorit"):
        load_release_expectation(path, _sha(path))


def test_public_successor_rejects_malformed_digest_and_candidate_identity(
    tmp_path: Path,
) -> None:
    path = _reseal_as_public_successor(tmp_path)
    aggregate = json.loads(path.read_bytes())
    aggregate["authorities"]["derivative_currentness_evidence_sha256"] = "bad"
    path.write_bytes(_canonical(aggregate))
    with pytest.raises(ReleaseReadinessError, match="derivative_currentness_evidence_sha256"):
        load_release_expectation(path, _sha(path))
    aggregate["authorities"]["derivative_currentness_evidence_sha256"] = "a" * 64
    aggregate["release_id"] = "student-public-20261010-v1-eb39f6cd0423e184"
    path.write_bytes(_canonical(aggregate))
    with pytest.raises(ReleaseReadinessError, match="successor release_id"):
        load_release_expectation(path, _sha(path))


def test_public_successor_refuses_pdf_and_internal_placement(tmp_path: Path) -> None:
    path = _reseal_as_public_successor(tmp_path)
    aggregate = json.loads(path.read_bytes())
    registry_path = path.parent / "artifacts.release.json"
    registry = json.loads(registry_path.read_bytes())
    registry["artifacts"][0]["media_type"] = "application/pdf"
    registry_path.write_bytes(_canonical(registry))
    aggregate["artifact_registry"]["sha256"] = _sha(registry_path)
    path.write_bytes(_canonical(aggregate))
    with pytest.raises(ReleaseReadinessError, match="text derivatives only"):
        load_release_expectation(path, _sha(path))

    path = _reseal_as_public_successor(tmp_path / "second")
    aggregate = json.loads(path.read_bytes())
    subject_path = path.parent / aggregate["subjects"][0]["path"]
    subject = json.loads(subject_path.read_bytes())
    subject["placements"][0]["visibility"] = "internal"
    subject_path.write_bytes(_canonical(subject))
    aggregate["subjects"][0]["sha256"] = _sha(subject_path)
    path.write_bytes(_canonical(aggregate))
    with pytest.raises(ReleaseReadinessError, match="placement visibility"):
        load_release_expectation(path, _sha(path))


def test_public_successor_rejects_candidate_statuses(tmp_path: Path) -> None:
    path = _reseal_as_public_successor(tmp_path)
    aggregate = json.loads(path.read_bytes())
    aggregate.update(promotion_status="NOT_PROMOTABLE", review_status="PRE_REVIEW",
                     activation_status="NO_PRODUCTION_ACTIVATION")
    path.write_bytes(_canonical(aggregate))
    with pytest.raises(ReleaseReadinessError, match="public successor status mismatch"):
        load_release_expectation(path, _sha(path))


@pytest.mark.parametrize("field", ["chunk_count", "target_tokens", "approved_native_group_count"])
def test_candidate_lineage_rejects_float_equal_to_integer(field: str) -> None:
    registry = json.loads((CANDIDATE / "artifacts.release.json").read_bytes())
    aggregate = json.loads((CANDIDATE / "production-profile-gate.release.json").read_bytes())
    lineage = registry["artifacts"][0]["chunk_lineage"]
    lineage[field] = float(lineage[field])
    with pytest.raises(ReleaseReadinessError, match="chunk_lineage"):
        _parse_v2_artifact_registry(
            registry, "artifact registry",
            release_id=aggregate["release_id"],
            school_year=aggregate["school_year"],
            embedding_model=aggregate["models"]["embedding"]["model_id"],
            embedding_dimension=aggregate["models"]["embedding"]["dimension"],
        )
