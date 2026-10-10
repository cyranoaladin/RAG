"""Les profils de la nouvelle release publique restent liés aux sources scellées."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from nexus_contracts.ingestion import collection_profile_fingerprint

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/rag-pedago/scripts"))

from build_student_public_promotion import (  # noqa: E402
    build_public_profile_proposal_documents,
    project_public_profiles,
)
from nexus_contracts.profile_manifest import strict_yaml_mapping  # noqa: E402

CANDIDATE = next((ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
                  / "profile_gate_student_public_v1").glob("release-*/profile_gate"))


def test_projects_eleven_complete_public_profiles_from_approved_sources() -> None:
    profiles = project_public_profiles(ROOT, CANDIDATE)
    assert len(profiles) == 11
    assert len({collection_profile_fingerprint(p) for p in profiles.values()}) == 11
    for collection, profile in profiles.items():
        assert profile.scope.collection == collection
        assert profile.scope.visibility == "public"
        assert [value.value for value in profile.scope.audience] == ["libre", "aefe"]
        assert profile.profile_version == "student-public-derivative-v1"
        assert profile.publication.auto_publish is False
        assert profile.expected_topics


def test_refuses_candidate_scope_tampering_even_when_json_is_valid(tmp_path: Path) -> None:
    proposal = json.loads((CANDIDATE / "public_profiles.json").read_bytes())
    proposal["entries"][0]["scope"]["matiere"] = "histoire"
    copied = tmp_path / "candidate"
    copied.mkdir()
    (copied / "public_profiles.json").write_text(json.dumps(proposal))
    (copied / "production-profile-gate.release.json").write_bytes(
        (CANDIDATE / "production-profile-gate.release.json").read_bytes()
    )
    with pytest.raises(ValueError, match="digest|scope|proposal"):
        project_public_profiles(ROOT, copied)


def test_refuses_student_role_in_pedagogical_audience(tmp_path: Path) -> None:
    proposal = json.loads((CANDIDATE / "public_profiles.json").read_bytes())
    proposal["entries"][0]["scope"]["audience"] = ["student", "teacher"]
    copied = tmp_path / "candidate"
    copied.mkdir()
    (copied / "public_profiles.json").write_text(json.dumps(proposal))
    (copied / "production-profile-gate.release.json").write_bytes(
        (CANDIDATE / "production-profile-gate.release.json").read_bytes()
    )
    with pytest.raises(ValueError, match="digest|audience|proposal"):
        project_public_profiles(ROOT, copied)


def test_renders_only_proposed_profiles_without_claiming_human_approval(tmp_path: Path) -> None:
    documents = build_public_profile_proposal_documents(ROOT, CANDIDATE, tmp_path)
    profiles = project_public_profiles(ROOT, CANDIDATE)
    profile_paths = sorted(path for path in documents if path.suffix == ".yml")
    assert len(profile_paths) == 11
    proposal = json.loads(documents[tmp_path / "public_profile_proposal.json"])
    assert proposal["status"] == "PENDING_EXACT_HEAD_AUTHORITY_REVIEW"
    assert len(proposal["entries"]) == 11
    assert "approved_by" not in json.dumps(proposal)
    assert not any(path.name.startswith("ingestion_manifest") for path in documents)
    for row in proposal["entries"]:
        raw = documents[tmp_path / row["path"]]
        profile = strict_yaml_mapping(raw, source=row["path"])
        assert profile["scope"]["visibility"] == "public"
        assert profile["scope"]["audience"] == ["libre", "aefe"]
        assert profile["publication"]["auto_publish"] is False
        assert row["fingerprint"] == collection_profile_fingerprint(
            profiles[row["collection"]]
        )


def test_versioned_profile_proposal_matches_exact_reprojection() -> None:
    output = ROOT / "services/rag-engine/configs/ingestion_profiles/student_public_derivative_v1"
    generated = build_public_profile_proposal_documents(ROOT, CANDIDATE, output)
    assert {path.name for path in generated} == {path.name for path in output.iterdir()}
    for path, raw in generated.items():
        assert path.read_bytes() == raw
