"""Le contenu immutable précède les autorités de publication externes."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
from build_public_successor_content_anchor import (
    ContentAnchorError,
    build_authority_envelope,
    build_content_anchor,
    canonical_bytes,
    inspect_content_preparation,
    inspect_envelope_preparation,
    write_content_anchor,
)

REPO = Path(__file__).resolve().parents[2]
PREPARATION = REPO / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-fcc84331e7700042"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_anchor_binds_exact_preparation_without_claiming_publication() -> None:
    manifest = PREPARATION / "profile_gate/production-profile-gate.release.json"
    anchor = build_content_anchor(manifest, _sha(manifest))
    assert anchor["kind"] == "NEXUS_PUBLIC_SUCCESSOR_CONTENT_ANCHOR_V1"
    assert anchor["content_manifest_sha256"] == _sha(manifest)
    assert anchor["preparation_index_sha256"] == _sha(PREPARATION / "preparation-index.json")
    assert anchor["expected_counts"] == {
        "subjects": 11, "unique_artifacts": 253,
        "placements": 377, "unique_chunks": 3975,
    }
    assert len(anchor["subjects"]) == 11
    assert all(row["subject_sha256"] == _sha(manifest.parent / row["path"])
               for row in anchor["subjects"])
    assert anchor["status"] == "CONTENT_ONLY_NOT_ACTIVABLE"
    assert anchor["activation_allowed"] is False
    assert "authorities" not in anchor


def test_real_content_inclusion_can_pass_without_an_authority_envelope() -> None:
    manifest = PREPARATION / "profile_gate/production-profile-gate.release.json"
    result = inspect_content_preparation(manifest, _sha(manifest))
    assert result["inclusion_population_verified"] is True
    assert result["content_manifest_sha256"] == _sha(manifest)
    assert result["private_cas_replay_verified"] is False
    assert result["activation_allowed"] is False


def test_anchor_refuses_changed_subject_even_with_resigned_manifest(tmp_path: Path) -> None:
    release = tmp_path / "release"
    shutil.copytree(PREPARATION, release)
    manifest = release / "profile_gate/production-profile-gate.release.json"
    doc = json.loads(manifest.read_bytes())
    subject = manifest.parent / doc["subjects"][0]["path"]
    changed = json.loads(subject.read_bytes())
    changed["release_id"] = "student-public-successor-substituted"
    subject.write_bytes(canonical_bytes(changed))
    doc["subjects"][0]["sha256"] = _sha(subject)
    manifest.write_bytes(canonical_bytes(doc))
    with pytest.raises(ContentAnchorError):
        build_content_anchor(manifest, _sha(manifest))


def test_anchor_refuses_preparation_index_substitution(tmp_path: Path) -> None:
    release = tmp_path / "release"
    shutil.copytree(PREPARATION, release)
    index = release / "preparation-index.json"
    doc = json.loads(index.read_bytes())
    doc["proposed_scopes"][0]["status"] = "ISSUED"
    index.write_bytes(canonical_bytes(doc))
    manifest = release / "profile_gate/production-profile-gate.release.json"
    with pytest.raises(ContentAnchorError):
        build_content_anchor(manifest, _sha(manifest))


@pytest.mark.parametrize("sidecar", [
    "public_profiles.json", "public_rights_registry.json",
    "public_pii_registry.json", "public_currentness_registry.json",
    "inclusion_attestation.json",
])
def test_anchor_refuses_missing_referenced_sidecar(
    tmp_path: Path, sidecar: str,
) -> None:
    release = tmp_path / "release"
    shutil.copytree(PREPARATION, release)
    (release / "profile_gate" / sidecar).unlink()
    manifest = release / "profile_gate/production-profile-gate.release.json"
    with pytest.raises(ContentAnchorError, match="sidecar"):
        build_content_anchor(manifest, _sha(manifest))


def test_anchor_refuses_changed_referenced_sidecar(tmp_path: Path) -> None:
    release = tmp_path / "release"
    shutil.copytree(PREPARATION, release)
    sidecar = release / "profile_gate/public_profiles.json"
    sidecar.write_bytes(sidecar.read_bytes() + b" ")
    manifest = release / "profile_gate/production-profile-gate.release.json"
    with pytest.raises(ContentAnchorError, match="sidecar"):
        build_content_anchor(manifest, _sha(manifest))


def test_inclusion_replay_refuses_unhandled_exclusion_in_content_anchor(
    tmp_path: Path,
) -> None:
    release = tmp_path / "release"
    shutil.copytree(PREPARATION, release)
    index = release / "preparation-index.json"
    document = json.loads(index.read_bytes())
    document["excluded_derivative_count"] = 1
    index.write_bytes(canonical_bytes(document))
    manifest = release / "profile_gate/production-profile-gate.release.json"
    with pytest.raises(ContentAnchorError, match="source inventory"):
        inspect_content_preparation(manifest, _sha(manifest))


def test_anchor_refuses_rewriting_a_divergent_output(tmp_path: Path) -> None:
    manifest = PREPARATION / "profile_gate/production-profile-gate.release.json"
    anchor = build_content_anchor(manifest, _sha(manifest))
    target = tmp_path / "anchor.json"
    write_content_anchor(target, anchor)
    write_content_anchor(target, anchor)
    target.write_text("{}\n")
    with pytest.raises(ContentAnchorError):
        write_content_anchor(target, anchor)


def test_external_authority_envelope_is_bytes_only_and_never_activates(
    tmp_path: Path,
) -> None:
    manifest = PREPARATION / "profile_gate/production-profile-gate.release.json"
    anchor = build_content_anchor(manifest, _sha(manifest))
    anchor_path = tmp_path / "anchor.json"
    write_content_anchor(anchor_path, anchor)
    from nexus_release_chain.release_readiness import (
        _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS,
    )

    evidence = {}
    for field in _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS:
        path = tmp_path / field
        path.write_bytes(canonical_bytes({"fixture_field": field}))
        evidence[field] = path
    evidence["source_preparation_release_manifest_sha256"] = manifest
    evidence["source_preparation_index_sha256"] = PREPARATION / "preparation-index.json"
    evidence["candidate_inventory_sha256"] = PREPARATION / "profile_gate/candidate_inventory.json"
    envelope = build_authority_envelope(anchor_path, _sha(anchor_path), evidence)
    assert envelope["kind"] == "NEXUS_PUBLIC_SUCCESSOR_AUTHORITY_ENVELOPE_V1"
    assert envelope["content_anchor_sha256"] == _sha(anchor_path)
    assert envelope["content_manifest_sha256"] == _sha(manifest)
    assert envelope["status"] == "EVIDENCE_BYTES_ONLY_NOT_ACTIVABLE"
    assert envelope["activation_allowed"] is False
    assert len(envelope["authorities"]) == 21


def test_authority_envelope_refuses_missing_or_wrong_content_anchor(tmp_path: Path) -> None:
    manifest = PREPARATION / "profile_gate/production-profile-gate.release.json"
    anchor = build_content_anchor(manifest, _sha(manifest))
    anchor_path = tmp_path / "anchor.json"
    write_content_anchor(anchor_path, anchor)
    with pytest.raises(ContentAnchorError):
        build_authority_envelope(anchor_path, _sha(anchor_path), {})


def test_inclusion_population_is_replayed_but_cannot_activate(tmp_path: Path) -> None:
    manifest = PREPARATION / "profile_gate/production-profile-gate.release.json"
    anchor = build_content_anchor(manifest, _sha(manifest))
    anchor_path = tmp_path / "anchor.json"
    write_content_anchor(anchor_path, anchor)
    from nexus_release_chain.release_readiness import (
        _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS,
    )

    evidence = {}
    for field in _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS:
        path = tmp_path / field
        path.write_bytes(canonical_bytes({"fixture_field": field}))
        evidence[field] = path
    evidence["source_preparation_release_manifest_sha256"] = manifest
    evidence["source_preparation_index_sha256"] = PREPARATION / "preparation-index.json"
    evidence["candidate_inventory_sha256"] = PREPARATION / "profile_gate/candidate_inventory.json"
    evidence["inclusion_attestation_sha256"] = PREPARATION / "profile_gate/inclusion_attestation.json"
    envelope = build_authority_envelope(anchor_path, _sha(anchor_path), evidence)
    result = inspect_envelope_preparation(anchor_path, envelope, evidence)
    assert result["inclusion_population_verified"] is True
    assert result["private_cas_replay_verified"] is False
    assert result["semantic_verification_complete"] is False
    assert result["activation_allowed"] is False
    assert "publication_batch_review_receipt_sha256" in result["unverified_authorities"]


def test_inclusion_replay_refuses_resealed_wrong_pdf(tmp_path: Path) -> None:
    manifest = PREPARATION / "profile_gate/production-profile-gate.release.json"
    anchor = build_content_anchor(manifest, _sha(manifest))
    anchor_path = tmp_path / "anchor.json"
    write_content_anchor(anchor_path, anchor)
    from nexus_release_chain.release_readiness import (
        _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS,
    )

    evidence = {}
    for field in _PUBLIC_SUCCESSOR_PROMOTION_AUTHORITY_FIELDS:
        path = tmp_path / field
        path.write_bytes(canonical_bytes({"fixture_field": field}))
        evidence[field] = path
    evidence["source_preparation_release_manifest_sha256"] = manifest
    evidence["source_preparation_index_sha256"] = PREPARATION / "preparation-index.json"
    evidence["candidate_inventory_sha256"] = PREPARATION / "profile_gate/candidate_inventory.json"
    inclusion = json.loads((PREPARATION / "profile_gate/inclusion_attestation.json").read_bytes())
    inclusion["decisions"][0]["source_pdf_sha256"] = "a" * 64
    modified = tmp_path / "modified_inclusion.json"
    modified.write_bytes(canonical_bytes(inclusion))
    evidence["inclusion_attestation_sha256"] = modified
    envelope = build_authority_envelope(anchor_path, _sha(anchor_path), evidence)
    with pytest.raises(ContentAnchorError):
        inspect_envelope_preparation(anchor_path, envelope, evidence)
    anchor["content_manifest_sha256"] = "a" * 64
    anchor_path.write_bytes(canonical_bytes(anchor))
    with pytest.raises(ContentAnchorError):
        build_authority_envelope(anchor_path, _sha(anchor_path), {})
