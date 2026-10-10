"""Le reçu d'inclusion dépend des preuves complètes, jamais du seul dépistage."""

from __future__ import annotations

import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))
checker = importlib.import_module("check_student_public_derivative_inclusions")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _fixture() -> tuple[dict, bytes, bytes]:
    derivative = _sha(b"texte derive")
    source = _sha(b"pdf exact")
    receipt = _sha(b"recu")
    artifact = {
        "content_sha256": derivative, "source_pdf_sha256": source,
        "derivative_receipt_sha256": receipt,
        "citation": {"source_uri": "https://eduscol.education.gouv.fr/example.pdf"},
    }
    sources = {"inputs": {
        "candidate_manifest_sha256": "a" * 64,
        "artifact_registry_sha256": "b" * 64,
        "release": {"authorities": {"rights_authority_sha256": "8" * 64}},
        "artifacts": {"artifacts": [artifact]},
    }, "inventory": {"counts": {"unique_artifacts": 1}}}
    pii_row = {
        "decision_kind": "NEXUS_STUDENT_DERIVATIVE_PII_DECISION_V1",
        "derivative_content_sha256": derivative, "source_pdf_sha256": source,
        "derivative_receipt_sha256": receipt, "pii_scan_scope": "FULL_DERIVATIVE_TEXT",
        "pii_status": "PASS", "reason_codes": [], "text_byte_count": len(b"texte derive"),
        "policy_sha256": "c" * 64,
    }
    pii_row["evidence_sha256"] = _sha(_canonical(pii_row))
    current_row = {
        "derivative_content_sha256": derivative, "source_pdf_sha256": source,
        "derivative_receipt_sha256": receipt, "source_uri": artifact["citation"]["source_uri"],
        "status": "PASS", "reason_codes": [],
        "fresh_source_checkpoint_file_sha256": "d" * 64,
        "fresh_source_checkpoint_sha256": "e" * 64,
        "fresh_listing_receipt_sha256": "f" * 64,
        "fresh_pdf_fetch_receipt_sha256": "1" * 64,
    }
    current_row["evidence_sha256"] = _sha(_canonical(current_row))
    pii = {
        "kind": "NEXUS_STUDENT_DERIVATIVE_PII_ADJUDICATION_V1",
        "candidate_manifest_sha256": sources["inputs"]["candidate_manifest_sha256"],
        "artifact_registry_sha256": sources["inputs"]["artifact_registry_sha256"],
        "pii_decision_scope": "DETERMINISTIC_FULL_DERIVATIVE_TEXT_AND_SOURCE_REVIEW",
        "currentness_revocation_status": "UNPROVEN_FOR_SUCCESSOR",
        "decision_count": 1, "status_counts": {"PASS": 1},
        "policy_sha256": "c" * 64, "rows": [pii_row],
    }
    current = {
        "kind": "NEXUS_STUDENT_DERIVATIVE_SOURCE_CURRENTNESS_ATTESTATION_V1",
        "candidate_manifest_sha256": sources["inputs"]["candidate_manifest_sha256"],
        "fresh_source_index_file_sha256": "2" * 64,
        "fresh_source_index_logical_sha256": "3" * 64,
        "successor_release_binding": "NOT_YET_SEALED",
        "fresh_source_checked_at_utc": "2026-10-10T13:00:00Z",
        "attested_at_utc": "2026-10-10T13:01:00Z",
        "decision_count": 1, "status_counts": {"PASS": 1}, "rows": [current_row],
    }
    return sources, _canonical(pii), _canonical(current)


def test_report_pair_produces_only_exact_complete_derivative_rows():
    source, pii_raw, current_raw = _fixture()
    rows = checker.verify_report_pair(
        source, pii_raw, current_raw,
        as_of=datetime(2026, 10, 10, 14, tzinfo=timezone.utc),
    )
    assert len(rows) == 1
    assert rows[0][0]["content_sha256"] == source["inputs"]["artifacts"]["artifacts"][0]["content_sha256"]


@pytest.mark.parametrize("change", [
    "pattern_only", "missing_row", "wrong_source", "pii_blocked", "current_blocked",
    "pii_row_tampered", "current_row_tampered", "wrong_candidate", "wrong_receipt",
    "stale_currentness",
])
def test_report_pair_fails_closed_on_sabotage(change):
    source, pii_raw, current_raw = _fixture()
    pii, current = json.loads(pii_raw), json.loads(current_raw)
    if change == "pattern_only":
        pii["kind"] = "NEXUS_STUDENT_DERIVATIVE_PII_PATTERN_SCREEN_V1"
    elif change == "missing_row":
        current["rows"] = []
    elif change == "wrong_source":
        current["rows"][0]["source_pdf_sha256"] = "4" * 64
    elif change == "pii_blocked":
        pii["rows"][0]["pii_status"] = "BLOCKED"
    elif change == "current_blocked":
        current["rows"][0]["status"] = "BLOCKED"
    elif change == "pii_row_tampered":
        pii["rows"][0]["text_byte_count"] += 1
    elif change == "current_row_tampered":
        current["rows"][0]["source_uri"] = "https://example.org/other.pdf"
    elif change == "wrong_candidate":
        current["candidate_manifest_sha256"] = "5" * 64
    elif change == "wrong_receipt":
        pii["rows"][0]["derivative_receipt_sha256"] = "6" * 64
    elif change == "stale_currentness":
        current["fresh_source_checked_at_utc"] = "2026-10-08T13:00:00Z"
    with pytest.raises(ValueError):
        checker.verify_report_pair(
            source, _canonical(pii), _canonical(current),
            as_of=datetime(2026, 10, 10, 14, tzinfo=timezone.utc),
        )


def test_inclusion_is_deterministic_and_binds_both_reports():
    source, pii_raw, current_raw = _fixture()
    row_pair = checker.verify_report_pair(
        source, pii_raw, current_raw,
        as_of=datetime(2026, 10, 10, 14, tzinfo=timezone.utc),
    )
    inclusion = checker.make_inclusion(
        source, pii_raw, current_raw, row_pair,
        private_cas_manifest_sha256="9" * 64,
        source_currentness_valid_until=datetime(2026, 10, 11, 13, tzinfo=timezone.utc),
    )
    assert inclusion["kind"] == "NEXUS_STUDENT_PUBLIC_DERIVATIVE_INCLUSIONS_V2"
    assert inclusion["pii_adjudication_report_sha256"] == _sha(pii_raw)
    assert inclusion["source_currentness_attestation_sha256"] == _sha(current_raw)
    assert inclusion["decision_count"] == 1
    assert inclusion["private_cas_manifest_sha256"] == "9" * 64
    assert inclusion["decisions"][0]["disposition"] == "INCLUDE"
    assert inclusion["decisions"][0]["source_pdf_sha256"] == source["inputs"]["artifacts"]["artifacts"][0]["source_pdf_sha256"]
    assert checker.make_inclusion(
        source, pii_raw, current_raw, row_pair,
        private_cas_manifest_sha256="9" * 64,
        source_currentness_valid_until=datetime(2026, 10, 11, 13, tzinfo=timezone.utc),
    ) == inclusion


def test_private_cas_is_immutable_and_tampered_bytes_are_refused(tmp_path):
    repository = tmp_path / "repo"
    repository.mkdir()
    origin = tmp_path / "proof.txt"
    origin.write_bytes(b"private evidence")
    cas = tmp_path / "private-cas"
    index_sha = checker.write_private_cas(
        cas, {Path("derivatives/proof.txt"): origin}, repository_root=repository,
        candidate_sha256="a" * 64,
    )
    refs = checker.verify_cas_files(cas, candidate_sha256="a" * 64)
    assert _sha((cas / "index.json").read_bytes()) == index_sha
    assert refs == {"derivatives/proof.txt": _sha(b"private evidence")}
    with pytest.raises(ValueError, match="already exists"):
        checker.write_private_cas(
            cas, {Path("derivatives/proof.txt"): origin}, repository_root=repository,
            candidate_sha256="a" * 64,
        )
    (cas / "derivatives/proof.txt").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="digest"):
        checker.verify_cas_files(cas, candidate_sha256="a" * 64)


def test_private_cas_cannot_be_written_inside_repository(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    origin = tmp_path / "proof.txt"
    origin.write_bytes(b"private")
    with pytest.raises(ValueError, match="outside repository"):
        checker.write_private_cas(
            root / "cas", {Path("proof.txt"): origin}, repository_root=root,
            candidate_sha256="a" * 64,
        )


def test_missing_private_receipt_is_refused(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    origin = tmp_path / "receipt.json"
    origin.write_bytes(b"private receipt")
    cas = tmp_path / "cas"
    checker.write_private_cas(
        cas, {Path("derivative_receipts/receipt.json"): origin},
        repository_root=root, candidate_sha256="a" * 64,
    )
    (cas / "derivative_receipts/receipt.json").unlink()
    with pytest.raises(FileNotFoundError):
        checker.verify_cas_files(cas, candidate_sha256="a" * 64)


def test_cross_line_source_swap_with_rehashed_row_is_refused():
    source, pii_raw, current_raw = _fixture()
    current = json.loads(current_raw)
    row = current["rows"][0]
    row["source_pdf_sha256"] = "7" * 64
    row["evidence_sha256"] = _sha(_canonical({
        key: value for key, value in row.items() if key != "evidence_sha256"
    }))
    with pytest.raises(ValueError, match="report evidence differs"):
        checker.verify_report_pair(
            source, pii_raw, _canonical(current),
            as_of=datetime(2026, 10, 10, 14, tzinfo=timezone.utc),
        )


def test_inclusion_cannot_be_generated_from_an_incomplete_private_cas(tmp_path):
    source, _, _ = _fixture()
    root = tmp_path / "repo"
    root.mkdir()
    origin = tmp_path / "proof.txt"
    origin.write_bytes(b"unrelated")
    cas = tmp_path / "cas"
    checker.write_private_cas(
        cas, {Path("derivatives/unrelated.txt"): origin}, repository_root=root,
        candidate_sha256=source["inputs"]["candidate_manifest_sha256"],
    )
    with pytest.raises((ValueError, FileNotFoundError), match="proof|missing|population"):
        checker.verify_private_cas_evidence(source, cas)


def test_builder_rejects_legacy_unverified_inclusion():
    from build_student_public_successor_release import load_sources, validate_inclusions

    source = load_sources(ROOT)
    decisions = [
        {"content_sha256": item["content_sha256"], "disposition": "INCLUDE",
         "evidence_sha256": "b" * 64}
        for item in source["inputs"]["artifacts"]["artifacts"]
    ]
    old = {
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_INCLUSIONS_V1",
        "source_candidate_manifest_sha256": source["inputs"]["candidate_manifest_sha256"],
        "source_candidate_inventory_sha256": _sha(_canonical(source["inventory"])),
        "pii_scan_report_sha256": "a" * 64,
        "decisions": sorted(decisions, key=lambda row: row["content_sha256"]),
    }
    with pytest.raises(ValueError, match="verified inclusion"):
        validate_inclusions(source, old)


def test_capture_timing_rejects_old_listings_and_gets_under_advanced_index():
    observed = datetime(2026, 10, 10, 13, 40, tzinfo=timezone.utc)
    checked = datetime(2026, 10, 10, 13, 44, tzinfo=timezone.utc)
    checker.check_capture_timing(
        checked, observed, observed, observed, observed,
        as_of=datetime(2026, 10, 10, 14, tzinfo=timezone.utc),
    )
    with pytest.raises(ValueError, match="capture timing"):
        checker.check_capture_timing(
            datetime(2026, 10, 12, 13, 44, tzinfo=timezone.utc),
            observed, observed, observed, observed,
            as_of=datetime(2026, 10, 12, 14, tzinfo=timezone.utc),
        )


def test_listing_body_paths_require_all_three_exact_bodies(tmp_path):
    prefix = "a" * 16
    body_specs = (
        ("normalized_html", ".normalized.html", b"<html>source</html>"),
        ("extracted_text", ".extracted.txt", b"source text"),
        ("screenshot", ".png", b"PNG bytes"),
    )
    receipt = {}
    for name, suffix, raw in body_specs:
        filename = prefix + suffix
        (tmp_path / filename).write_bytes(raw)
        receipt[name + "_file"] = filename
        receipt[name + "_sha256"] = _sha(raw)
    paths = checker.listing_body_paths(receipt, "a" * 64, tmp_path, prefix=prefix)
    assert len(paths) == 3
    assert all(path.exists() for path in paths.values())
    (tmp_path / (prefix + ".png")).unlink()
    with pytest.raises((FileNotFoundError, ValueError)):
        checker.listing_body_paths(receipt, "a" * 64, tmp_path, prefix=prefix)
    (tmp_path / (prefix + ".png")).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="listing body"):
        checker.listing_body_paths(receipt, "a" * 64, tmp_path, prefix=prefix)
