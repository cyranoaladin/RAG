"""Le verdict étudiant découle des preuves, jamais d'un texte libre d'agent."""

from __future__ import annotations

import ast
import copy
import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from adjudicate_student_public_rights import (  # noqa: E402
    adjudicate_artifact,
    build_artifact_record,
    build_pack_index,
    copy_cas_receipt,
    final_population,
    materialize_pack,
    project_page_scans,
    render_decision_sheet,
    source_population_refs,
)


def test_cli_entrypoint_is_after_all_function_definitions() -> None:
    path = Path(__file__).resolve().parents[1] / "go_live/adjudicate_student_public_rights.py"
    module = ast.parse(path.read_text())
    entrypoints = [
        node for node in module.body
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Compare)
        and isinstance(node.test.left, ast.Name)
        and node.test.left.id == "__name__"
    ]
    assert len(entrypoints) == 1
    assert module.body[-1] is entrypoints[0]


def test_copy_cas_receipt_verifies_digest_and_layout(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    payload = b'{"observation":"PASS"}'
    digest = hashlib.sha256(payload).hexdigest()
    path = source / digest[:2] / f"{digest}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload)
    copy_cas_receipt(source, target, digest)
    assert (target / digest[:2] / f"{digest}.json").read_bytes() == payload


def test_copy_cas_receipt_rejects_tampered_source(tmp_path: Path) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    digest = hashlib.sha256(b"good").hexdigest()
    path = source / digest[:2] / f"{digest}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"bad")
    with pytest.raises(ValueError, match="CAS_RECEIPT_DIGEST_MISMATCH"):
        copy_cas_receipt(source, target, digest)


CFTR = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
SHA = "a" * 64


def accepted_evidence() -> dict:
    return {
        "artifact_id": SHA,
        "content_sha256": SHA,
        "source_uri": "https://eduscol.education.gouv.fr/sites/default/files/document/exact.pdf",
        "page_count": 2,
        "rights_basis": "EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE",
        "rights_evidence_uri": "https://eduscol.education.gouv.fr/4656/mentions-legales",
        "license_or_terms_excerpt_hash": "b" * 64,
        "source_receipt_sha256": "9" * 64,
        "evidence_pages": [1, 2],
        "third_party_status": "CLEARED_WITH_EVIDENCE",
        "pii_status": "PASS",
        "currentness_status": "PASS",
        "revocation_status": "PASS",
        "student_suitability": "PASS",
        "source_verification": {
            "status": "VERIFIED",
            "exact_pdf_uri": "https://eduscol.education.gouv.fr/sites/default/files/document/exact.pdf",
            "remote_pdf_sha256": SHA,
            "observed_at_utc": "2026-10-09T20:00:00Z",
            "source_last_updated_at_utc": "2026-09-01T00:00:00Z",
            "terms_uri": "https://eduscol.education.gouv.fr/4656/mentions-legales",
            "terms_sha256": "b" * 64,
            "terms_observed_at_utc": "2026-10-09T20:00:00Z",
            "revocation_evidence_uri": "https://eduscol.education.gouv.fr/sites/default/files/document/exact.pdf",
        },
        "reviewer_a": {
            "identity": "rights-agent-a@1",
            "verdict": "PASS",
            "prompt_sha256": "c" * 64,
            "model_version": "rights-model@1",
            "context_sha256": "d" * 64,
            "observation_sha256": "1" * 64,
            "complete": True,
            "confidence": "HIGH",
            "pages_covered": [1, 2],
            "evidence_refs": ["sha256:" + "5" * 64],
        },
        "reviewer_b": {
            "identity": "suitability-agent-b@1",
            "verdict": "PASS",
            "prompt_sha256": "e" * 64,
            "model_version": "suitability-model@1",
            "context_sha256": "f" * 64,
            "observation_sha256": "2" * 64,
            "complete": True,
            "confidence": "HIGH",
            "pages_covered": [1, 2],
            "evidence_refs": ["sha256:" + "6" * 64],
        },
        "candidate_replays": [
            {"run_index": 1, "run_nonce": 0,
             "reviewer_a_observation_sha256": "1" * 64,
             "reviewer_b_observation_sha256": "2" * 64,
             "reviewer_a_context_sha256": "d" * 64,
             "reviewer_b_context_sha256": "f" * 64,
             "reviewer_a_evidence_refs": ["sha256:" + "5" * 64],
             "reviewer_b_evidence_refs": ["sha256:" + "6" * 64],
             "candidate_verdict": "PASS"},
            {"run_index": 2, "run_nonce": 1,
             "reviewer_a_observation_sha256": "1" * 64,
             "reviewer_b_observation_sha256": "2" * 64,
             "reviewer_a_context_sha256": "3" * 64,
             "reviewer_b_context_sha256": "4" * 64,
             "reviewer_a_evidence_refs": ["sha256:" + "7" * 64],
             "reviewer_b_evidence_refs": ["sha256:" + "8" * 64],
             "candidate_verdict": "PASS"},
        ],
        "checks": {
            "exact_bytes_match": True,
            "full_document_scan_complete": True,
            "annexes_scan_complete": True,
            "explicit_rights_basis_present": True,
            "reuse_scope_covers_student_retrieval_excerpt": True,
            "source_exact_document_match": True,
            "pii_gate_pass": True,
            "currentness_gate_pass": True,
            "revocation_gate_pass": True,
            "student_suitability_pass": True,
            "restrictive_notice_detected": False,
            "teacher_only_detected": False,
            "non_disclosure_instruction_detected": False,
            "unlicensed_third_party_content_detected": False,
        },
    }


def strict_policy() -> dict:
    return {
        "rights_bases": {"accepted": ["EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE"]},
        "approve_public_requires_rights_basis_in": ["EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE"],
        "authorized_use": "student_retrieval_excerpt_only",
        "full_pdf_redistribution_allowed": False,
        "answer_generation_allowed": False,
    }


def test_page_projection_preserves_every_scanned_page_and_graphic_proof():
    sha = "a" * 64
    scan = {
        "content_sha256": sha,
        "page_count": 2,
        "pages": [
            {"page_number": 1, "text_sha256": "1" * 64,
             "render_sha256": "2" * 64, "ocr_sha256": "3" * 64,
             "raster_image_count": 1, "vector_drawing_count": 0,
             "annotation_count": 0, "ocr_required": True, "ocr_complete": True},
            {"page_number": 2, "text_sha256": "4" * 64,
             "render_sha256": None, "ocr_sha256": None,
             "raster_image_count": 0, "vector_drawing_count": 0,
             "annotation_count": 0, "ocr_required": False, "ocr_complete": True},
        ],
    }
    pages = project_page_scans(scan)
    assert len(pages) == 2
    assert pages[0]["render_inspected"] is True
    assert pages[0]["graphics_detected"] is True
    assert pages[1]["render_required"] is False
    assert pages[1]["render_sha256"] is None


def test_page_projection_rejects_missing_or_unrendered_graphic_page():
    scan = {"page_count": 2, "pages": [{"page_number": 1, "text_sha256": "a" * 64,
             "render_sha256": None, "ocr_sha256": None,
             "raster_image_count": 1, "vector_drawing_count": 0,
             "annotation_count": 0, "ocr_required": True, "ocr_complete": False}]}
    with pytest.raises(ValueError):
        project_page_scans(scan)


def test_record_without_positive_rights_is_excluded_without_human_claim():
    scan = {
        "content_sha256": SHA, "page_count": 1, "file_size_bytes": 123,
        "exact_bytes_match": True, "full_document_scan_complete": True,
        "annexes_scan_complete": True, "images_and_annexes_checked": True,
        "pages": [{"page_number": 1, "text_sha256": "a" * 64,
                   "render_sha256": None, "ocr_sha256": None,
                   "raster_image_count": 0, "vector_drawing_count": 0,
                   "annotation_count": 0, "ocr_required": False,
                   "ocr_complete": True}],
    }
    reviewer = {"identity": "agent-a", "model_id": "model", "model_version": "digest",
                "prompt_sha256": "a" * 64, "parameters_sha256": "b" * 64,
                "context_sha256": "c" * 64, "observation_sha256": "d" * 64,
                "verdict": "FAIL", "complete": True, "confidence": "HIGH",
                "pages_covered": [1], "evidence_refs": ["page:1:segment:1"]}
    record = build_artifact_record(
        {"content_sha256": SHA, "source_listing_url": "https://example.org/list",
         "page_count": 1}, scan,
        {"source_verification": {"status": "UNVERIFIABLE", "listing_uri": "https://example.org/list",
         "exact_pdf_uri": None, "final_uri": None, "http_status": 403,
         "observed_at_utc": "2026-10-09T20:00:00Z", "etag": None,
         "last_modified": None, "remote_pdf_sha256": None, "terms_uri": None,
         "terms_sha256": None, "terms_observed_at_utc": None,
         "source_last_updated_at_utc": None, "revocation_evidence_uri": None},
         "rights_basis": "NONE", "rights_evidence_uri": None,
         "license_or_terms_excerpt_hash": None, "evidence_pages": [],
         "currentness_status": "UNVERIFIABLE", "revocation_status": "UNVERIFIABLE",
         "reason_codes": ["SOURCE_HTTP_403"]},
        {"reviewer_a": reviewer, "reviewer_b": {**reviewer, "identity": "agent-b",
         "context_sha256": "e" * 64}, "restriction_signals": [],
         "assembly_protocol": "NEXUS_REVIEW_TEXT_ASSEMBLY_V5",
         "text_assembly": [{"page_number": 1,
                            "assembly_protocol": "NEXUS_REVIEW_TEXT_ASSEMBLY_V5"}]},
        strict_policy(), {"inventory_sha256": "1" * 64},
        decided_at_utc="2026-10-09T20:00:00Z",
    )
    assert record["final_disposition"] == "EXCLUDE"
    assert record["rights_basis"] == "NONE"
    assert record["source_receipt_sha256"] is None
    assert record["individual_human_review_claimed"] is False
    assert record["checks"]["explicit_rights_basis_present"] is False
    assert record["reason_codes"]
    assert record["page_scans"][0]["page_number"] == 1
    assert record["assembly_protocol"] == "NEXUS_REVIEW_TEXT_ASSEMBLY_V5"
    assert record["text_assembly"][0]["page_number"] == 1


def test_generated_sheet_is_sorted_and_never_claims_human_pdf_review():
    packet = {"source_release": "v4", "placements": [{"collection": "alpha"}],
              "source_path": "corpus/example.pdf", "source_listing_url": "https://example.org/a",
              "page_count": 1, "source_pii_status": "CLEARED",
              "source_currentness_disposition": "UNVERIFIABLE",
              "automated_review_signals": [], "explicit_student_exclusion_signal": False}
    records = []
    for sha in ("b" * 64, "a" * 64):
        record = {"content_sha256": sha, "rights_basis": "NONE",
                  "reviewer_a": {"verdict": "FAIL"}, "reviewer_b": {"verdict": "FAIL"},
                  "checks": {}, "third_party_status": "UNVERIFIABLE",
                  "final_disposition": "EXCLUDE", "rights_evidence_uri": None,
                  "evidence_pages": [], "reason_codes": ["RIGHTS_UNVERIFIABLE"],
                  "decided_at_utc": "2026-10-09T20:00:00Z",
                  "decision_executor": "nexus-delegated-student-rights-adjudicator-v1",
                  "delegation_id": "nexus-student-public-rights-abenrhouma-20261009-v1"}
        records.append((record, packet, sha))
    result = render_decision_sheet(records).decode("utf-8")
    lines = result.splitlines()
    assert lines[1].startswith("a" * 64 + "\t")
    assert lines[2].startswith("b" * 64 + "\t")
    assert "\thuman_reviewer\t" in lines[0]
    human_index = lines[0].split("\t").index("human_reviewer")
    assert all(line.split("\t")[human_index] == "" for line in lines[1:])
    assert "PENDING" not in result


def test_source_population_matches_exact_v4_v5_union():
    root = Path(__file__).resolve().parents[2]
    refs, counts = source_population_refs(root)
    assert {entry["source_release"] for entry in refs} == {"v4_non_hggsp", "v5_hggsp"}
    assert len(counts) == 315
    assert sum(row["source_placement_count"] for row in counts.values()) == 479
    assert sum(row["source_chunk_count"] for row in counts.values()) == 8268
    assert len({name for row in counts.values() for name in row["collections"]}) == 11


def test_final_counts_derive_from_decisions_including_cftr_exclusion():
    root = Path(__file__).resolve().parents[2]
    _, counts = source_population_refs(root)
    records = [
        {"content_sha256": sha,
         "final_disposition": "EXCLUDE" if sha == CFTR else "APPROVE_PUBLIC"}
        for sha in counts
    ]
    result = final_population(records, counts)
    assert result == {
        "collections": 11, "artifacts": 314, "placements": 478, "chunks": 8242,
        "approve_public": 314, "exclude": 1, "replace_with_new_content": 0,
    }


def test_pack_index_binds_actual_inventory_and_zero_approval_population():
    root = Path(__file__).resolve().parents[2]
    packet_bytes = (root / "docs/reports/go_live/"
                    "student_public_rights_individual_review_packet_20261009.json").read_bytes()
    packet = __import__("json").loads(packet_bytes)
    records = [{"content_sha256": row["content_sha256"],
                "final_disposition": "EXCLUDE"} for row in packet["artifacts"]]
    pins = {label: {"identity": f"agent-{label}", "model_id": "model",
                    "model_version": "digest", "prompt_sha256": "a" * 64,
                    "parameters_sha256": "b" * 64} for label in ("a", "b")}
    index = build_pack_index(
        root, packet_bytes=packet_bytes, records=records,
        artifact_digests={r["content_sha256"]: "c" * 64 for r in records},
        decision_sheet_bytes=b"sheet\n", reviewer_pins=pins,
        policy_bytes=b"policy", mandate_bytes=b"mandate", schema_bytes=b"schema",
    )
    assert len(index["artifacts"]) == 315
    assert index["final_population"] == {
        "collections": 0, "artifacts": 0, "placements": 0, "chunks": 0,
        "approve_public": 0, "exclude": 315, "replace_with_new_content": 0,
    }
    assert index["inventory_sha256"] != index["mandate_sha256"]


def test_draft_mandate_cannot_materialize_final_sheet(tmp_path: Path):
    root = Path(__file__).resolve().parents[2]
    paths = (
        "docs/reports/go_live/student_public_rights_individual_review_packet_20261009.json",
        "governance/student_public_rights/delegated_review_policy_v1.yml",
        "governance/student_public_rights/delegation_abenrhouma_20261009.yml",
        "governance/student_public_rights/schemas/automated_artifact_review_v1.schema.json",
        "scripts/go_live/student_rights_pdf_scan.py",
    )
    for relative in paths:
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((root / relative).read_bytes())
    mandate = tmp_path / paths[2]
    mandate.write_text(mandate.read_text().replace(
        "status: SEALED_PENDING_FINAL_APPROVAL", "status: DRAFT_UNSEALED", 1,
    ))
    with pytest.raises(ValueError, match="POLICY_OR_MANDATE_NOT_SEALED"):
        materialize_pack(
            tmp_path, scan_checkpoints=tmp_path, source_checkpoints=tmp_path,
            review_checkpoints=tmp_path, decided_at_utc="2026-10-09T21:00:00Z",
        )


def test_complete_positive_proof_can_approve():
    result = adjudicate_artifact(accepted_evidence(), strict_policy())
    assert result["final_disposition"] == "APPROVE_PUBLIC"
    assert result["deterministic_policy_verdict"] == "PASS"
    assert result["reason_codes"] == []


@pytest.mark.parametrize(
    "key",
    [
        "exact_bytes_match", "full_document_scan_complete", "annexes_scan_complete",
        "explicit_rights_basis_present", "reuse_scope_covers_student_retrieval_excerpt",
        "source_exact_document_match", "pii_gate_pass", "currentness_gate_pass",
        "revocation_gate_pass", "student_suitability_pass",
    ],
)
def test_any_missing_positive_predicate_excludes(key: str):
    evidence = accepted_evidence()
    evidence["checks"][key] = False
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert key.upper() in result["reason_codes"]


@pytest.mark.parametrize(
    "key",
    [
        "restrictive_notice_detected", "teacher_only_detected",
        "non_disclosure_instruction_detected", "unlicensed_third_party_content_detected",
    ],
)
def test_any_restriction_excludes(key: str):
    evidence = accepted_evidence()
    evidence["checks"][key] = True
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert key.upper() in result["reason_codes"]


@pytest.mark.parametrize("verdict", ["FAIL", "UNCERTAIN", None])
def test_both_independent_reviewers_must_pass(verdict: str | None):
    evidence = accepted_evidence()
    evidence["reviewer_b"]["verdict"] = verdict
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert "REVIEWER_B_NOT_PASS" in result["reason_codes"]


def test_same_reviewer_or_context_cannot_approve():
    evidence = accepted_evidence()
    evidence["reviewer_b"] = copy.deepcopy(evidence["reviewer_a"])
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert "REVIEWS_NOT_INDEPENDENT" in result["reason_codes"]


@pytest.mark.parametrize("change", ["complete", "confidence", "pages_covered"])
def test_incomplete_or_low_confidence_review_excludes(change: str):
    evidence = accepted_evidence()
    evidence["reviewer_a"][change] = {
        "complete": False, "confidence": "LOW", "pages_covered": [1]
    }[change]
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert "REVIEWER_A_EVIDENCE_INCOMPLETE" in result["reason_codes"]


def test_second_candidate_classification_must_match():
    evidence = accepted_evidence()
    evidence["candidate_replays"][1]["reviewer_b_observation_sha256"] = "3" * 64
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert "CANDIDATE_REPLAY_DIVERGENCE" in result["reason_codes"]


def test_second_candidate_classification_requires_distinct_context_and_receipts():
    evidence = accepted_evidence()
    evidence["candidate_replays"][1]["reviewer_a_context_sha256"] = (
        evidence["candidate_replays"][0]["reviewer_a_context_sha256"]
    )
    evidence["candidate_replays"][1]["reviewer_a_evidence_refs"] = (
        evidence["candidate_replays"][0]["reviewer_a_evidence_refs"]
    )
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert "CANDIDATE_REPLAY_DIVERGENCE" in result["reason_codes"]


def test_missing_source_terms_excludes():
    evidence = accepted_evidence()
    evidence["source_verification"]["terms_sha256"] = None
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert "SOURCE_TERMS_OR_REVOCATION_NOT_PROVEN" in result["reason_codes"]


@pytest.mark.parametrize("key", [
    "third_party_status", "pii_status", "currentness_status",
    "revocation_status", "student_suitability",
])
def test_missing_explicit_safety_status_excludes(key: str):
    evidence = accepted_evidence()
    evidence[key] = "UNVERIFIABLE"
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"


def test_missing_source_receipt_excludes():
    evidence = accepted_evidence()
    evidence["source_receipt_sha256"] = None
    assert adjudicate_artifact(evidence, strict_policy())["final_disposition"] == "EXCLUDE"


def test_malformed_policy_rights_list_fails_closed_without_exception():
    policy = strict_policy()
    policy["rights_bases"]["accepted"] = [{"unexpected": "mapping"}]
    result = adjudicate_artifact(accepted_evidence(), policy)
    assert result["final_disposition"] == "EXCLUDE"
    assert "POLICY_RIGHTS_BASES_INVALID" in result["reason_codes"]


@pytest.mark.parametrize("basis", ["officiel_public", "OTHER_EXPLICITLY_VERIFIED_BASIS", None])
def test_legacy_or_unenumerated_rights_basis_cannot_approve(basis: str | None):
    evidence = accepted_evidence()
    evidence["rights_basis"] = basis
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert "RIGHTS_BASIS_NOT_ALLOWED" in result["reason_codes"]


def test_listing_url_without_exact_pdf_identity_cannot_approve():
    evidence = accepted_evidence()
    evidence["source_verification"]["remote_pdf_sha256"] = "0" * 64
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert "SOURCE_IDENTITY_NOT_PROVEN" in result["reason_codes"]


def test_cftr_page_three_is_excluded_even_if_other_checks_pass():
    evidence = accepted_evidence()
    evidence["artifact_id"] = CFTR
    evidence["content_sha256"] = CFTR
    evidence["source_verification"]["remote_pdf_sha256"] = CFTR
    result = adjudicate_artifact(evidence, strict_policy())
    assert result["final_disposition"] == "EXCLUDE"
    assert result["student_suitability"] == "FAIL"
    schema = __import__("json").loads((
        Path(__file__).resolve().parents[2]
        / "governance/student_public_rights/schemas/automated_artifact_review_v1.schema.json"
    ).read_text())
    assert set(result) <= set(schema["properties"])
    assert result["reason_codes"] == ["TEACHER_NON_DISCLOSURE_INSTRUCTION"]
    assert result["evidence_pages"] == [3]


def test_no_policy_can_enable_full_pdf_or_answer_generation():
    policy = strict_policy()
    policy["full_pdf_redistribution_allowed"] = True
    result = adjudicate_artifact(accepted_evidence(), policy)
    assert result["final_disposition"] == "EXCLUDE"
    assert "POLICY_SCOPE_INVALID" in result["reason_codes"]
