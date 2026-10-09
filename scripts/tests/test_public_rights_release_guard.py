"""La release publique successeur ne peut reprendre un SHA exclu."""

from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from public_rights_release_guard import (  # noqa: E402
    PublicRightsReleaseError,
    require_public_release_rights,
)

A = "a" * 64
B = "b" * 64
CFTR = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"


def _documents(*, shas: tuple[str, ...] = (A,), visibility: str = "public") -> dict[Path, bytes]:
    root = Path("release/profile_gate")
    registry = {"artifacts": [{"artifact_id": sha, "content_sha256": sha,
                                "chunks": [{"chunk_id": sha}]} for sha in shas]}
    subject = {"collection": "rag_nexus_test", "placements": [
        {"artifact_id": sha, "collection": "rag_nexus_test", "visibility": visibility}
        for sha in shas
    ]}
    aggregate = {"release_id": "new-student-public-successor", "release_mode": "production",
                 "promotion_status": "NOT_PROMOTABLE",
                 "activation_status": "NO_PRODUCTION_ACTIVATION",
                 "review_status": "PRE_REVIEW",
                 "artifact_registry": {"path": "artifacts.release.json"},
                 "subjects": [{"path": "subjects/rag_nexus_test.release.json"}],
                 "expected_counts": {"unique_artifacts": len(shas), "placements": len(shas),
                                     "unique_chunks": len(shas), "subjects": 1}}
    return _seal_documents({
        root / "artifacts.release.json": json.dumps(registry).encode(),
        root / "subjects/rag_nexus_test.release.json": json.dumps(subject).encode(),
        root / "production-profile-gate.release.json": json.dumps(aggregate).encode(),
    })


def _seal_documents(documents: dict[Path, bytes]) -> dict[Path, bytes]:
    root = Path("release/profile_gate")
    artifact_path = root / "artifacts.release.json"
    subject_path = root / "subjects/rag_nexus_test.release.json"
    aggregate_path = root / "production-profile-gate.release.json"
    artifact_digest = hashlib.sha256(documents[artifact_path]).hexdigest()
    subject = json.loads(documents[subject_path])
    subject["artifact_registry"] = {"path": "../artifacts.release.json",
                                    "sha256": artifact_digest}
    documents[subject_path] = json.dumps(subject).encode()
    aggregate = json.loads(documents[aggregate_path])
    aggregate["artifact_registry"]["sha256"] = artifact_digest
    aggregate["subjects"][0]["sha256"] = hashlib.sha256(documents[subject_path]).hexdigest()
    documents[aggregate_path] = json.dumps(aggregate).encode()
    documents[root.parent / "release-registry.json"] = json.dumps({
        "registry_version": "1", "releases": [{
            "release_id": aggregate["release_id"],
            "collections": [subject["collection"]],
            "manifest_path": "profile_gate/production-profile-gate.release.json",
            "expected_manifest_sha256": hashlib.sha256(documents[aggregate_path]).hexdigest(),
            "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
        }],
    }).encode()
    return documents


def _gate(shas: tuple[str, ...] = (A,)) -> dict:
    return {"DELEGATED_RIGHTS_ADJUDICATION_PASS": True,
            "APPROVED_CONTENT_SHA256": list(shas),
            "EVIDENCE_PACK_SHA256": "e" * 64,
            "APPROVED_SOURCE_PLACEMENTS": {
                sha: {"rag_nexus_test": 1} for sha in shas
            },
            "APPROVED_SOURCE_CHUNKS_SHA256": {
                sha: hashlib.sha256((json.dumps(
                    [{"chunk_id": sha}], sort_keys=True, separators=(",", ":")
                ) + "\n").encode()).hexdigest() for sha in shas
            },
            "FINAL_POPULATION": {"collections": 1, "artifacts": len(shas),
                                 "placements": len(shas), "chunks": len(shas)}}


def test_public_candidate_with_exact_approved_set_passes(tmp_path: Path):
    result = require_public_release_rights(
        _documents(), repository_root=tmp_path, source_mirror_root=tmp_path,
        expected_head="f" * 40, gate_runner=lambda **_: _gate(),
    )
    assert result["PUBLIC_RIGHTS_GATE_PASS"] is True
    assert result["APPROVED_CONTENT_SHA256"] == [A]


def test_historical_internal_candidate_does_not_invoke_public_gate(tmp_path: Path):
    result = require_public_release_rights(
        _documents(visibility="internal"), repository_root=tmp_path,
        source_mirror_root=None, expected_head=None,
        gate_runner=lambda **_: pytest.fail("internal candidate invoked public gate"),
    )
    assert result["PUBLIC_RIGHTS_GATE_APPLICABLE"] is False


@pytest.mark.parametrize(
    ("documents", "gate_result", "expected"),
    [
        (_documents(shas=(A, CFTR)), _gate((A,)), "PUBLIC_SHA_NOT_APPROVED"),
        (_documents(shas=(A, B)), _gate((A, B, CFTR)), "APPROVED_SHA_NOT_IN_RELEASE"),
        (_documents(), {**_gate(), "DELEGATED_RIGHTS_ADJUDICATION_PASS": False},
         "DELEGATED_GATE_NOT_PASS"),
        (_documents(), {**_gate(), "EVIDENCE_PACK_SHA256": None},
         "EVIDENCE_PACK_DIGEST_MISSING"),
        (_documents(), {**_gate(), "FINAL_POPULATION": {"collections": 1,
            "artifacts": 315, "placements": 479, "chunks": 8268}},
         "PUBLIC_RELEASE_COUNTS_MISMATCH"),
    ],
)
def test_public_candidate_refuses_unapproved_or_forged_counts(
    tmp_path: Path, documents: dict[Path, bytes], gate_result: dict, expected: str
):
    with pytest.raises(PublicRightsReleaseError, match=expected):
        require_public_release_rights(
            documents, repository_root=tmp_path, source_mirror_root=tmp_path,
            expected_head="f" * 40, gate_runner=lambda **_: gate_result,
        )


def test_public_candidate_refuses_missing_mirror_or_head(tmp_path: Path):
    with pytest.raises(PublicRightsReleaseError, match="SOURCE_MIRROR_AND_HEAD_REQUIRED"):
        require_public_release_rights(
            _documents(), repository_root=tmp_path, source_mirror_root=None,
            expected_head=None, gate_runner=lambda **_: _gate(),
        )


def test_machine_pack_cannot_make_public_candidate_activable(tmp_path: Path):
    documents = _documents()
    aggregate_path = next(path for path in documents if path.name == "production-profile-gate.release.json")
    aggregate = json.loads(documents[aggregate_path])
    aggregate.update(promotion_status="PROMOTABLE", activation_status="PRODUCTION_ACTIVATION_ALLOWED",
                     review_status="REVIEWED")
    documents[aggregate_path] = json.dumps(aggregate).encode()
    with pytest.raises(PublicRightsReleaseError, match="FINAL_AUTHORITY_APPROVAL_REQUIRED"):
        require_public_release_rights(
            documents, repository_root=tmp_path, source_mirror_root=tmp_path,
            expected_head="f" * 40, gate_runner=lambda **_: _gate(),
        )


def test_public_candidate_refuses_mixed_internal_visibility(tmp_path: Path):
    documents = _documents(shas=(A, B))
    subject_path = next(path for path in documents if "subjects" in path.parts)
    subject = json.loads(documents[subject_path])
    subject["placements"][1]["visibility"] = "internal"
    documents[subject_path] = json.dumps(subject).encode()
    with pytest.raises(PublicRightsReleaseError, match="MIXED_PUBLIC_INTERNAL_RELEASE"):
        require_public_release_rights(
            documents, repository_root=tmp_path, source_mirror_root=tmp_path,
            expected_head="f" * 40, gate_runner=lambda **_: _gate((A, B)),
        )


def test_public_candidate_refuses_registry_artifact_identity_mismatch(tmp_path: Path):
    documents = _documents()
    registry_path = next(path for path in documents if path.name == "artifacts.release.json")
    registry = json.loads(documents[registry_path])
    registry["artifacts"][0]["artifact_id"] = B
    documents[registry_path] = json.dumps(registry).encode()
    _seal_documents(documents)
    with pytest.raises(PublicRightsReleaseError, match="PUBLIC_RELEASE_CONTENT_SET_INVALID"):
        require_public_release_rights(
            documents, repository_root=tmp_path, source_mirror_root=tmp_path,
            expected_head="f" * 40, gate_runner=lambda **_: _gate(),
        )


@pytest.mark.parametrize("target", ["artifact", "subject", "release_registry"])
def test_public_candidate_refuses_forged_manifest_bindings(tmp_path: Path, target: str):
    documents = _documents()
    aggregate_path = next(path for path in documents
                          if path.name == "production-profile-gate.release.json")
    if target == "release_registry":
        path = next(path for path in documents if path.name == "release-registry.json")
        value = json.loads(documents[path])
        value["releases"][0]["manifest_path"] = "other.json"
        value["releases"][0]["expected_manifest_sha256"] = "0" * 64
        documents[path] = json.dumps(value).encode()
        expected = "RELEASE_REGISTRY_BINDING_MISMATCH"
    else:
        aggregate = json.loads(documents[aggregate_path])
        if target == "artifact":
            aggregate["artifact_registry"]["sha256"] = "0" * 64
            expected = "RELEASE_REGISTRY_DIGEST_MISMATCH"
        else:
            aggregate["subjects"][0]["sha256"] = "0" * 64
            expected = "RELEASE_SUBJECT_DIGEST_MISMATCH"
        documents[aggregate_path] = json.dumps(aggregate).encode()
    with pytest.raises(PublicRightsReleaseError, match=expected):
        require_public_release_rights(
            documents, repository_root=tmp_path, source_mirror_root=tmp_path,
            expected_head="f" * 40, gate_runner=lambda **_: _gate(),
        )


def test_public_candidate_refuses_collection_remap_with_approved_sha(tmp_path: Path):
    documents = _documents()
    subject_path = next(path for path in documents if "subjects" in path.parts)
    subject = json.loads(documents[subject_path])
    subject["collection"] = "rogue_collection"
    subject["placements"][0]["collection"] = "rogue_collection"
    documents[subject_path] = json.dumps(subject).encode()
    _seal_documents(documents)
    with pytest.raises(PublicRightsReleaseError, match="PUBLIC_RELEASE_SOURCE_TOPOLOGY_MISMATCH"):
        require_public_release_rights(
            documents, repository_root=tmp_path, source_mirror_root=tmp_path,
            expected_head="f" * 40, gate_runner=lambda **_: _gate(),
        )


def test_public_candidate_refuses_changed_chunk_with_same_count(tmp_path: Path):
    documents = _documents()
    registry_path = next(path for path in documents if path.name == "artifacts.release.json")
    registry = json.loads(documents[registry_path])
    registry["artifacts"][0]["chunks"][0]["chunk_id"] = B
    documents[registry_path] = json.dumps(registry).encode()
    _seal_documents(documents)
    with pytest.raises(PublicRightsReleaseError, match="PUBLIC_RELEASE_SOURCE_CHUNKS_MISMATCH"):
        require_public_release_rights(
            documents, repository_root=tmp_path, source_mirror_root=tmp_path,
            expected_head="f" * 40, gate_runner=lambda **_: _gate(),
        )
