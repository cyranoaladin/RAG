"""Le successeur reste un candidat distinct et non activable."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from build_student_public_successor_release import (
    build_documents,
    load_sources,
    validate_inclusions,
    write_immutable,
)

ROOT = Path(__file__).resolve().parents[2]


def _doc(documents: dict[Path, bytes], name: str) -> dict:
    return json.loads(next(value for path, value in documents.items() if path.name == name))


def _inclusion(source: dict, excluded: set[str]) -> dict:
    inputs = source["inputs"]
    artifacts = sorted(item["content_sha256"] for item in inputs["artifacts"]["artifacts"])
    return {
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_INCLUSIONS_V1",
        "source_candidate_manifest_sha256": inputs["candidate_manifest_sha256"],
        "source_candidate_inventory_sha256": hashlib.sha256(
            (json.dumps(source["inventory"], ensure_ascii=False, sort_keys=True, indent=2)
             + "\n").encode()
        ).hexdigest(),
        "pii_scan_report_sha256": "a" * 64,
        "decisions": [
            {"content_sha256": sha, "disposition": "EXCLUDE" if sha in excluded else "INCLUDE",
             "evidence_sha256": "b" * 64}
            for sha in artifacts
        ],
    }


def test_real_successor_has_fresh_immutable_manifests_and_explicit_blockers():
    source = load_sources(ROOT)
    excluded = source["inputs"]["artifacts"]["artifacts"][0]["content_sha256"]
    documents = build_documents(source, inclusion=_inclusion(source, {excluded}))
    aggregate = _doc(documents, "production-profile-gate.release.json")
    registry = _doc(documents, "release-registry.json")
    inventory = _doc(documents, "candidate_inventory.json")
    allowlist = _doc(documents, "private_transfer_allowlist.json")
    index = _doc(documents, "preparation-index.json")
    assert aggregate["release_id"].startswith("student-public-successor-")
    assert aggregate["release_id"] != index["source_candidate_release_id"]
    assert aggregate["expected_counts"] == {
        "subjects": 11,
        "unique_artifacts": 252,
        "placements": sum(1 for row in source["inputs"]["subjects"]
                          for placement in row["placements"] if placement["artifact_id"] != excluded),
        "unique_chunks": sum(len(row["chunks"]) for row in source["inputs"]["artifacts"]["artifacts"]
                             if row["content_sha256"] != excluded),
    }
    assert (aggregate["release_mode"], aggregate["promotion_status"],
            aggregate["review_status"], aggregate["activation_status"]) == (
                "candidate", "NOT_PROMOTABLE", "PRE_REVIEW", "NO_PRODUCTION_ACTIVATION",
            )
    assert len(aggregate["subjects"]) == 11
    assert len(registry["releases"]) == 1
    assert inventory["counts"]["unique_artifacts"] == 252
    assert inventory["counts"]["placements"] == aggregate["expected_counts"]["placements"]
    assert allowlist["transfer_status"] == "NOT_TRANSFERRED"
    assert index["status"] == "PREPARATION_ONLY_NOT_ACTIVABLE"
    assert index["blocking_evidence"] == [
        "EXACT_HEAD_SUCCESSOR_SCOPE_REVIEW",
        "DERIVATIVE_CURRENTNESS_EVIDENCE",
        "PRIVATE_BYTES_TRANSFER_RECEIPT",
        "SUCCESSOR_AUTHORIZATION_AND_BATCH_REVIEW",
    ]
    assert len([path for path in documents if path.suffix == ".yml"]) == 11
    for row in index["complete_profiles"]:
        assert any(str(path).endswith(row["path"]) for path in documents)
    assert any(path.name == "public_profile_proposal.json" for path in documents)


def test_builder_rejects_candidate_authority_sabotage():
    source = copy.deepcopy(load_sources(ROOT))
    source["inputs"]["release"]["promotion_status"] = "PROMOTABLE"
    with pytest.raises(ValueError, match="candidate status"):
        build_documents(source, inclusion=_inclusion(source, set()))


def test_builder_rejects_pdf_and_missing_profile():
    source = copy.deepcopy(load_sources(ROOT))
    source["inputs"]["artifacts"]["artifacts"][0]["media_type"] = "application/pdf"
    with pytest.raises(ValueError, match="text artifact"):
        build_documents(source, inclusion=_inclusion(source, set()))
    source = copy.deepcopy(load_sources(ROOT))
    source["profiles"].pop(next(iter(source["profiles"])))
    with pytest.raises(ValueError, match="profile population"):
        build_documents(source, inclusion=_inclusion(source, set()))


def test_attestation_required_and_sabotages_fail():
    source = load_sources(ROOT)
    with pytest.raises(ValueError, match="inclusion attestation required"):
        build_documents(source)
    inclusion = _inclusion(source, set())
    inclusion["decisions"][0]["disposition"] = "PENDING"
    with pytest.raises(ValueError, match="inclusion disposition"):
        validate_inclusions(source, inclusion)
    inclusion = _inclusion(source, set())
    inclusion["decisions"].pop()
    with pytest.raises(ValueError, match="inclusion population"):
        validate_inclusions(source, inclusion)
    inclusion = _inclusion(source, set())
    inclusion["pii_scan_report_sha256"] = "bad"
    with pytest.raises(ValueError, match="attestation authority"):
        validate_inclusions(source, inclusion)


def test_builder_refuses_to_empty_a_collection():
    source = load_sources(ROOT)
    first_collection = source["inventory"]["collections"][0]
    excluded = {row["content_sha256"] for row in first_collection["candidates"]}
    with pytest.raises(ValueError, match="collection empty"):
        build_documents(source, inclusion=_inclusion(source, excluded))


def test_immutable_writer_refuses_divergent_existing_output(tmp_path):
    documents = {Path("release-registry.json"): b"one\n"}
    write_immutable(tmp_path, documents)
    write_immutable(tmp_path, documents)
    with pytest.raises(ValueError, match="immutable"):
        write_immutable(tmp_path, {Path("release-registry.json"): b"two\n"})
