"""La proposition de droits lie précisément les 315 contenus V4/V5 retenus."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[3]
PROPOSAL = ROOT / "docs/governance/student_public_rights_decision_proposal_20261008.yml"
RELEASE_ROOT = ROOT / "services/rag-pedago/data/releases/prerentree_2026_2027"
RELEASES = {
    "production-profile-gate-2026-2027-v4": next(
        (RELEASE_ROOT / "profile_gate_v4").glob(
            "**/production-profile-gate.release.json"
        )
    ),
    "production-profile-gate-2026-2027-v5-hggsp": next(
        (RELEASE_ROOT / "profile_gate_hggsp_v5").glob(
            "**/production-profile-gate.release.json"
        )
    ),
}


def _checked_json(path: Path, expected_digest: str) -> dict:
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected_digest
    return json.loads(raw)


def test_rights_request_is_bound_to_exact_eduscol_content_set() -> None:
    proposal = yaml.safe_load(PROPOSAL.read_bytes())
    assert proposal["status"] == "PENDING_HUMAN_APPROVAL"
    scope = proposal["decision_scope"]
    assert scope["population"] == "libre"
    assert scope["rights_category_required"] == "officiel_public"
    assert scope["target_policy_visibility"] == "public"
    assert scope["target_placement_visibility"] == "public"
    assert scope["answer_generation_allowed"] is False

    content_ids: set[str] = set()
    collections: set[str] = set()
    placements = 0
    for specification in scope["source_releases"]:
        release_path = RELEASES[specification["release_id"]]
        release = _checked_json(release_path, specification["manifest_sha256"])
        assert release["release_id"] == specification["release_id"]
        registry_ref = release["artifact_registry"]
        artifact_registry = _checked_json(
            release_path.parent / registry_ref["path"], registry_ref["sha256"]
        )
        artifacts = {
            entry["artifact_id"]: entry for entry in artifact_registry["artifacts"]
        }
        selected = [
            subject
            for subject in release["subjects"]
            if specification["collections"] == 2 or "hggsp" not in subject["collection"]
        ]
        assert len(selected) == specification["collections"]
        local_placements = 0
        for subject_ref in selected:
            subject = _checked_json(
                release_path.parent / subject_ref["path"], subject_ref["sha256"]
            )
            assert subject["collection"] == subject_ref["collection"]
            assert subject["collection"] not in collections
            collections.add(subject["collection"])
            for placement in subject["placements"]:
                artifact_id = placement["artifact_id"]
                artifact = artifacts[artifact_id]
                assert artifact_id == artifact["content_sha256"]
                assert artifact["source_path"].startswith(
                    scope["all_sources_must_be_in_zone"]
                )
                content_ids.add(artifact_id)
                local_placements += 1
        assert local_placements == specification["placements"]
        placements += local_placements

    canonical = "".join(f"{digest}\n" for digest in sorted(content_ids)).encode()
    assert len(collections) == scope["collection_count"] == 11
    assert len(content_ids) == scope["artifact_count"] == 315
    assert placements == scope["placement_count"] == 479
    assert hashlib.sha256(canonical).hexdigest() == scope["content_sha256_set_digest"]
