"""Sabotages du vérificateur indépendant de la délégation étudiante."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from check_delegated_student_rights_gate import (  # noqa: E402
    DEFAULTS,
    _git_source_binding,
    _reconstruct_review_requests,
    _verify_approval_source_proof,
    _verify_review_receipts,
    _rescan_pdf,
    _source_population,
    canonical_json_bytes,
    check_artifact,
    check_gate,
    render_decision_sheet,
)

CFTR = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
SHA = "a" * 64
H = lambda c: c * 64  # noqa: E731
G = lambda c: c * 40  # noqa: E731
UTC = "2026-10-09T20:00:00Z"


def _record(sha: str = SHA) -> dict:
    record = {
        "record_kind": "NEXUS_AUTOMATED_ARTIFACT_REVIEW_V1",
        "artifact_id": sha,
        "content_sha256": sha,
        "source_uri": "https://example.org/exact.pdf",
        "page_count": 2,
        "byte_size": 100,
        "scan_complete": True,
        "images_and_annexes_checked": True,
        "assembly_protocol": "NEXUS_REVIEW_TEXT_ASSEMBLY_V3",
        "text_assembly": [
            {
                "page_number": n,
                "assembly_protocol": "NEXUS_REVIEW_TEXT_ASSEMBLY_V3",
                "extracted_text_sha256": H("1"), "ocr_full_sha256": H("2"),
                "ocr_residual_sha256": H("3"),
                "ocr_exact_duplicate_lines_removed": 0,
                "segment_count": 1, "visual_segment_indices": [1],
                **({"xmp_full_sha256": H("4"), "xmp_projection_sha256": H("5"),
                    "xmp_unique_value_count": 0, "xmp_duplicate_value_count": 0,
                    "xmp_embedded_image_count": 0, "xmp_embedded_image_sha256": []}
                   if n == 1 else {}),
            }
            for n in (1, 2)
        ],
        "page_scans": [
            {"page_number": n, "text_sha256": H("1"), "render_sha256": H("2"),
             "ocr_sha256": H("3"), "graphics_detected": True, "render_required": True,
             "render_inspected": True, "annex_page": n == 2, "scan_complete": True}
            for n in (1, 2)
        ],
        "source_verification": {
            "status": "VERIFIED", "listing_uri": "https://example.org/list",
            "exact_pdf_uri": "https://example.org/exact.pdf",
            "final_uri": "https://example.org/exact.pdf", "http_status": 200,
            "observed_at_utc": UTC, "etag": None, "last_modified": None,
            "remote_pdf_sha256": sha, "terms_uri": "https://example.org/terms",
            "terms_sha256": H("4"), "terms_observed_at_utc": UTC,
            "source_last_updated_at_utc": UTC,
            "revocation_evidence_uri": "https://example.org/terms",
        },
        "source_receipt_sha256": None,
        "rights_basis": "EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE",
        "rights_evidence_uri": "https://example.org/terms",
        "license_or_terms_excerpt_hash": H("5"), "evidence_pages": [1],
        "third_party_status": "CLEARED_WITH_EVIDENCE", "pii_status": "PASS",
        "currentness_status": "PASS", "revocation_status": "PASS",
        "student_suitability": "PASS", "restriction_signals": [],
        "checks": {
            "exact_bytes_match": True, "full_document_scan_complete": True,
            "annexes_scan_complete": True, "explicit_rights_basis_present": True,
            "reuse_scope_covers_student_retrieval_excerpt": True,
            "source_exact_document_match": True, "pii_gate_pass": True,
            "currentness_gate_pass": True, "revocation_gate_pass": True,
            "student_suitability_pass": True, "restrictive_notice_detected": False,
            "teacher_only_detected": False, "non_disclosure_instruction_detected": False,
            "unlicensed_third_party_content_detected": False,
        },
        "reviewer_a": {
            "identity": "rights-agent-a@1", "model_id": "model-a",
            "model_version": "model-a@1", "prompt_sha256": H("6"),
            "parameters_sha256": H("7"), "verdict": "PASS", "complete": True,
            "confidence": "HIGH", "pages_covered": [1, 2],
            "observation_sha256": H("8"), "context_sha256": H("c"),
            "evidence_refs": [f"sha256:{H('3')}"],
        },
        "reviewer_b": {
            "identity": "suitability-agent-b@1", "model_id": "model-b",
            "model_version": "model-b@1", "prompt_sha256": H("9"),
            "parameters_sha256": H("a"), "verdict": "PASS", "complete": True,
            "confidence": "HIGH", "pages_covered": [1, 2],
            "observation_sha256": H("b"), "context_sha256": H("d"),
            "evidence_refs": [f"sha256:{H('4')}"],
        },
        "candidate_replays": [
            {"run_index": n, "run_nonce": n - 1,
             "reviewer_a_observation_sha256": H("8"),
             "reviewer_b_observation_sha256": H("b"),
             "reviewer_a_context_sha256": H("c") if n == 1 else H("e"),
             "reviewer_b_context_sha256": H("d") if n == 1 else H("f"),
             "reviewer_a_evidence_refs": [f"sha256:{H('3' if n == 1 else '5')}"],
             "reviewer_b_evidence_refs": [f"sha256:{H('4' if n == 1 else '6')}"],
             "candidate_verdict": "PASS"}
            for n in (1, 2)
        ],
        "deterministic_rules_passed": ["exact_bytes_match"],
        "deterministic_policy_verdict": "PASS", "final_disposition": "APPROVE_PUBLIC",
        "reason_codes": [],
        "decision_executor": "nexus-delegated-student-rights-adjudicator-v1",
        "delegation_id": "nexus-student-public-rights-abenrhouma-20261009-v1",
        "individual_human_review_claimed": False,
        "bindings": {"inventory_sha256": H("c"), "policy_sha256": H("d"),
                     "mandate_sha256": H("e"), "schema_sha256": H("f"),
                     "engine_code_sha256": H("0"), "scanner_code_sha256": H("1"),
                     "source_checker_code_sha256": H("2"),
                     "reviewer_code_sha256": H("3"),
                     "pdf_sha256": sha},
        "decided_at_utc": UTC,
    }
    record["pdf_scan_evidence"] = {
        "scanner_kind": "NEXUS-STUDENT-RIGHTS-PDF-SCAN-V1",
        "renderer_version": "test-renderer-1", "content_sha256": sha,
        "exact_bytes_match": True, "file_size_bytes": 100,
        "page_count": 2, "expected_page_count": 2,
        "full_document_scan_complete": True, "annexes_scan_complete": True,
        "images_and_annexes_checked": True, "embedded_file_count": 0,
        "metadata_sha256": H("e"),
        "pages": [
            {"page_number": n, "text_sha256": H("1"), "text_character_count": 50,
             "raster_image_count": 1, "vector_drawing_count": 0, "annotation_count": 0,
             "annotations_sha256": H("c"), "link_count": 0, "links_sha256": H("d"),
             "render_sha256": H("2"), "render_scale": 1.0,
             "ocr_required": True, "ocr_complete": True, "ocr_sha256": H("3"),
             "annex_page": n == 2}
            for n in (1, 2)
        ],
    }
    return record


def _receipt_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _packet_artifact(sha: str = SHA) -> dict:
    return {"content_sha256": sha, "page_count": 2,
            "source_release": "v4", "source_path": "pdf/a.pdf",
            "source_listing_url": "https://example.org/list",
            "placements": [{"collection": "rag_nexus_test", "source_internal_placement_id": H("1")}],
            "source_pii_status": "CLEARED", "source_currentness_disposition": "CURRENT"}


def _policy() -> dict:
    return {"authorized_use": "student_retrieval_excerpt_only",
            "full_pdf_redistribution_allowed": False, "answer_generation_allowed": False,
            "rights_bases": {"accepted": ["EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE"]},
            "delegating_authority": "abenrhouma",
            "status": "SEALED_PENDING_FINAL_APPROVAL"}


def _mandate() -> dict:
    return {"delegating_authority": "abenrhouma", "decision_executor":
            "nexus-delegated-student-rights-adjudicator-v1", "status": "SEALED_PENDING_FINAL_APPROVAL",
            "effective_authority": False,
            "delegation_id": "nexus-student-public-rights-abenrhouma-20261009-v1",
            "authorized_use": "student_retrieval_excerpt_only",
            "full_pdf_redistribution_allowed": False, "answer_generation_allowed": False,
            "public_ingest_endpoint_allowed": False, "public_writer_allowed": False}


def _errors(record: dict, packet: dict | None = None) -> list[str]:
    return check_artifact(record, packet or _packet_artifact(record["content_sha256"]),
                          _policy(), _mandate(), record["bindings"])


def test_valid_complete_record_has_no_errors():
    assert _errors(_record()) == []


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (lambda r: r.update(final_disposition="PENDING"), "DISPOSITION_INVALID"),
        (lambda r: r.update(rights_basis="NONE"), "APPROVAL_RIGHTS_BASIS"),
        (lambda r: r.update(evidence_pages=[]), "APPROVAL_EVIDENCE_PAGES"),
        (lambda r: r.update(content_sha256=H("f")), "CONTENT_IDENTITY"),
        (lambda r: r["reviewer_a"].update(identity=""), "REVIEWER_A_INCOMPLETE"),
        (lambda r: r["source_verification"].update(final_uri="https://other.org/different.pdf"),
         "APPROVAL_SOURCE_MISMATCH"),
        (lambda r: r.update(rights_basis="officiel_public"), "APPROVAL_RIGHTS_BASIS"),
        (lambda r: r["page_scans"][1].update(render_inspected=False), "FULL_SCAN_INCOMPLETE"),
        (lambda r: r["reviewer_b"].update(pages_covered=[1]), "REVIEWER_B_INCOMPLETE"),
        (lambda r: r.update(individual_human_review_claimed=True), "FALSE_HUMAN_REVIEW"),
    ],
)
def test_record_sabotage_is_rejected(mutation, code):
    record = _record()
    mutation(record)
    assert code in _errors(record)


def test_cftr_cannot_be_approved():
    record = _record(CFTR)
    assert "CFTR_NOT_EXCLUDED" in _errors(record)


def test_cftr_exclusion_requires_page_three_and_reason():
    record = _record(CFTR)
    record.update(page_count=3, final_disposition="EXCLUDE", student_suitability="FAIL",
                  deterministic_policy_verdict="FAIL",
                  reason_codes=["TEACHER_NON_DISCLOSURE_INSTRUCTION"],
                  evidence_pages=[3])
    record["page_scans"].append({**record["page_scans"][1], "page_number": 3})
    record["pdf_scan_evidence"].update(page_count=3, expected_page_count=3)
    record["pdf_scan_evidence"]["pages"].append(
        {**record["pdf_scan_evidence"]["pages"][1], "page_number": 3}
    )
    for reviewer in (record["reviewer_a"], record["reviewer_b"]):
        reviewer["pages_covered"] = [1, 2, 3]
    packet = _packet_artifact(CFTR)
    packet["page_count"] = 3
    assert _errors(record, packet) == []


def test_canonical_json_stable():
    assert canonical_json_bytes({"é": 1, "a": 2}) == b'{"a":2,"\xc3\xa9":1}\n'


def test_sheet_render_is_deterministic_and_never_claims_human_review():
    record = _record()
    content = render_decision_sheet([(record, _packet_artifact(), H("0"))])
    rows = list(csv.DictReader(content.decode("utf-8").splitlines(), delimiter="\t"))
    assert rows[0]["human_reviewer"] == ""
    assert rows[0]["student_public_disposition"] == "APPROVE_PUBLIC"
    assert rows[0]["decision_executor"] == record["decision_executor"]


def test_gate_fails_closed_without_315_records(tmp_path: Path):
    (tmp_path / "docs/reports/go_live/student_rights_evidence").mkdir(parents=True)
    result = check_gate(tmp_path)
    assert result["DELEGATED_RIGHTS_ADJUDICATION_PASS"] is False
    assert "INDEX_MISSING" in result["errors"]


def test_sheet_manual_tamper_detected_via_digest(tmp_path: Path):
    record = _record()
    original = render_decision_sheet([(record, _packet_artifact(), H("0"))])
    tampered = original.replace(b"APPROVE_PUBLIC", b"EXCLUDE")
    assert hashlib.sha256(original).hexdigest() != hashlib.sha256(tampered).hexdigest()


def test_pdf_scan_projection_must_match_structural_evidence():
    record = _record()
    record["pdf_scan_evidence"]["pages"][1]["text_sha256"] = H("0")
    assert "FULL_SCAN_INCOMPLETE" in _errors(record)


def test_pdf_rescan_rejects_fabricated_evidence(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    document = fitz.open()
    document.new_page().insert_text((50, 50), "Document témoin")
    data = document.tobytes()
    document.close()
    sha = hashlib.sha256(data).hexdigest()
    path = tmp_path / "pdf" / "document.pdf"
    path.parent.mkdir()
    path.write_bytes(data)
    packet = {"content_sha256": sha, "page_count": 1, "source_path": "pdf/document.pdf"}
    record = _record(sha)
    assert _rescan_pdf(record, packet, tmp_path) == ["PDF_RESCAN_MISMATCH"]


def test_source_receipt_and_matching_live_bytes_still_cannot_forge_currentness(
    tmp_path: Path,
):
    pdf_bytes = b"%PDF-1.4\nexact\n%%EOF\n"
    legal_bytes = (b"<html>documents proposes en telechargement licence etalab-2.0 "
                   b"sont exclus les contenus de tiers</html>")
    license_bytes = (b"<html>licence ouverte 2.0 reproduire extraire "
                     b"mentionner la paternite date de la derniere mise a jour</html>")
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    checker_path = tmp_path / "scripts/go_live/student_rights_source_check.py"
    checker_path.parent.mkdir(parents=True)
    checker_path.write_text("# bound source checker\n")
    listing = "https://eduscol.education.gouv.fr/ressources"
    observed = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    pdf_uri = "https://eduscol.education.gouv.fr/exact.pdf"
    legal_uri = "https://eduscol.education.gouv.fr/4656/mentions-legales"
    license_uri = "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0"
    record = _record(sha)
    record["source_uri"] = pdf_uri
    record["source_verification"]["terms_sha256"] = hashlib.sha256(legal_bytes).hexdigest()
    record["source_verification"]["terms_observed_at_utc"] = observed
    record["rights_evidence_uri"] = legal_uri
    record["license_or_terms_excerpt_hash"] = hashlib.sha256(legal_bytes).hexdigest()
    receipt = {
        "kind": "NEXUS-STUDENT-SOURCE-RIGHTS-RECEIPT-V1",
        "artifact_content_sha256": sha, "listing_uri": listing,
        "pdf": {"final_uri": pdf_uri, "http_status": 200, "observed_at_utc": observed,
                "etag": None, "last_modified": None, "content_sha256": sha},
        "legal_terms": {"final_uri": legal_uri, "http_status": 200,
                        "observed_at_utc": observed, "etag": None, "last_modified": None,
                        "body_sha256": hashlib.sha256(legal_bytes).hexdigest()},
        "license": {"final_uri": license_uri, "http_status": 200,
                    "observed_at_utc": observed, "etag": None, "last_modified": None,
                    "body_sha256": hashlib.sha256(license_bytes).hexdigest()},
        "rights_scope": "EDUSCOL_DOWNLOADS_EXCLUDING_THIRD_PARTY",
        "source_checker_code_sha256": hashlib.sha256(checker_path.read_bytes()).hexdigest(),
        "transport_kind": "URLLIB_HTTPS_GET_NO_REDIRECT_V1",
    }
    evidence_root = tmp_path / "docs/reports/go_live/student_rights_evidence"
    raw = canonical_json_bytes(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    path = evidence_root / "source_receipts" / digest[:2] / f"{digest}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    record["source_receipt_sha256"] = digest
    content = {pdf_uri: pdf_bytes, legal_uri: legal_bytes, license_uri: license_bytes}
    called = []

    def fetch(uri: str, _limit: int) -> bytes:
        called.append(uri)
        return content[uri]

    assert _verify_approval_source_proof(record, {"content_sha256": sha,
        "source_listing_url": listing}, evidence_root, fetch=fetch) == [
            "APPROVAL_SOURCE_PROOF_UNVERIFIABLE"
        ]
    assert called == [pdf_uri, legal_uri, license_uri]
    called.clear()
    receipt["transport_kind"] = "INJECTED_TEST_TRANSPORT"
    raw = canonical_json_bytes(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    forged_path = evidence_root / "source_receipts" / digest[:2] / f"{digest}.json"
    forged_path.parent.mkdir(parents=True)
    forged_path.write_bytes(raw)
    record["source_receipt_sha256"] = digest
    assert _verify_approval_source_proof(record, {"content_sha256": sha,
        "source_listing_url": listing}, evidence_root, fetch=fetch) == [
            "APPROVAL_SOURCE_PROOF_UNVERIFIABLE"
        ]
    assert called == []


def test_real_pdf_request_hashes_reconstruct_and_resealed_receipt_tamper_fails(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    from student_rights_reviewers import review_document

    pdf = tmp_path / "pdf" / "exact.pdf"
    pdf.parent.mkdir()
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 50), "Document témoin avec une notice explicite.")
    page.draw_rect(fitz.Rect(50, 70, 100, 100))
    pdf.write_bytes(document.tobytes())
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()

    def transport(_model_id, _system_prompt, payload, _parameters, _image_png):
        observation = {
            "page_number": payload["page_number"],
            "segment_index": payload["segment_index"],
            "segment_count": payload["segment_count"],
            "verdict": "PASS", "confidence": "HIGH", "reason_codes": [],
            "evidence_pages": [payload["page_number"]],
            "visual_examined": _image_png is not None,
        }
        if payload["review_domain"] == "reviewer_a":
            observation["positive_rights_notice_present"] = True
        return observation

    transport.supports_vision = True
    receipt_dir = tmp_path / "evidence" / "receipts"
    reviewed = review_document(
        pdf, sha, transport=transport, model_id="qwen3-vl:2b",
        model_version="sha256:test", parameters={"temperature": 0, "seed": 17},
        rights_evidence_positive=True, vision_enabled=True,
        receipt_dir=receipt_dir,
    )
    record = {
        "content_sha256": sha, "page_count": 1,
        "assembly_protocol": reviewed["assembly_protocol"],
        "text_assembly": reviewed["text_assembly"],
        "page_scans": [{"page_number": 1, "graphics_detected": True}],
        "reviewer_a": reviewed["reviewer_a"], "reviewer_b": reviewed["reviewer_b"],
    }
    packet = {"source_path": "pdf/exact.pdf", "content_sha256": sha, "page_count": 1}
    proofs, errors = _reconstruct_review_requests(record, packet, tmp_path)
    assert errors == []
    assert _verify_review_receipts(record, tmp_path / "evidence", proofs) == []
    second = review_document(
        pdf, sha, transport=transport, model_id="qwen3-vl:2b",
        model_version="sha256:test", parameters={"temperature": 0, "seed": 17},
        rights_evidence_positive=True, vision_enabled=True,
        receipt_dir=receipt_dir, run_nonce=1,
    )
    replay_record = {**record, "reviewer_a": second["reviewer_a"],
                     "reviewer_b": second["reviewer_b"]}
    assert _verify_review_receipts(replay_record, tmp_path / "evidence", proofs,
                                   run_nonce=1) == []
    assert second["reviewer_a"]["context_sha256"] != reviewed["reviewer_a"]["context_sha256"]
    context = record["reviewer_a"]["context_sha256"]
    record["reviewer_a"]["context_sha256"] = H("f")
    assert "REVIEWER_A_RECEIPT_CONTEXT_MISMATCH" in _verify_review_receipts(
        record, tmp_path / "evidence", proofs
    )
    record["reviewer_a"]["context_sha256"] = context

    ref = record["reviewer_a"]["evidence_refs"][0]
    digest = ref.split(":", 1)[1]
    old_path = receipt_dir / digest[:2] / f"{digest}.json"
    forged = json.loads(old_path.read_bytes())
    forged["request_sha256"] = H("f")
    raw = _receipt_bytes(forged)
    forged_sha = hashlib.sha256(raw).hexdigest()
    forged_path = receipt_dir / forged_sha[:2] / f"{forged_sha}.json"
    forged_path.parent.mkdir()
    forged_path.write_bytes(raw)
    record["reviewer_a"]["evidence_refs"][0] = f"sha256:{forged_sha}"
    assert "REVIEWER_A_RECEIPT_REQUEST_MISMATCH" in _verify_review_receipts(
        record, tmp_path / "evidence", proofs
    )


def test_v3_xmp_image_and_residual_ocr_requests_reconstruct(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import base64

    fitz = pytest.importorskip("fitz")
    import student_rights_pdf_scan as scanner
    import student_rights_reviewers as reviewers

    image = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 32, 32), False)
    for y in range(32):
        for x in range(32):
            image.set_pixel(x, y, (
                (x * 73 + y * 13) % 256,
                (x * 29 + y * 17) % 256,
                (x * 7 + y * 97) % 256,
            ))
    image_bytes = image.tobytes("png")
    assert len(base64.b64encode(image_bytes)) > 400
    pdf = tmp_path / "pdf" / "with-xmp.pdf"
    pdf.parent.mkdir()
    document = fitz.open()
    page = document.new_page()
    page.insert_text((50, 50), "Ligne extraite.")
    page.draw_rect(fitz.Rect(50, 70, 100, 100))
    document.set_xml_metadata(
        '<x:xmpmeta xmlns:x="adobe:ns:meta/" xmlns:t="urn:test">'
        '<t:title>Notice de droits</t:title><t:title>Notice de droits</t:title>'
        f'<t:image>{base64.b64encode(image_bytes).decode("ascii")}</t:image>'
        '</x:xmpmeta>'
    )
    pdf.write_bytes(document.tobytes())
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    monkeypatch.setattr(scanner, "_ocr_text", lambda _png: "Ligne extraite.\nLigne nouvelle.\n")
    monkeypatch.setattr(reviewers, "_ocr_text", lambda _png: "Ligne extraite.\nLigne nouvelle.\n")

    sent_segments = []

    def transport(_model_id, _system_prompt, payload, _parameters, image_png):
        sent_segments.append((payload.copy(), image_png is not None))
        return {
            "page_number": payload["page_number"],
            "segment_index": payload["segment_index"],
            "segment_count": payload["segment_count"],
            "verdict": "PASS", "confidence": "HIGH", "reason_codes": [],
            "evidence_pages": [payload["page_number"]],
            "visual_examined": image_png is not None,
            **({"positive_rights_notice_present": True}
               if payload["review_domain"] == "reviewer_a" else {}),
        }

    transport.supports_vision = True
    reviewed = reviewers.review_document(
        pdf, sha, transport=transport, model_id="granite3.2-vision:2b",
        model_version="sha256:test", parameters={"temperature": 0, "seed": 17},
        rights_evidence_positive=True, vision_enabled=True,
        receipt_dir=tmp_path / "evidence" / "receipts",
    )
    facts = reviewed["text_assembly"][0]
    assert facts["assembly_protocol"] == "NEXUS_REVIEW_TEXT_ASSEMBLY_V3"
    assert facts["xmp_duplicate_value_count"] == 1
    assert facts["xmp_embedded_image_count"] == 1
    assert facts["ocr_exact_duplicate_lines_removed"] == 1
    assert facts["segment_count"] >= 3
    assert facts["visual_segment_indices"] == [1, facts["segment_count"]]
    assert sent_segments[0][0]["page_text_segment"].startswith("[PDF_PAGE_RENDER_SHA256:")
    assert len(sent_segments[0][0]["page_text_segment"]) < 100
    assert sent_segments[0][1] is True
    assert sent_segments[1][1] is False
    record = {
        "content_sha256": sha, "page_count": 1,
        "assembly_protocol": reviewed["assembly_protocol"],
        "text_assembly": reviewed["text_assembly"],
        "page_scans": [{"page_number": 1, "graphics_detected": True}],
        "reviewer_a": reviewed["reviewer_a"], "reviewer_b": reviewed["reviewer_b"],
    }
    packet = {"source_path": "pdf/with-xmp.pdf", "content_sha256": sha, "page_count": 1}
    proofs, errors = _reconstruct_review_requests(record, packet, tmp_path)
    assert errors == []
    assert _verify_review_receipts(record, tmp_path / "evidence", proofs) == []
    text_ref = record["reviewer_a"]["evidence_refs"][1]
    text_digest = text_ref.split(":", 1)[1]
    text_receipt = json.loads((tmp_path / "evidence" / "receipts"
                               / text_digest[:2] / f"{text_digest}.json").read_bytes())
    assert text_receipt["image_sha256"] is None
    text_receipt["observation"]["visual_examined"] = True
    text_receipt["observation_sha256"] = hashlib.sha256(
        _receipt_bytes(text_receipt["observation"])
    ).hexdigest()
    forged_text = _receipt_bytes(text_receipt)
    forged_text_digest = hashlib.sha256(forged_text).hexdigest()
    forged_text_path = (tmp_path / "evidence" / "receipts" / forged_text_digest[:2]
                        / f"{forged_text_digest}.json")
    forged_text_path.parent.mkdir(parents=True, exist_ok=True)
    forged_text_path.write_bytes(forged_text)
    record["reviewer_a"]["evidence_refs"][1] = f"sha256:{forged_text_digest}"
    assert "REVIEWER_A_RECEIPT_NONVISUAL_CLAIM" in _verify_review_receipts(
        record, tmp_path / "evidence", proofs
    )
    record["reviewer_a"]["evidence_refs"][1] = text_ref
    visual_ref = record["reviewer_a"]["evidence_refs"][-1]
    visual_digest = visual_ref.split(":", 1)[1]
    visual_receipt = json.loads((tmp_path / "evidence" / "receipts"
                                 / visual_digest[:2] / f"{visual_digest}.json").read_bytes())
    assert visual_receipt["image_sha256"] == facts["xmp_embedded_image_sha256"][0]
    visual_receipt["observation"]["visual_examined"] = False
    visual_receipt["observation_sha256"] = hashlib.sha256(
        _receipt_bytes(visual_receipt["observation"])
    ).hexdigest()
    forged = _receipt_bytes(visual_receipt)
    forged_digest = hashlib.sha256(forged).hexdigest()
    forged_path = (tmp_path / "evidence" / "receipts" / forged_digest[:2]
                   / f"{forged_digest}.json")
    forged_path.parent.mkdir(parents=True, exist_ok=True)
    forged_path.write_bytes(forged)
    record["reviewer_a"]["evidence_refs"][-1] = f"sha256:{forged_digest}"
    assert "REVIEWER_A_RECEIPT_PASS_UNSUPPORTED" in _verify_review_receipts(
        record, tmp_path / "evidence", proofs
    )
    record["text_assembly"][0]["ocr_residual_sha256"] = H("f")
    _, errors = _reconstruct_review_requests(record, packet, tmp_path)
    assert errors == ["REVIEW_TEXT_ASSEMBLY_MISMATCH"]


def test_gate_requires_source_mirror_even_for_otherwise_sealed_pack(sealed_pack):
    root, _ = sealed_pack
    result = check_gate(root, expected_count=2)
    assert result["errors"] == ["SOURCE_MIRROR_ROOT_REQUIRED"]


def _source_refs(root: Path) -> list[dict]:
    base = root / "services/rag-pedago/data/releases/prerentree_2026_2027"
    result = []
    for release, directory, expected_subjects in (
        ("v4_non_hggsp", "profile_gate_v4", 9),
        ("v5_hggsp", "profile_gate_hggsp_v5", 2),
    ):
        profile = next((base / directory).glob("release-*/profile_gate"))
        artifacts = profile / "artifacts.release.json"
        subjects = sorted((profile / "subjects").glob("*.release.json"))
        if release == "v4_non_hggsp":
            subjects = [p for p in subjects if "hggsp" not in p.name]
        assert len(subjects) == expected_subjects
        result.append({
            "source_release": release,
            "artifacts_path": str(artifacts.relative_to(root)),
            "artifacts_sha256": hashlib.sha256(artifacts.read_bytes()).hexdigest(),
            "subjects": [{"path": str(p.relative_to(root)),
                          "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                         for p in subjects],
        })
    return result


def test_source_manifests_recompute_315_from_9_v4_plus_2_v5_subjects():
    root = Path(__file__).resolve().parents[2]
    packet = json.loads((root / "docs/reports/go_live/"
                         "student_public_rights_individual_review_packet_20261009.json").read_text())
    inventory = {p["content_sha256"]: p for p in packet["artifacts"]}
    source_refs = _source_refs(root)
    index = {"source_population": source_refs, "artifacts": {}}
    counts, collections, errors = _source_population(root, index, inventory)
    assert len(counts) == 315
    assert len(collections) == 11
    assert sum(c["source_placement_count"] for c in counts.values()) == 479
    assert sum(c["source_chunk_count"] for c in counts.values()) == 8268
    assert all(len(c["source_chunks_sha256"]) == 64 for c in counts.values())
    assert errors == []


def test_source_manifests_refuse_hggsp_v4_reuse():
    root = Path(__file__).resolve().parents[2]
    packet = json.loads((root / "docs/reports/go_live/"
                         "student_public_rights_individual_review_packet_20261009.json").read_text())
    inventory = {p["content_sha256"]: p for p in packet["artifacts"]}
    refs = _source_refs(root)
    hggsp_v4 = next((root / refs[0]["artifacts_path"]).parent.glob(
        "subjects/rag_nexus_hggsp_premiere_specialite.release.json"
    ))
    refs[0]["subjects"][0] = {
        "path": str(hggsp_v4.relative_to(root)),
        "sha256": hashlib.sha256(hggsp_v4.read_bytes()).hexdigest(),
    }
    _, _, errors = _source_population(root, {"source_population": refs, "artifacts": {}}, inventory)
    assert any(code.startswith("SOURCE_COLLECTION_SCOPE:") for code in errors)


def test_source_projection_cannot_forge_legacy_counts():
    root = Path(__file__).resolve().parents[2]
    packet = json.loads((root / "docs/reports/go_live/"
                         "student_public_rights_individual_review_packet_20261009.json").read_text())
    inventory = {p["content_sha256"]: p for p in packet["artifacts"]}
    refs = _source_refs(root)
    counts, _, errors = _source_population(root, {"source_population": refs}, inventory)
    assert errors == []
    projection = {sha: {"source_placement_count": c["source_placement_count"],
                        "source_chunk_count": c["source_chunk_count"]}
                  for sha, c in counts.items()}
    projection[CFTR]["source_chunk_count"] += 26
    _, _, errors = _source_population(root, {"source_population": refs, "artifacts": projection}, inventory)
    assert f"SOURCE_PROJECTED_COUNTS:{CFTR[:12]}" in errors


@pytest.fixture
def sealed_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict]:
    """Deux vrais enregistrements structurés dans un pack synthétique scellé."""
    source_root = Path(__file__).resolve().parents[2]
    paths = {key: tmp_path / value for key, value in DEFAULTS.items()}
    for path in paths.values():
        path.parent.mkdir(parents=True, exist_ok=True)
    paths["schema"].write_bytes((source_root / DEFAULTS["schema"]).read_bytes())
    paths["engine"].write_text("# test engine\n")
    paths["scanner"].write_text("# test scanner\n")
    paths["source_checker"].write_text("# test source checker\n")
    paths["reviewer"].write_text("# test reviewer\n")
    prompt_a = tmp_path / "governance/student_public_rights/reviewer_a.txt"
    prompt_b = tmp_path / "governance/student_public_rights/reviewer_b.txt"
    prompt_a.write_text("rights prompt\n")
    prompt_b.write_text("student prompt\n")
    reviewers = {
        label: {k: _record()[f"reviewer_{label}"][k] for k in
                ("identity", "model_id", "model_version")}
        for label in ("a", "b")
    }
    parameters = {"temperature": 0, "seed": 42, "num_ctx": 4096, "num_predict": 512}
    for label, prompt in (("a", prompt_a), ("b", prompt_b)):
        reviewers[label]["prompt_sha256"] = hashlib.sha256(prompt.read_bytes()).hexdigest()
        reviewers[label]["parameters_sha256"] = hashlib.sha256(
            _receipt_bytes(parameters)
        ).hexdigest()
    packet_a = _packet_artifact()
    packet_cftr = _packet_artifact(CFTR)
    packet_cftr["page_count"] = 3
    packet_cftr["placements"][0]["collection"] = "rag_nexus_cftr"
    packet = {"population": {"content_sha256_set_digest": hashlib.sha256(
        f"{CFTR}\n{SHA}\n".encode()).hexdigest()},
        "artifacts": [packet_a, packet_cftr]}
    paths["packet"].write_bytes(canonical_json_bytes(packet))
    paths["policy"].write_text(yaml.safe_dump(_policy(), sort_keys=True))
    digests = {key: hashlib.sha256(paths[key].read_bytes()).hexdigest()
               for key in ("packet", "policy", "schema", "engine", "scanner",
                           "source_checker", "reviewer")}
    mandate = _mandate()
    now = datetime.now(timezone.utc)
    mandate["created_at_utc"] = (now - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mandate["expires_at_utc"] = (now + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mandate["source_binding"] = {
        "source_main_commit_sha": G("1"), "source_main_tree_sha": G("2"),
        "inventory_file_sha256": digests["packet"],
        "inventory_content_sha256_set_digest": packet["population"]["content_sha256_set_digest"],
        "inventory_count": 2, "policy_sha256": digests["policy"],
        "schema_sha256": digests["schema"], "engine_code_sha256": digests["engine"],
        "scanner_code_sha256": digests["scanner"],
        "source_checker_code_sha256": digests["source_checker"],
        "reviewer_code_sha256": digests["reviewer"],
        "independent_verifier_code_sha256": hashlib.sha256(
            (source_root / "scripts/go_live/check_delegated_student_rights_gate.py").read_bytes()
        ).hexdigest(),
    }
    mandate["automated_reviewers"] = {
        f"reviewer_{label}": {
            "agent_identity": reviewers[label]["identity"],
            "model_id": reviewers[label]["model_id"],
            "model_version": reviewers[label]["model_version"],
            "prompt_sha256": reviewers[label]["prompt_sha256"],
            "prompt_path": str(prompt.relative_to(tmp_path)),
            "deterministic_parameters": parameters,
        }
        for label, prompt in (("a", prompt_a), ("b", prompt_b))
    }
    paths["mandate"].write_text(yaml.safe_dump(mandate, sort_keys=True))
    mandate_sha = hashlib.sha256(paths["mandate"].read_bytes()).hexdigest()
    records = [_record(), _record(CFTR)]
    records[1].update(
        page_count=3, final_disposition="EXCLUDE", student_suitability="FAIL",
        deterministic_policy_verdict="FAIL",
        reason_codes=["TEACHER_NON_DISCLOSURE_INSTRUCTION"], evidence_pages=[3],
    )
    records[1]["page_scans"].append({**records[1]["page_scans"][1], "page_number": 3})
    records[1]["text_assembly"].append(
        {**records[1]["text_assembly"][1], "page_number": 3}
    )
    records[1]["pdf_scan_evidence"].update(page_count=3, expected_page_count=3)
    records[1]["pdf_scan_evidence"]["pages"].append(
        {**records[1]["pdf_scan_evidence"]["pages"][1], "page_number": 3}
    )
    records[1]["reviewer_b"].update(verdict="FAIL")
    for record in records:
        for label in ("a", "b"):
            record[f"reviewer_{label}"].update(reviewers[label])
            if record["content_sha256"] == CFTR:
                record[f"reviewer_{label}"]["pages_covered"] = [1, 2, 3]
        record["bindings"] = {
            "inventory_sha256": digests["packet"], "policy_sha256": digests["policy"],
            "mandate_sha256": mandate_sha, "schema_sha256": digests["schema"],
            "engine_code_sha256": digests["engine"],
            "scanner_code_sha256": digests["scanner"],
            "source_checker_code_sha256": digests["source_checker"],
            "reviewer_code_sha256": digests["reviewer"],
            "pdf_sha256": record["content_sha256"],
        }
        record["pdf_scan_evidence"]["content_sha256"] = record["content_sha256"]
        record["source_verification"]["remote_pdf_sha256"] = record["content_sha256"]
        replay_results = {}
        for label in ("a", "b"):
            reviewer = record[f"reviewer_{label}"]
            for nonce in ((0, 1) if record["content_sha256"] != CFTR else (0,)):
                refs = []
                observations = []
                for page in range(1, record["page_count"] + 1):
                    fail = label == "b" and record["content_sha256"] == CFTR and page == 3
                    observation = {
                        "page_number": page, "segment_index": 1, "segment_count": 1,
                        "verdict": "FAIL" if fail else "PASS", "confidence": "HIGH",
                        "reason_codes": ["TEACHER_NON_DISCLOSURE_INSTRUCTION"] if fail else [],
                        "evidence_pages": [page], "visual_examined": True,
                    }
                    if label == "a":
                        observation["positive_rights_notice_present"] = True
                    receipt = {
                        "kind": "NEXUS-STUDENT-REVIEW-SEGMENT-RECEIPT-V1",
                        "assembly_protocol": "NEXUS_REVIEW_TEXT_ASSEMBLY_V3",
                        "content_sha256": record["content_sha256"],
                        "reviewer_identity": reviewer["identity"], "page_number": page,
                        "segment_index": 1, "segment_count": 1, "run_nonce": nonce,
                        "model_id": reviewer["model_id"],
                        "model_version": reviewer["model_version"],
                        "prompt_sha256": reviewer["prompt_sha256"],
                        "parameters_sha256": reviewer["parameters_sha256"],
                        "request_sha256": hashlib.sha256(
                            f"{label}:{record['content_sha256']}:{page}:{nonce}".encode()
                        ).hexdigest(),
                        "image_sha256": H("2"),
                        "observation_sha256": hashlib.sha256(_receipt_bytes(observation)).hexdigest(),
                        "observation": observation,
                    }
                    raw = _receipt_bytes(receipt)
                    digest = hashlib.sha256(raw).hexdigest()
                    path = paths["index"].parent / "receipts" / digest[:2] / f"{digest}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
                    refs.append(f"sha256:{digest}")
                    observations.append(_receipt_bytes(observation))
                result = {
                    "evidence_refs": refs,
                    "observation_sha256": hashlib.sha256(b"".join(observations)).hexdigest(),
                    "context_sha256": reviewer["context_sha256"] if nonce == 0
                    else H("e" if label == "a" else "f"),
                }
                if nonce == 0:
                    reviewer.update(result)
                else:
                    replay_results[label] = result
        if record["content_sha256"] != CFTR:
            for label in ("a", "b"):
                for key in ("evidence_refs", "observation_sha256", "context_sha256"):
                    record["candidate_replays"][0][f"reviewer_{label}_{key}"] = (
                        record[f"reviewer_{label}"][key]
                    )
                    record["candidate_replays"][1][f"reviewer_{label}_{key}"] = (
                        replay_results[label][key]
                    )
    refs = {}
    items = []
    for record, artifact in zip(records, (packet_a, packet_cftr), strict=True):
        raw = canonical_json_bytes(record)
        sha = record["content_sha256"]
        (paths["index"].parent / f"{sha}.json").write_bytes(raw)
        evidence_sha = hashlib.sha256(raw).hexdigest()
        refs[sha] = {"path": f"{sha}.json", "sha256": evidence_sha,
                     "source_placement_count": 1, "source_chunk_count": 2}
        items.append((record, artifact, evidence_sha))
    sheet = render_decision_sheet(items)
    paths["sheet"].write_bytes(sheet)
    index = {
        "schema_version": "NEXUS_DELEGATED_STUDENT_RIGHTS_EVIDENCE_INDEX_V1",
        "inventory_sha256": digests["packet"], "policy_sha256": digests["policy"],
        "delegation_sha256": mandate_sha, "mandate_sha256": mandate_sha,
        "schema_sha256": digests["schema"], "engine_code_sha256": digests["engine"],
        "scanner_code_sha256": digests["scanner"],
        "source_checker_code_sha256": digests["source_checker"],
        "reviewer_code_sha256": digests["reviewer"],
        "reviewer_a": reviewers["a"], "reviewer_b": reviewers["b"],
        "artifacts": refs, "decision_sheet_sha256": hashlib.sha256(sheet).hexdigest(),
        "final_population": {"collections": 1, "artifacts": 1, "placements": 1,
                             "chunks": 2, "approve_public": 1, "exclude": 1,
                             "replace_with_new_content": 0},
    }
    paths["index"].write_bytes(canonical_json_bytes(index))
    counts = {sha: {"source_placement_count": 1, "source_chunk_count": 2,
                    "collections": {"rag_nexus_test" if sha == SHA else "rag_nexus_cftr"},
                    "collection_placements": {
                        "rag_nexus_test" if sha == SHA else "rag_nexus_cftr": 1},
                    "source_chunks_sha256": H("4")}
              for sha in (SHA, CFTR)}
    monkeypatch.setattr("check_delegated_student_rights_gate._source_population",
                        lambda *_: (counts, {"rag_nexus_test", "rag_nexus_cftr"}, []))
    monkeypatch.setattr("check_delegated_student_rights_gate._git_source_binding",
                        lambda *_: [])
    mirror = tmp_path / "mirror"
    mirror.mkdir()
    monkeypatch.setattr("check_delegated_student_rights_gate._rescan_pdf",
                        lambda *_: [])
    monkeypatch.setattr("check_delegated_student_rights_gate._verify_approval_source_proof",
                        lambda *_: [])
    monkeypatch.setattr(
        "check_delegated_student_rights_gate._reconstruct_review_requests",
        lambda record, packet_artifact, _mirror: ({
            (label, nonce): {
                "requests": {
                    (page, 1): {
                        "request_sha256": hashlib.sha256(
                            f"{label}:{packet_artifact['content_sha256']}:{page}:{nonce}".encode()
                        ).hexdigest(),
                        "image_sha256": H("2"), "segment_count": 1,
                    } for page in range(1, packet_artifact["page_count"] + 1)
                },
                "context_sha256": (
                    record[f"reviewer_{label}"]["context_sha256"] if nonce == 0
                    else record["candidate_replays"][1][f"reviewer_{label}_context_sha256"]
                ),
            } for label in ("a", "b") for nonce in (0, 1)
        }, []),
    )
    return tmp_path, {"paths": paths, "index": index, "records": records,
                      "packet": packet, "items": items}


def test_sealed_fixture_passes_independent_gate(sealed_pack):
    root, _ = sealed_pack
    result = check_gate(root, expected_count=2, expected_head=G("1"),
                        source_mirror_root=root / "mirror")
    assert result["errors"] == []
    assert result["DELEGATED_RIGHTS_ADJUDICATION_PASS"] is True


def test_machine_pack_cannot_claim_active_human_authority(sealed_pack):
    root, pack = sealed_pack
    path = pack["paths"]["mandate"]
    mandate = yaml.safe_load(path.read_text())
    mandate.update(status="SEALED_ACTIVE", effective_authority=True)
    path.write_text(yaml.safe_dump(mandate, sort_keys=True))
    result = check_gate(root, expected_count=2, expected_head=G("1"),
                        source_mirror_root=root / "mirror")
    assert "MANDATE_NOT_SEALED" in result["errors"]
    assert "PREAPPROVAL_AUTHORITY_MUST_BE_FALSE" in result["errors"]


def test_git_source_binding_accepts_real_sha1_and_rejects_dirty_tree(tmp_path: Path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    source = tmp_path / "source.txt"
    source.write_text("sealed\n")
    subprocess.run(["git", "add", "source.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.org",
                    "commit", "-qm", "test: seal"], cwd=tmp_path, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=tmp_path,
                                   text=True).strip()
    assert len(head) == len(tree) == 40
    mandate = {"source_binding": {"source_main_commit_sha": head,
                                  "source_main_tree_sha": tree}}
    assert _git_source_binding(tmp_path, mandate, head) == []
    source.write_text("tampered\n")
    assert "CHECKOUT_NOT_CLEAN" in _git_source_binding(tmp_path, mandate, head)
    source.write_text("sealed\n")
    (tmp_path / "forged.json").write_text("{}\n")
    assert "CHECKOUT_NOT_CLEAN" in _git_source_binding(tmp_path, mandate, head)


def _reseal_records(pack: dict) -> None:
    """Simule un adversaire qui recalcule les SHA après modification sémantique."""
    paths = pack["paths"]
    index = pack["index"]
    packet = {p["content_sha256"]: p for p in pack["packet"]["artifacts"]}
    items = []
    for sha, ref in index["artifacts"].items():
        record = next(r for r in pack["records"] if r["bindings"]["pdf_sha256"] == sha)
        raw = canonical_json_bytes(record)
        digest = hashlib.sha256(raw).hexdigest()
        (paths["index"].parent / ref["path"]).write_bytes(raw)
        ref["sha256"] = digest
        items.append((record, packet[sha], digest))
    sheet = render_decision_sheet(items)
    paths["sheet"].write_bytes(sheet)
    index["decision_sheet_sha256"] = hashlib.sha256(sheet).hexdigest()
    paths["index"].write_bytes(canonical_json_bytes(index))


@pytest.mark.parametrize(
    ("sabotage", "expected"),
    [
        (lambda p: p["records"][0].update(final_disposition="PENDING"), "DISPOSITION_INVALID"),
        (lambda p: p["records"][0].update(rights_basis="NONE"), "APPROVAL_RIGHTS_BASIS"),
        (lambda p: p["records"][0].update(evidence_pages=[]), "APPROVAL_EVIDENCE_PAGES"),
        (lambda p: p["records"][0].update(content_sha256=H("f")), "CONTENT_IDENTITY"),
        (lambda p: p["records"][1].update(final_disposition="APPROVE_PUBLIC"), "CFTR_NOT_EXCLUDED"),
        (lambda p: p["records"][0]["reviewer_a"].update(identity=""), "REVIEWER_A_INCOMPLETE"),
        (lambda p: p["records"][0]["reviewer_a"].update(evidence_refs=[]),
         "APPROVAL_DUAL_REVIEW"),
        (lambda p: p["records"][0]["source_verification"].update(
            final_uri="https://other.example.org/unrelated.pdf"), "APPROVAL_SOURCE_MISMATCH"),
        (lambda p: p["records"][0].update(rights_basis="officiel_public"), "APPROVAL_RIGHTS_BASIS"),
        (lambda p: p["records"][0]["page_scans"][1].update(
            render_inspected=False), "FULL_SCAN_INCOMPLETE"),
    ],
)
def test_resealed_semantic_sabotage_still_fails(sealed_pack, sabotage, expected):
    root, pack = sealed_pack
    sabotage(pack)
    _reseal_records(pack)
    result = check_gate(root, expected_count=2, expected_head=G("1"),
                        source_mirror_root=root / "mirror")
    assert result["DELEGATED_RIGHTS_ADJUDICATION_PASS"] is False
    assert any(error.startswith(expected) for error in result["errors"])


def test_manual_sheet_change_is_detected(sealed_pack):
    root, pack = sealed_pack
    path = pack["paths"]["sheet"]
    path.write_bytes(path.read_bytes().replace(b"APPROVE_PUBLIC", b"EXCLUDE"))
    result = check_gate(root, expected_count=2, expected_head=G("1"),
                        source_mirror_root=root / "mirror")
    assert result["DELEGATED_RIGHTS_ADJUDICATION_PASS"] is False
    assert "DECISION_SHEET_TAMPERED" in result["errors"]


@pytest.mark.parametrize("tamper", ["missing", "changed"])
def test_missing_or_falsified_reviewer_cas_receipt_is_rejected(sealed_pack, tamper: str):
    root, pack = sealed_pack
    digest = pack["records"][0]["reviewer_a"]["evidence_refs"][0].split(":", 1)[1]
    path = pack["paths"]["index"].parent / "receipts" / digest[:2] / f"{digest}.json"
    if tamper == "missing":
        path.unlink()
    else:
        receipt = json.loads(path.read_bytes())
        receipt["observation"]["visual_examined"] = False
        path.write_bytes(_receipt_bytes(receipt))
    result = check_gate(root, expected_count=2, expected_head=G("1"),
                        source_mirror_root=root / "mirror")
    assert result["DELEGATED_RIGHTS_ADJUDICATION_PASS"] is False
    assert any(code.startswith("REVIEWER_A_RECEIPT_") for code in result["errors"])


def test_replay_cannot_reuse_first_run_receipts(sealed_pack):
    root, pack = sealed_pack
    record = pack["records"][0]
    record["candidate_replays"][1]["reviewer_a_evidence_refs"] = list(
        record["reviewer_a"]["evidence_refs"]
    )
    _reseal_records(pack)
    result = check_gate(root, expected_count=2, expected_head=G("1"),
                        source_mirror_root=root / "mirror")
    assert result["DELEGATED_RIGHTS_ADJUDICATION_PASS"] is False
    assert any(error.startswith("APPROVAL_REPLAY_DIVERGENCE")
               or error.startswith("REPLAY_REVIEWER_A_RECEIPT_")
               for error in result["errors"])


def test_replay_missing_cas_receipt_is_rejected(sealed_pack):
    root, pack = sealed_pack
    digest = pack["records"][0]["candidate_replays"][1][
        "reviewer_a_evidence_refs"][0].split(":", 1)[1]
    path = pack["paths"]["index"].parent / "receipts" / digest[:2] / f"{digest}.json"
    path.unlink()
    result = check_gate(root, expected_count=2, expected_head=G("1"),
                        source_mirror_root=root / "mirror")
    assert result["DELEGATED_RIGHTS_ADJUDICATION_PASS"] is False
    assert any(error.startswith("REPLAY_REVIEWER_A_RECEIPT_MISSING_OR_INVALID")
               for error in result["errors"])


def test_replay_boolean_nonce_cannot_impersonate_second_run(sealed_pack):
    root, pack = sealed_pack
    replay = pack["records"][0]["candidate_replays"][1]
    digest = replay["reviewer_a_evidence_refs"][0].split(":", 1)[1]
    path = pack["paths"]["index"].parent / "receipts" / digest[:2] / f"{digest}.json"
    receipt = json.loads(path.read_bytes())
    receipt["run_nonce"] = True
    raw = _receipt_bytes(receipt)
    forged_digest = hashlib.sha256(raw).hexdigest()
    forged_path = path.parent.parent / forged_digest[:2] / f"{forged_digest}.json"
    forged_path.parent.mkdir()
    forged_path.write_bytes(raw)
    replay["reviewer_a_evidence_refs"][0] = f"sha256:{forged_digest}"
    _reseal_records(pack)
    result = check_gate(root, expected_count=2, expected_head=G("1"),
                        source_mirror_root=root / "mirror")
    assert any(error.startswith("REPLAY_REVIEWER_A_RECEIPT_STRUCTURE")
               for error in result["errors"])
