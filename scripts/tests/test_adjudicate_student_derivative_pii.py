"""La décision PII du dérivé reste liée aux octets et aux preuves exactes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

from adjudicate_student_derivative_pii import (  # noqa: E402
    decide_artifact,
    require_matching_screen,
)

SHA = "a" * 64
SOURCE = "b" * 64
RECEIPT = "c" * 64


def _facts() -> tuple[dict, dict, dict, dict]:
    screen = {
        "content_sha256": SHA, "source_pdf_sha256": SOURCE,
        "derivative_receipt_sha256": RECEIPT,
        "text_byte_count": 100, "unresolved_hits": 0,
        "source_hash_metadata_hits": 2,
        "pattern_hits": {"phone_french": 2},
        "status": "PATTERN_SCREEN_CLEAR_ONLY",
    }
    packet = {"content_sha256": SOURCE, "source_pii_status": "CLEARED",
              "source_pdf_sha256_verified": True}
    source = {"content_sha256": SOURCE, "scan_complete": True,
              "images_and_annexes_checked": True,
              "pdf_scan_evidence": {"content_sha256": SOURCE,
                                    "exact_bytes_match": True,
                                    "full_document_scan_complete": True,
                                    "annexes_scan_complete": True}}
    receipt = {"source_content_sha256": SOURCE,
               "derivative_content_sha256": SHA,
               "all_source_pages_inspected": True,
               "ocr_used": False, "images_copied": False,
               "graphic_renders_copied": False,
               "pages": [{"packet_pii_status": "CLEARED",
                          "selected_block_indices": [0],
                          "all_blocks": [{"block_index": 0,
                                          "block_class": "SAFE_TEXT_CANDIDATE"}]}]}
    return screen, packet, source, receipt


def test_exact_subset_with_clean_full_text_is_pii_pass() -> None:
    screen, packet, source, receipt = _facts()
    assert decide_artifact(screen, packet, source, receipt,
                           native_blocks_reverified=1)["pii_status"] == "PASS"


def test_source_cleared_alone_is_not_sufficient() -> None:
    screen, packet, source, receipt = _facts()
    screen["unresolved_hits"] = 1
    assert decide_artifact(screen, packet, source, receipt,
                           native_blocks_reverified=1)["pii_status"] == "BLOCKED"


def test_source_full_scan_absent_blocks() -> None:
    screen, packet, source, receipt = _facts()
    source["pdf_scan_evidence"]["full_document_scan_complete"] = False
    assert decide_artifact(screen, packet, source, receipt,
                           native_blocks_reverified=1)["pii_status"] == "BLOCKED"


def test_source_pii_not_cleared_blocks() -> None:
    screen, packet, source, receipt = _facts()
    packet["source_pii_status"] = "UNVERIFIED"
    assert decide_artifact(screen, packet, source, receipt,
                           native_blocks_reverified=1)["pii_status"] == "BLOCKED"


def test_native_block_mismatch_blocks() -> None:
    screen, packet, source, receipt = _facts()
    assert decide_artifact(screen, packet, source, receipt,
                           native_blocks_reverified=0)["pii_status"] == "BLOCKED"


def test_graphic_or_ocr_blocks() -> None:
    screen, packet, source, receipt = _facts()
    receipt["ocr_used"] = True
    assert decide_artifact(screen, packet, source, receipt,
                           native_blocks_reverified=1)["pii_status"] == "BLOCKED"


def test_metadata_pattern_outside_canonical_sha_blocks() -> None:
    screen, packet, source, receipt = _facts()
    screen["pattern_hits"] = {"phone_french": 3}
    assert decide_artifact(screen, packet, source, receipt,
                           native_blocks_reverified=1)["pii_status"] == "BLOCKED"


def test_nonsafe_selected_block_blocks() -> None:
    screen, packet, source, receipt = _facts()
    receipt["pages"][0]["all_blocks"][0]["block_class"] = "PII_OR_UNCERTAIN"
    assert decide_artifact(screen, packet, source, receipt,
                           native_blocks_reverified=1)["pii_status"] == "BLOCKED"


def test_derivative_sha_spoof_blocks() -> None:
    screen, packet, source, receipt = _facts()
    receipt["derivative_content_sha256"] = "d" * 64
    assert decide_artifact(screen, packet, source, receipt,
                           native_blocks_reverified=1)["pii_status"] == "BLOCKED"


def test_pattern_screen_receipt_must_match_fresh_replay_except_timestamp() -> None:
    fresh = {"scanned_at_utc": "2026-10-10T14:00:00Z", "rows": [{"status": "CLEAR"}]}
    sealed = {"scanned_at_utc": "2026-10-10T13:00:00Z", "rows": [{"status": "CLEAR"}]}
    require_matching_screen(fresh, sealed)
    sealed["rows"][0]["status"] = "BLOCKED"
    import pytest  # noqa: PLC0415
    with pytest.raises(ValueError, match="PATTERN_SCREEN_REPLAY_MISMATCH"):
        require_matching_screen(fresh, sealed)
