"""La fraîcheur source doit être prouvée pour les octets PDF exacts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

from attest_student_derivative_source_currentness import assess_fresh_checkpoint  # noqa: E402

SOURCE = "a" * 64
DERIVATIVE = "b" * 64
URI = "https://eduscol.education.gouv.fr/source.pdf"
LISTING = "c" * 64


def _facts() -> tuple[dict, dict, dict]:
    entry = {"source_content_sha256": SOURCE,
             "derivative_content_sha256": DERIVATIVE,
             "citation": {"source_uri": URI,
                          "source_updated_at": "2026-10-10T06:00:00Z"}}
    row = {"content_sha256": SOURCE, "source_status": "EXACT_CURRENT_SOURCE",
           "currentness_status": "PASS",
           "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION"}
    current_ref = {"pdf_sha256": SOURCE, "pdf_url": URI,
                   "listing_capture_receipt_sha256": LISTING}
    checkpoint = {"content_sha256": SOURCE,
                  "source_provenance": {
                      "status": "EXACT_CURRENT_SOURCE",
                      "currentness_status": "PASS",
                      "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
                      "retraction_notice_associated": False,
                      "currentness_observed_at_utc": "2026-10-10T13:00:00Z",
                      "revocation_observed_at_utc": "2026-10-10T13:00:00Z",
                      "pdf_fetch": {"requested_url": URI, "final_url": URI,
                                    "http_status": 200, "content_sha256": SOURCE,
                                    "byte_count": 100,
                                    "observed_at_utc": "2026-10-10T13:00:00Z"},
                      "currentness_evidence_ref": current_ref,
                      "revocation_evidence_ref": current_ref,
                  }}
    return entry, row, checkpoint


def test_fresh_exact_pdf_and_listing_can_pass() -> None:
    entry, row, checkpoint = _facts()
    assert assess_fresh_checkpoint(entry, row, checkpoint,
                                   listing_receipt_sha256=LISTING)["status"] == "PASS"


def test_pdf_sha_change_blocks() -> None:
    entry, row, checkpoint = _facts()
    checkpoint["source_provenance"]["pdf_fetch"]["content_sha256"] = "d" * 64
    assert assess_fresh_checkpoint(entry, row, checkpoint,
                                   listing_receipt_sha256=LISTING)["status"] == "BLOCKED"


def test_pdf_url_change_blocks() -> None:
    entry, row, checkpoint = _facts()
    checkpoint["source_provenance"]["pdf_fetch"]["final_url"] = "https://eduscol.education.gouv.fr/other.pdf"
    assert assess_fresh_checkpoint(entry, row, checkpoint,
                                   listing_receipt_sha256=LISTING)["status"] == "BLOCKED"


def test_retraction_signal_blocks() -> None:
    entry, row, checkpoint = _facts()
    checkpoint["source_provenance"]["retraction_notice_associated"] = True
    assert assess_fresh_checkpoint(entry, row, checkpoint,
                                   listing_receipt_sha256=LISTING)["status"] == "BLOCKED"


def test_listing_digest_mismatch_blocks() -> None:
    entry, row, checkpoint = _facts()
    assert assess_fresh_checkpoint(entry, row, checkpoint,
                                   listing_receipt_sha256="d" * 64)["status"] == "BLOCKED"


def test_stale_observation_before_attribution_blocks() -> None:
    entry, row, checkpoint = _facts()
    checkpoint["source_provenance"]["revocation_observed_at_utc"] = "2026-10-09T23:00:00Z"
    assert assess_fresh_checkpoint(entry, row, checkpoint,
                                   listing_receipt_sha256=LISTING)["status"] == "BLOCKED"
