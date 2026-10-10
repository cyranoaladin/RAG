"""Le successeur reste un candidat distinct et non activable."""

from __future__ import annotations

import copy
import hashlib
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))
_builder = importlib.import_module("build_student_public_successor_release")
build_documents = _builder.build_documents
load_sources = _builder.load_sources
validate_inclusions = _builder.validate_inclusions
write_immutable = _builder.write_immutable


def _doc(documents: dict[Path, bytes], name: str) -> dict:
    return json.loads(next(value for path, value in documents.items() if path.name == name))


def _inclusion(source: dict, excluded: set[str]) -> dict:
    inputs = source["inputs"]
    artifacts = sorted(item["content_sha256"] for item in inputs["artifacts"]["artifacts"])
    pdf_by_sha = {item["content_sha256"]: item["source_pdf_sha256"]
                 for item in inputs["artifacts"]["artifacts"]}
    proof = {"pii_evidence_sha256": "a" * 64,
             "currentness_evidence_sha256": "b" * 64,
             "fresh_source_checkpoint_file_sha256": "c" * 64}
    decisions = [
        {"content_sha256": sha, "source_pdf_sha256": pdf_by_sha[sha],
         "disposition": "EXCLUDE" if sha in excluded else "INCLUDE",
         **proof, "evidence_sha256": hashlib.sha256(_builder.canonical(proof)).hexdigest()}
        for sha in artifacts
    ]
    return {
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_INCLUSIONS_V2",
        "source_candidate_manifest_sha256": inputs["candidate_manifest_sha256"],
        "rights_authority_sha256": inputs["release"]["authorities"]["rights_authority_sha256"],
        "source_candidate_inventory_sha256": hashlib.sha256(
            (json.dumps(source["inventory"], ensure_ascii=False, sort_keys=True, indent=2)
             + "\n").encode()
        ).hexdigest(),
        "pii_adjudication_report_sha256": "d" * 64,
        "source_currentness_attestation_sha256": "e" * 64,
        "fresh_source_index_file_sha256": "f" * 64,
        "fresh_source_index_logical_sha256": "1" * 64,
        "private_cas_manifest_sha256": "2" * 64,
        "source_currentness_valid_until_utc": "2099-01-01T00:00:00Z",
        "decision_count": len(decisions),
        "evidence_pack_sha256": hashlib.sha256(_builder.canonical(decisions)).hexdigest(),
        "decisions": decisions,
    }


def test_real_successor_has_fresh_immutable_manifests_and_explicit_blockers():
    source = load_sources(ROOT)
    excluded = source["inputs"]["artifacts"]["artifacts"][0]["content_sha256"]
    inclusion = _inclusion(source, {excluded})
    documents = build_documents(source, inclusion=inclusion)
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
        "FRESH_SOURCE_CURRENTNESS_AT_PROMOTION",
        "PRIVATE_BYTES_TRANSFER_RECEIPT",
        "SUCCESSOR_AUTHORIZATION_AND_BATCH_REVIEW",
    ]
    assert len([path for path in documents if path.suffix == ".yml"]) == 11
    pii = _doc(documents, "public_pii_registry.json")
    rights = _doc(documents, "public_rights_registry.json")
    currentness = _doc(documents, "public_currentness_registry.json")
    included_row = inclusion["decisions"][1]
    matching = next(row for row in pii["entries"]
                    if row["content_sha256"] == included_row["content_sha256"])
    assert pii["adjudication_report_sha256"] == inclusion["pii_adjudication_report_sha256"]
    assert matching["pii_gate_status"] == "PASS_BY_DERIVATIVE_FULL_TEXT_ADJUDICATION"
    assert matching["pii_evidence_sha256"] == included_row["pii_evidence_sha256"]
    right = next(row for row in rights["entries"]
                 if row["content_sha256"] == included_row["content_sha256"])
    assert rights["rights_authority_sha256"] == source["inputs"]["release"]["authorities"]["rights_authority_sha256"]
    assert right["rights_basis"] == "EDUSCOL_ETALAB_2_0_SITEWIDE"
    assert right["source_pdf_sha256"] == included_row["source_pdf_sha256"]
    assert right["currentness_evidence_sha256"] == included_row["currentness_evidence_sha256"]
    current = next(row for row in currentness["entries"]
                   if row["content_sha256"] == included_row["content_sha256"])
    assert current["currentness_evidence_sha256"] == included_row["currentness_evidence_sha256"]
    assert current["revocation_status"] == "PASS_CURRENT_OFFICIAL_PUBLICATION"
    assert index["kind"] == "NEXUS_STUDENT_PUBLIC_SUCCESSOR_PREPARATION_V2"
    assert index["verified_authorities"]["public_currentness_registry_sha256"] == hashlib.sha256(_builder.canonical(currentness)).hexdigest()
    proposed = index["proposed_scopes"]
    assert len(proposed) == 11
    assert {row["collection"]: row["final_subject_sha256"] for row in proposed} == {
        row["collection"]: row["sha256"] for row in aggregate["subjects"]
    }
    assert len({row["proposed_scope_id"] for row in proposed}) == 11
    assert all(row["status"] == "NOT_ISSUED" for row in proposed)
    assert all(row["proposed_scope_id"] ==
               f"student_public_{row['collection'].removeprefix('rag_nexus_')}_v1"
               for row in proposed)
    for row in index["complete_profiles"]:
        assert any(str(path).endswith(row["path"]) for path in documents)
    assert any(path.name == "public_profile_proposal.json" for path in documents)


def test_successor_subject_profiles_match_complete_public_profiles():
    source = load_sources(ROOT)
    documents = build_documents(source, inclusion=_inclusion(source, set()))
    profile_refs = source["profile_refs"]
    subjects = [json.loads(raw) for path, raw in documents.items()
                if path.parent.name == "subjects" and path.name.endswith(".release.json")]
    assert len(subjects) == 11
    for subject in subjects:
        expected = profile_refs[subject["collection"]]
        assert subject["profile"]["version"] == expected["profile_version"]
        assert subject["profile"]["fingerprint"] == expected["fingerprint"]
        registry = _doc(documents, "public_profiles.json")
        entry = next(row for row in registry["entries"]
                     if row["collection"] == subject["collection"])
        assert entry["profile_fingerprint"] == hashlib.sha256(
            _builder.canonical(entry["scope"])
        ).hexdigest()
        assert subject["profile"]["fingerprint"] != entry["profile_fingerprint"]
        assert subject["profile"]["manifest_digest"] == hashlib.sha256(
            _builder.canonical(registry)
        ).hexdigest()


def test_legacy_successor_replay_keeps_sealed_candidate_immutable():
    source = load_sources(ROOT)
    release_dir = next((ROOT / _builder.RELEASE_ROOT).glob("release-*"))
    inclusion = json.loads((release_dir / "profile_gate/inclusion_attestation.json").read_bytes())
    documents = build_documents(source, inclusion=inclusion, legacy_profile_binding=True)
    assert len(documents) == 34
    for relative, raw in documents.items():
        assert (ROOT / relative).read_bytes() == raw
    corrected = build_documents(source, inclusion=inclusion)
    assert _doc(corrected, "production-profile-gate.release.json")["release_id"] != (
        _doc(documents, "production-profile-gate.release.json")["release_id"]
    )


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
    with pytest.raises(ValueError, match="inclusion"):
        validate_inclusions(source, inclusion)
    inclusion = _inclusion(source, set())
    inclusion["decisions"].pop()
    with pytest.raises(ValueError, match="inclusion population"):
        validate_inclusions(source, inclusion)
    inclusion = _inclusion(source, set())
    inclusion["pii_adjudication_report_sha256"] = "bad"
    with pytest.raises(ValueError, match="inclusion authority"):
        validate_inclusions(source, inclusion)


def test_builder_refuses_to_empty_a_collection():
    source = load_sources(ROOT)
    first_collection = source["inventory"]["collections"][0]
    excluded = {row["content_sha256"] for row in first_collection["candidates"]}
    with pytest.raises(ValueError, match="collection empty"):
        build_documents(source, inclusion=_inclusion(source, excluded))


def test_builder_refuses_expired_currentness_receipt():
    source = load_sources(ROOT)
    inclusion = _inclusion(source, set())
    inclusion["source_currentness_valid_until_utc"] = "2026-10-01T00:00:00Z"
    with pytest.raises(ValueError, match="freshness expired"):
        build_documents(source, inclusion=inclusion)


def test_immutable_writer_refuses_divergent_existing_output(tmp_path):
    documents = {Path("release-registry.json"): b"one\n"}
    write_immutable(tmp_path, documents)
    write_immutable(tmp_path, documents)
    with pytest.raises(ValueError, match="immutable"):
        write_immutable(tmp_path, {Path("release-registry.json"): b"two\n"})
