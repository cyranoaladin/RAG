"""The public candidate's authority and numeric lineage remain fail-closed."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from nexus_release_chain.release_readiness import (
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
