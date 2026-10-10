"""Le texte candidat exige des preuves liées à ses propres octets."""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

from student_derivative_pii_currentness_gate import (  # noqa: E402
    assess_derivative,
    assess_repository,
)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _raw(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.fixture
def valid() -> dict:
    source = "a" * 64
    attribution = {
        "source_uri": "https://eduscol.education.gouv.fr/example.pdf",
        "source_label": "Document",
        "source_updated_at": "2026-10-10T06:00:00Z",
        "source_date_kind": "DATED_OFFICIAL_SNAPSHOT",
        "licensor": "Dgesco",
        "licence_id": "ETALAB-2.0",
        "derivative_notice": "Extrait textuel ; snapshot du 2026-10-10T06:00:00Z",
    }
    header = b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n" + _raw({"source_pdf_sha256": source, **attribution})
    body = b"\n[PAGE 1 BLOCK 0]\nCitation\nTexte scolaire admissible\n"
    page_text = header + body
    block_start = page_text.index(b"Texte scolaire admissible")
    block_end = block_start + len(b"Texte scolaire admissible")
    receipt = {
        "kind": "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1",
        "source_content_sha256": source,
        "source_page_count": 2,
        "source_provenance_checkpoint_sha256": "b" * 64,
        "derivative_content_sha256": _sha(page_text),
        "derivative_byte_count": len(page_text),
        "source_attribution": attribution,
        "status": "PREPARED_PRIVATE",
        "all_source_pages_inspected": True,
        "ocr_used": False,
        "images_copied": False,
        "graphic_renders_copied": False,
        "pages": [
            {"page_number": 1, "byte_start": len(header), "byte_end": len(page_text),
             "derived_page_text_sha256": _sha(body),
             "packet_pii_status": "CLEARED", "selected_block_indices": [0],
             "all_blocks": [{"block_index": 0, "block_class": "SAFE_TEXT_CANDIDATE",
                             "byte_start": block_start, "byte_end": block_end}],
             "excluded_blocks": [], "review_groups": [
                 {"block_indices": [0], "byte_start": block_start, "byte_end": block_end,
                  "group_text_sha256": _sha(b"Texte scolaire admissible")}]},
            {"page_number": 2, "byte_start": len(page_text),
             "byte_end": len(page_text), "derived_page_text_sha256": _sha(b""),
             "packet_pii_status": "CLEARED", "selected_block_indices": [],
             "all_blocks": [{"block_index": 0, "block_class": "EXCLUDED_NON_TEXT"}],
             "excluded_blocks": [{"block_index": 0, "reason_code": "RASTER_OVERLAP"}],
             "review_groups": []},
        ],
    }
    receipt_raw = _raw(receipt)
    artifact = {
        "content_sha256": _sha(page_text), "source_pdf_sha256": source,
        "derivative_receipt_sha256": _sha(receipt_raw),
        "excluded_source_pages": [2], "page_count": 2,
        "citation": {**receipt["source_attribution"], "source_pdf_sha256": source},
        "chunks": [{"page_start": 1, "page_end": 1}],
    }
    manifest_entry = {
        "derivative_content_sha256": _sha(page_text),
        "source_content_sha256": source,
        "derivative_receipt_sha256": _sha(receipt_raw),
        "citation": receipt["source_attribution"],
        "derivative_disposition": "APPROVE_PUBLIC",
        "source_disposition": "REPLACE_WITH_NEW_CONTENT",
    }
    source_evidence = {
        "content_sha256": source,
        "source_receipt_sha256": "b" * 64,
        "derivative_content_sha256": _sha(page_text),
        "derivative_receipt_sha256": _sha(receipt_raw),
        "source_disposition": "REPLACE_WITH_NEW_CONTENT",
        "derivative_disposition": "APPROVE_PUBLIC",
        "scan_complete": True, "images_and_annexes_checked": True,
    }
    source_raw = _raw(source_evidence)
    provenance = {
        "content_sha256": source,
        "checkpoint_file_sha256": "b" * 64,
        "currentness_status": "PASS",
        "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
        "source_status": "EXACT_CURRENT_SOURCE",
    }
    independent = {
        "kind": "NEXUS_STUDENT_DERIVATIVE_PII_CURRENTNESS_EVIDENCE_V1",
        "derivative_content_sha256": _sha(page_text),
        "source_pdf_sha256": source,
        "derivative_receipt_sha256": _sha(receipt_raw),
        "source_provenance_checkpoint_sha256": "b" * 64,
        "source_checkpoint_file_sha256": "b" * 64,
        "source_uri": receipt["source_attribution"]["source_uri"],
        "source_updated_at": receipt["source_attribution"]["source_updated_at"],
        "verified_at_utc": "2026-10-10T09:00:00Z",
        "pii_scan_scope": "FULL_DERIVATIVE_TEXT",
        "pii_status": "PASS",
        "currentness_status": "PASS",
        "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
        "reviewed_derivative_text_sha256": _sha(page_text),
        "source_checkpoint_exact_bytes_match": True,
        "revocation_check_source_uri": receipt["source_attribution"]["source_uri"],
    }
    return dict(text=page_text, receipt_raw=receipt_raw, artifact=artifact,
                manifest_entry=manifest_entry, source_raw=source_raw,
                source_index_ref={"sha256": _sha(source_raw)},
                provenance=provenance, source_checkpoint_raw=None,
                independent=independent)


def _assess(value: dict) -> dict:
    return assess_derivative(**value)


def test_missing_source_checkpoint_and_derivative_review_block(valid: dict) -> None:
    value = {**valid, "independent": None}
    result = _assess(value)
    assert result["structural_status"] == "PASS"
    assert result["publication_status"] == "BLOCKED"
    assert "DERIVATIVE_PII_REVIEW_MISSING" in result["reasons"]
    assert "CURRENTNESS_CHECKPOINT_MISSING" in result["reasons"]


def test_exact_positive_evidence_passes(valid: dict) -> None:
    source_uri = valid["receipt_raw"] and json.loads(valid["receipt_raw"])["source_attribution"]["source_uri"]
    checkpoint = {
        "kind": "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1",
        "content_sha256": valid["artifact"]["source_pdf_sha256"],
        "source_provenance": {
            "status": "EXACT_CURRENT_SOURCE", "currentness_status": "PASS",
            "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
            "retraction_notice_associated": False,
            "currentness_evidence_ref": {"pdf_sha256": valid["artifact"]["source_pdf_sha256"], "pdf_url": source_uri},
            "revocation_evidence_ref": {"pdf_sha256": valid["artifact"]["source_pdf_sha256"], "pdf_url": source_uri,
                                        "listing_capture_receipt_sha256": "e" * 64},
            "source_updated_at": {"date": "2026-10-10T06:00:00Z"},
            "currentness_observed_at_utc": "2026-10-10T06:00:00Z",
            "revocation_observed_at_utc": "2026-10-10T06:00:00Z",
        },
    }
    logical_sha = _sha(_raw(checkpoint))
    checkpoint["checkpoint_sha256"] = logical_sha
    value = {**valid, "source_checkpoint_raw": _raw(checkpoint)}
    value["receipt_raw"] = _raw({**json.loads(value["receipt_raw"]),
                                 "source_provenance_checkpoint_sha256": logical_sha})
    receipt_sha = _sha(value["receipt_raw"])
    for key in ("artifact", "manifest_entry", "independent"):
        value[key]["derivative_receipt_sha256"] = receipt_sha
    value["source_raw"] = _raw({**json.loads(value["source_raw"]),
                                "derivative_receipt_sha256": receipt_sha,
                                "source_receipt_sha256": _sha(value["source_checkpoint_raw"])})
    value["source_index_ref"]["sha256"] = _sha(value["source_raw"])
    value["provenance"]["checkpoint_file_sha256"] = _sha(value["source_checkpoint_raw"])
    value["independent"]["source_provenance_checkpoint_sha256"] = logical_sha
    value["independent"]["source_checkpoint_file_sha256"] = _sha(value["source_checkpoint_raw"])
    result = _assess(value)
    assert result["publication_status"] == "PASS"


@pytest.mark.parametrize("mutation,reason", [
    (lambda v: v.update(text=b"other"), "DERIVATIVE_TEXT_SHA_MISMATCH"),
    (lambda v: v["artifact"].update(excluded_source_pages=[]), "EXCLUDED_PAGES_MISMATCH"),
    (lambda v: v["source_raw"] and v.update(source_raw=b"{}"), "PR300_SOURCE_EVIDENCE_DIGEST_MISMATCH"),
    (lambda v: v["artifact"]["chunks"][0].update(page_start=2, page_end=2), "CHUNK_ON_EXCLUDED_PAGE"),
    (lambda v: v["independent"].update(reviewed_derivative_text_sha256="c" * 64), "DERIVATIVE_PII_REVIEW_MISMATCH"),
    (lambda v: v["independent"].update(source_updated_at=""), "ATTRIBUTION_DATE_MISMATCH"),
    (lambda v: v["independent"].update(revocation_status="UNKNOWN"), "REVOCATION_UNPROVEN"),
    (lambda v: v["independent"].update(source_checkpoint_exact_bytes_match=False), "ATTRIBUTION_DATE_MISMATCH"),
    (lambda v: v["receipt_raw"] and v.update(receipt_raw=v["receipt_raw"] + b" "), "DERIVATIVE_RECEIPT_SHA_MISMATCH"),
])
def test_sabotage_is_blocked(valid: dict, mutation, reason: str) -> None:
    value = copy.deepcopy(valid)
    mutation(value)
    assert reason in _assess(value)["reasons"]


def test_malformed_page_count_fails_closed(valid: dict) -> None:
    value = copy.deepcopy(valid)
    receipt = json.loads(value["receipt_raw"])
    receipt["source_page_count"] = None
    value["receipt_raw"] = _raw(receipt)
    assert "PAGE_COVERAGE_INVALID" in _assess(value)["reasons"]


def test_real_candidate_has_253_records_and_no_unproved_promotion() -> None:
    private = Path.home() / "nexus-student-public-release-eb39f6cd0423e184"
    if not private.is_dir():
        pytest.skip("CAS privé #312 absent")
    result = assess_repository(ROOT, private)
    assert result["artifact_count"] == 253
    assert result["structural_pass_count"] == 253
    assert result["publication_pass_count"] == 0
    assert result["publication_blocked_count"] == 253
    assert result["missing_derivative_pii_review_count"] == 253


def test_unsealed_independent_packets_are_rejected(tmp_path: Path) -> None:
    private = Path.home() / "nexus-student-public-release-eb39f6cd0423e184"
    if not private.is_dir():
        pytest.skip("CAS privé #312 absent")
    (tmp_path / "index.json").write_text("{}")
    with pytest.raises(ValueError, match="INDEPENDENT_EVIDENCE_INDEX_UNSEALED"):
        assess_repository(ROOT, private, independent_root=tmp_path)
