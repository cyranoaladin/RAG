"""A ne devient jamais une autorité publique par la seule présence de ses octets."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationError,
    verify_content_anchor,
    verify_content_authority_bindings,
    verify_content_currentness,
    verify_public_scope_registry,
    verify_public_successor_activation,
)

ROOT = Path(__file__).resolve().parents[3]
RELEASE = (
    ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027"
    / "profile_gate_student_public_successor_v1"
    / "release-fcc84331e7700042"
)
ANCHOR = (
    ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
)
ANCHOR_SHA = "159e6e25fa493325304f8c790dd67113b4c6ced72a2fa696a60799a9fe7255a0"


def test_real_content_anchor_is_replayed_without_activation() -> None:
    observed = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    assert observed.content_manifest_sha256 == (
        "b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78"
    )
    assert observed.release_registry_sha256 == (
        "3f34f56c18e514ba4b0e92698f4b9a15deaa425818a0513ab51d48877ea24028"
    )
    assert len(observed.subject_sha256_by_collection) == 11
    assert observed.expected_counts == {
        "subjects": 11,
        "unique_artifacts": 253,
        "placements": 377,
        "unique_chunks": 3975,
    }
    assert observed.activation_allowed is False


def test_content_currentness_expires_at_the_sealed_limit() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    expiry = verify_content_currentness(
        RELEASE, content, datetime(2026, 10, 10, 21, tzinfo=UTC),
    )
    assert expiry.isoformat() == "2026-10-11T13:39:22.520000+00:00"
    with pytest.raises(PublicSuccessorActivationError, match="currentness expired"):
        verify_content_currentness(RELEASE, content, expiry)


def test_c_content_authorities_must_restate_exact_a_bindings() -> None:
    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    index = json.loads((RELEASE / "preparation-index.json").read_bytes())
    manifest = json.loads((RELEASE / "profile_gate/production-profile-gate.release.json").read_bytes())
    anchor = json.loads(ANCHOR.read_bytes())
    authorities = {
        "source_candidate_release_manifest_sha256": index["source_candidate_manifest_sha256"],
        "source_preparation_release_manifest_sha256": content.content_manifest_sha256,
        "source_preparation_index_sha256": content.preparation_index_sha256,
        "candidate_inventory_sha256": content.candidate_inventory_sha256,
        "inclusion_attestation_sha256": anchor["preparation_sidecars"]["inclusion_attestation.json"],
        "derivative_pii_evidence_sha256": index["pii_adjudication_report_sha256"],
        "derivative_currentness_evidence_sha256": index["source_currentness_attestation_sha256"],
        "public_profile_manifest_sha256": anchor["preparation_sidecars"]["public_profiles.json"],
        "public_rights_registry_sha256": anchor["preparation_sidecars"]["public_rights_registry.json"],
        "public_pii_registry_sha256": anchor["preparation_sidecars"]["public_pii_registry.json"],
        "rights_authority_sha256": manifest["authorities"]["rights_authority_sha256"],
        "delegated_evidence_pack_sha256": manifest["authorities"]["delegated_evidence_pack_sha256"],
        "pr300_final_authority_receipt_sha256": manifest["authorities"]["pr300_final_authority_receipt_sha256"],
    }
    verify_content_authority_bindings(RELEASE, content, authorities)
    for field in authorities:
        changed = {**authorities, field: "f" * 64}
        with pytest.raises(PublicSuccessorActivationError, match=field):
            verify_content_authority_bindings(RELEASE, content, changed)


@pytest.mark.parametrize(
    "relative",
    [
        "release-registry.json",
        "profile_gate/public_profiles.json",
        "profile_gate/public_rights_registry.json",
        "profile_gate/public_pii_registry.json",
        "profile_gate/public_currentness_registry.json",
        "profile_gate/inclusion_attestation.json",
        "profile_gate/subjects/rag_nexus_svt_premiere_specialite.release.json",
        "profile_gate/profiles/rag_nexus_svt_premiere_specialite.yml",
    ],
)
def test_missing_referenced_content_is_refused(tmp_path: Path, relative: str) -> None:
    copied = tmp_path / "release"
    shutil.copytree(RELEASE, copied)
    (copied / relative).unlink()
    with pytest.raises(PublicSuccessorActivationError):
        verify_content_anchor(ANCHOR, ANCHOR_SHA, copied)


def test_content_anchor_without_final_envelope_cannot_activate(tmp_path: Path) -> None:
    (tmp_path / "release").symlink_to(RELEASE, target_is_directory=True)
    (tmp_path / "content-anchor.json").write_bytes(ANCHOR.read_bytes())
    with pytest.raises(PublicSuccessorActivationError, match="authority envelope"):
        verify_public_successor_activation(
            tmp_path,
            expected_content_anchor_sha256=ANCHOR_SHA,
            expected_authority_envelope_sha256="f" * 64,
            expected_release_id="student-public-successor-20261010-fcc84331e7700042",
            expected_registry_sha256="3f34f56c18e514ba4b0e92698f4b9a15deaa425818a0513ab51d48877ea24028",
            expected_scope_authority_sha256="e" * 64,
        )


def test_internal_symlink_is_refused_even_with_identical_bytes(tmp_path: Path) -> None:
    copied = tmp_path / "release"
    shutil.copytree(RELEASE, copied)
    path = copied / "profile_gate/public_profiles.json"
    target = copied / "profile_gate/public_profiles-original.json"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(PublicSuccessorActivationError, match="symlink"):
        verify_content_anchor(ANCHOR, ANCHOR_SHA, copied)


def _scope_fixture(tmp_path: Path) -> tuple[Path, str, object]:
    from nexus_contracts.scope import RetrievalScopeArtifactV3

    content = verify_content_anchor(ANCHOR, ANCHOR_SHA, RELEASE)
    collection = "rag_nexus_hggsp_premiere_specialite"
    old = json.loads((ROOT / "packages/contracts/src/nexus_contracts/artifacts"
                      / "retrieval-scope-prod-hggsp-premiere-specialite-v3.json").read_text())
    target = old.pop("target_identity")
    old["artifact_version"] = "3"
    old["source_sha256"] = content.subject_sha256_by_collection[collection]
    old["target_policy"] = {
        **{key: value for key, value in target.items() if key not in ("audience", "candidates")},
        "audiences": [target["audience"]],
        "candidates": target["candidates"],
        "roles": ["student"],
    }
    old["evidence_subject"]["visibility"] = "public"
    old["evidence_subject"]["rights"] = ["public_allowed"]
    scope = RetrievalScopeArtifactV3.model_validate(old)
    scope_path = tmp_path / "scopes" / "hggsp.json"
    scope_path.parent.mkdir(parents=True)
    scope_path.write_bytes(scope.canonical_bytes())
    registry = {
        "kind": "NEXUS_STUDENT_PUBLIC_SCOPE_REGISTRY_V1",
        "status": "SCOPES_ISSUED_NOT_PUBLICATION_AUTHORITY",
        "activation_allowed": False,
        "content_anchor_sha256": ANCHOR_SHA,
        "content_manifest_sha256": content.content_manifest_sha256,
        "policy_registry_sha256": "a" * 64,
        "successor_authority_sha256": "b" * 64,
        "scopes": [{
            "collection": collection, "scope_id": scope.scope_id,
            "resource": "scopes/hggsp.json", "sha256": scope.sha256_digest(),
            "source_sha256": scope.source_sha256, "artifact_version": "3",
        }],
    }
    raw = (json.dumps(registry, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode()
    path = tmp_path / "scope-registry.json"
    path.write_bytes(raw)
    one_subject = replace(content, subject_sha256_by_collection={
        collection: content.subject_sha256_by_collection[collection],
    })
    return path, hashlib.sha256(raw).hexdigest(), one_subject


def test_scope_registry_binds_student_public_v3_to_a(tmp_path: Path) -> None:
    path, digest, content = _scope_fixture(tmp_path)
    scopes = verify_public_scope_registry(path, digest, content, RELEASE)
    assert len(scopes) == 1
    assert scopes[0].target_policy.roles == ["student"]


@pytest.mark.parametrize("change", ["source", "role", "visibility", "rights"])
def test_scope_registry_refuses_wrong_scope_semantics(tmp_path: Path, change: str) -> None:
    path, digest, content = _scope_fixture(tmp_path)
    scope_path = tmp_path / "scopes/hggsp.json"
    scope = json.loads(scope_path.read_bytes())
    if change == "source":
        scope["source_sha256"] = "f" * 64
    elif change == "role":
        scope["target_policy"]["roles"] = ["teacher"]
    elif change == "visibility":
        scope["evidence_subject"]["visibility"] = "internal"
    else:
        scope["evidence_subject"]["rights"] = ["officiel_public"]
    scope_path.write_bytes(json.dumps(scope, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode())
    with pytest.raises(PublicSuccessorActivationError):
        verify_public_scope_registry(path, digest, content, RELEASE)
