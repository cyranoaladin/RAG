"""Sabotages du vérificateur indépendant de la délégation étudiante."""

from __future__ import annotations

import csv
import hashlib
import json
import copy
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
import check_delegated_student_rights_gate as gate  # noqa: E402

from check_delegated_student_rights_gate import (  # noqa: E402
    DEFAULTS,
    _git_source_binding,
    _reconstruct_review_requests,
    _verify_approval_source_proof,
    _verify_review_receipts,
    _verify_sitewide_authority,
    _verify_text_derivative,
    _verify_candidate_manifest,
    _candidate_derivative_bindings,
    _verify_source_provenance,
    _verify_derivative_receipt_cas,
    _rescan_pdf,
    _source_population,
    canonical_json_bytes,
    check_artifact,
    check_gate,
    render_decision_sheet,
)


def test_real_chromium_sitewide_authority_capture_is_integral():
    root = Path(__file__).resolve().parents[2]
    authority_path = root / "governance/student_public_rights/authorities/eduscol_etalab_2_0_sitewide_20261010.yml"
    authority = yaml.safe_load(authority_path.read_bytes())
    assert _verify_sitewide_authority(root, authority) == []


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda a: a.pop("browser_capture"), "AUTHORITY_CAPTURE_MISSING"),
        (lambda a: a.update(legal_notice_url="https://example.org/mentions-legales"),
         "AUTHORITY_DOMAIN_MISMATCH"),
        (lambda a: a["browser_capture"]["legal_notice"].update(extracted_text_sha256="0" * 64),
         "AUTHORITY_CAPTURE_DIGEST"),
        (lambda a: a.update(attribution_required=["source", "URL"]), "AUTHORITY_ATTRIBUTION_SCOPE"),
        (lambda a: a.update(excluded_components=[]), "AUTHORITY_THIRD_PARTY_SCOPE"),
    ],
)
def test_sitewide_authority_sabotages_fail_closed(mutation, expected):
    root = Path(__file__).resolve().parents[2]
    path = root / "governance/student_public_rights/authorities/eduscol_etalab_2_0_sitewide_20261010.yml"
    authority = copy.deepcopy(yaml.safe_load(path.read_bytes()))
    mutation(authority)
    assert expected in _verify_sitewide_authority(root, authority)


def test_independent_text_derivative_reconstruction_matches_real_differential():
    base = Path("/tmp/rag-derivative-differential-v4")
    receipt_path = base / ("evidence/derivative_receipts/28/"
                           "28fcd6d1096fbfdd7d6297e5359cb5cd22317c01bd2e1f0e0b9df0e2f210f3c5.json")
    if not receipt_path.is_file():
        pytest.skip("Le témoin différentiel privé du générateur n'est pas présent")
    receipt = json.loads(receipt_path.read_bytes())
    packet = {
        "content_sha256": receipt["source_content_sha256"],
        "page_count": 1, "source_pii_status": "CLEARED",
        "automated_review_signals": [], "explicit_student_exclusion_signal": False,
    }
    candidate_path = base / "private" / receipt["candidate_relpath"]
    args = (receipt, base / "source.pdf", packet, candidate_path.read_bytes(),
            receipt["extraction_policy_sha256"], receipt["adjudication_policy_sha256"],
            receipt["generator_code_sha256"])
    assert _verify_text_derivative(*args) == []
    altered = copy.deepcopy(receipt)
    altered["pages"][0]["all_blocks"][1]["block_class"] = "SAFE_TEXT_CANDIDATE"
    assert "DERIVATIVE_BLOCK_MAP_MISMATCH" in _verify_text_derivative(
        altered, *args[1:])
    assert "DERIVATIVE_BYTES_MISMATCH" in _verify_text_derivative(
        receipt, args[1], packet, candidate_path.read_bytes() + b"image", *args[4:])
    altered = copy.deepcopy(receipt)
    altered["images_copied"] = True
    assert "DERIVATIVE_NON_TEXT_PUBLIC" in _verify_text_derivative(altered, *args[1:])


def test_derivative_publisher_proof_recomputed_from_exact_pdf(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    from student_rights_text_derivative import build_text_candidate

    pdf = tmp_path / "source.pdf"
    document = fitz.open()
    document.set_metadata({"author": "DGESCO"})
    document.new_page().insert_text((50, 50), "Le cycle hydrologique et les precipitations.")
    document.save(pdf)
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    packet = {"content_sha256": sha, "page_count": 1,
              "automated_review_signals": [], "source_pii_status": "CLEARED",
              "explicit_student_exclusion_signal": False}
    snapshot = "2026-10-10T00:00:00Z"
    attribution = {"source_uri": "https://eduscol.education.gouv.fr/doc.pdf",
                   "source_label": "Test", "source_updated_at": snapshot,
                   "source_date_kind": "DATED_OFFICIAL_SNAPSHOT",
                   "licensor": "Ministère de l’Éducation nationale",
                   "licence_id": "ETALAB-2.0", "derivative_notice": f"snapshot du {snapshot}"}
    candidate = build_text_candidate(pdf, sha, 1, attribution, packet)
    assert candidate.content is not None
    receipt = candidate.evidence
    receipt["candidate_relpath"] = f"candidates/{receipt['derivative_content_sha256']}.txt"
    args = (pdf, packet, candidate.content, receipt["extraction_policy_sha256"],
            receipt["adjudication_policy_sha256"], receipt["generator_code_sha256"])
    assert _verify_text_derivative(receipt, *args) == []
    altered = copy.deepcopy(receipt)
    altered["publisher_proof"] = {"status": "UNPROVEN", "kind": None}
    altered["publisher_status"] = "UNPROVEN"
    assert "DERIVATIVE_PUBLISHER_PROOF_MISMATCH" in _verify_text_derivative(altered, *args)


def test_first_party_copyright_is_not_treated_as_third_party_credit():
    from check_delegated_student_rights_gate import _derivative_reason

    assert _derivative_reason("© DGESCO") is None
    assert _derivative_reason("© Editions Nathan") == "THIRD_PARTY_SIGNAL"


def test_third_party_credit_excludes_whole_page_from_derivative(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    from student_rights_text_derivative import build_text_candidate

    pdf = tmp_path / "source.pdf"
    document = fitz.open()
    document.set_metadata({"author": "DGESCO"})
    document.new_page().insert_text((50, 50), "Le cycle de l'eau est une notion étudiée.")
    second = document.new_page()
    second.insert_text((50, 50), "Un énoncé potentiellement utile.")
    second.insert_text((50, 80), "© Editions Nathan")
    document.save(pdf)
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    packet = {"content_sha256": sha, "page_count": 2,
              "automated_review_signals": [], "source_pii_status": "CLEARED",
              "explicit_student_exclusion_signal": False}
    date = "2026-10-10T00:00:00Z"
    attribution = {"source_uri": "https://eduscol.education.gouv.fr/doc.pdf",
                   "source_label": "Test", "source_updated_at": date,
                   "source_date_kind": "DATED_OFFICIAL_SNAPSHOT",
                   "licensor": "Ministère de l’Éducation nationale",
                   "licence_id": "ETALAB-2.0", "derivative_notice": f"snapshot du {date}"}
    candidate = build_text_candidate(pdf, sha, 2, attribution, packet)
    assert candidate.content is not None
    receipt = candidate.evidence
    receipt["candidate_relpath"] = f"candidates/{receipt['derivative_content_sha256']}.txt"
    assert receipt["pages"][1]["third_party_page_signal"] is True
    assert receipt["pages"][1]["selected_block_indices"] == []
    args = (pdf, packet, candidate.content, receipt["extraction_policy_sha256"],
            receipt["adjudication_policy_sha256"], receipt["generator_code_sha256"])
    assert _verify_text_derivative(receipt, *args) == []
    altered = copy.deepcopy(receipt)
    altered["pages"][1]["third_party_page_signal"] = False
    assert "DERIVATIVE_BLOCK_MAP_MISMATCH" in _verify_text_derivative(altered, *args)


def test_independent_derivative_regexes_match_sealed_extraction_policy():
    import check_delegated_student_rights_gate as gate

    root = Path(__file__).resolve().parents[2]
    policy = yaml.safe_load((root / "governance/student_public_rights/"
                                  "text_derivative_extraction_policy_v1.yml").read_bytes())
    rules = policy["classification"]
    for key, name in (
        ("publisher_name_regex", "_OFFICIAL_PUBLISHER"),
        ("first_party_copyright_regex", "_FIRST_PARTY_COPYRIGHT"),
        ("third_party_block_regex", "_DERIVATIVE_THIRD"),
        ("third_party_page_regex", "_DERIVATIVE_THIRD_PAGE"),
        ("long_quotation_regex", "_DERIVATIVE_LONG_QUOTE"),
    ):
        assert rules[key] == getattr(gate, name).pattern
    imprint = (rules["publisher_imprint_marker_regex"]
               + r"\s*[:\-]?\s*[^\n]{0,80}?"
               + rules["publisher_name_regex"])
    assert imprint == gate._PUBLISHER_IMPRINT.pattern


def test_public_candidate_manifest_rejects_empty_and_pdf_surface():
    template = {
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_MANIFEST_V1",
        "status": "PRE_REVIEW_NOT_PROMOTABLE", "inventory_sha256": H("1"),
        "rights_authority_sha256": H("2"),
        "text_derivative_extraction_policy_sha256": H("3"),
        "entries": [], "excluded_source_sha256": [SHA],
        "counts": {"source_pdfs": 1, "public_collections": 0,
                   "public_derivative_artifacts": 0, "public_placements": 0,
                   "public_derivative_segments": 0, "original_pdf_public_count": 0},
    }
    records = {SHA: _v2_record()}
    packets = {SHA: _packet_artifact()}
    errors, _ = _verify_candidate_manifest(
        template, records, packets, {}, H("1"), H("2"), H("3"),
        {"rag_nexus_test"}, required_collections=1,
    )
    assert "PUBLIC_RELEASE_EMPTY_COLLECTION" in errors


    derivative_sha = H("4")
    manifest = copy.deepcopy(template)
    manifest["entries"] = [{
        "source_content_sha256": SHA, "derivative_content_sha256": derivative_sha,
        "derivative_receipt_sha256": H("5"), "media_type": "application/pdf",
        "private_candidate_relpath": f"candidates/{derivative_sha}.txt",
        "collections": ["rag_nexus_test"], "citation": {},
        "source_disposition": "REPLACE_WITH_NEW_CONTENT",
        "derivative_disposition": "APPROVE_PUBLIC",
    }]
    manifest["excluded_source_sha256"] = []
    manifest["counts"].update(public_collections=1, public_derivative_artifacts=1,
                              public_placements=1, public_derivative_segments=1)
    records[SHA].update(source_disposition="REPLACE_WITH_NEW_CONTENT",
                        final_disposition="REPLACE_WITH_NEW_CONTENT",
                        derivative_disposition="APPROVE_PUBLIC",
                        derivative_content_sha256=derivative_sha,
                        derivative_receipt_sha256=H("5"))
    receipts = {SHA: {"pages": [{"review_groups": [{}]}], "source_attribution": {}}}
    errors, _ = _verify_candidate_manifest(
        manifest, records, packets, receipts, H("1"), H("2"), H("3"),
        {"rag_nexus_test"}, required_collections=1,
    )
    assert "PUBLIC_MANIFEST_PDF_EXPOSED" in errors
    manifest["entries"][0]["media_type"] = "text/plain; charset=utf-8"
    manifest["entries"][0]["public_pdf_download_url"] = "https://example.org/original.pdf"
    errors, _ = _verify_candidate_manifest(
        manifest, records, packets, receipts, H("1"), H("2"), H("3"),
        {"rag_nexus_test"}, required_collections=1,
    )
    assert "PUBLIC_MANIFEST_PDF_EXPOSED" in errors


def test_candidate_bindings_preserve_placement_multiplicity_and_receipt():
    derivative_sha = H("4")
    manifest = {"entries": [{
        "source_content_sha256": SHA,
        "derivative_content_sha256": derivative_sha,
        "derivative_receipt_sha256": H("5"),
    }]}
    packets = {SHA: {"placements": [
        {"collection": "rag_nexus_test"},
        {"collection": "rag_nexus_test"},
        {"collection": "rag_nexus_other"},
    ]}}
    placements, receipts = _candidate_derivative_bindings(manifest, packets)
    assert placements == {derivative_sha: {
        "rag_nexus_other": 1, "rag_nexus_test": 2,
    }}
    assert receipts == {derivative_sha: H("5")}


def test_public_candidate_manifest_rejects_omitted_approved_derivative():
    derivative_sha = H("4")
    manifest = {
        "kind": "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_MANIFEST_V1",
        "status": "PRE_REVIEW_NOT_PROMOTABLE", "inventory_sha256": H("1"),
        "rights_authority_sha256": H("2"),
        "text_derivative_extraction_policy_sha256": H("3"),
        "entries": [], "excluded_source_sha256": [SHA],
        "counts": {"source_pdfs": 1, "public_collections": 0,
                   "public_derivative_artifacts": 0, "public_placements": 0,
                   "public_derivative_segments": 0, "original_pdf_public_count": 0},
    }
    record = _v2_record()
    record.update(source_disposition="REPLACE_WITH_NEW_CONTENT",
                  final_disposition="REPLACE_WITH_NEW_CONTENT",
                  derivative_disposition="APPROVE_PUBLIC",
                  derivative_content_sha256=derivative_sha,
                  derivative_receipt_sha256=H("5"))
    errors, _ = _verify_candidate_manifest(
        manifest, {SHA: record}, {SHA: _packet_artifact()}, {},
        H("1"), H("2"), H("3"), {"rag_nexus_test"}, required_collections=1,
    )
    assert "PUBLIC_MANIFEST_APPROVAL_SET_MISMATCH" in errors


def test_source_provenance_does_not_convert_http403_into_rights(tmp_path: Path):
    record = _v2_record()
    packet = _packet_artifact()
    evidence = tmp_path / "docs/reports/go_live/student_rights_evidence"
    path = evidence / "provenance/checkpoints" / f"{SHA}.json"
    path.parent.mkdir(parents=True)
    checkpoint = {
        "kind": "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1",
        "content_sha256": SHA, "inventory_sha256": H("1"),
        "authority_yaml_sha256": H("2"),
        "source_checker_code_sha256": H("3"),
        "source_listing_url": packet["source_listing_url"],
        "checked_at_utc": UTC, "raw_http_status_diagnostic": 403,
        "source_provenance": {"status": "SOURCE_UNPROVEN", "matched_anchor": None,
                              "pdf_fetch": None, "source_updated_at": None,
                              "historical_capture": None,
                              "listing_capture_receipt_relpath": None,
                              "listing_capture_receipt_sha256": None,
                              "reason_codes": ["LISTING_CAPTURE_MISSING"]},
        "rights_basis_kind": "NONE", "rights_basis_status": "SOURCE_UNPROVEN",
    }
    checkpoint["checkpoint_sha256"] = hashlib.sha256(canonical_json_bytes(checkpoint)).hexdigest()
    raw = canonical_json_bytes(checkpoint)
    path.write_bytes(raw)
    record["source_receipt_sha256"] = hashlib.sha256(raw).hexdigest()
    errors, _ = _verify_source_provenance(
        record, packet, tmp_path, evidence, tmp_path, H("1"), H("2"), H("3"),
        fetch=lambda _uri, _limit: b"%PDF-1.4\n",
    )
    assert "SOURCE_PROVENANCE_NOT_EXACT" in errors


def test_exact_source_provenance_rechecks_anchor_pdf_and_snapshot_date(tmp_path: Path):
    from student_rights_source_provenance import build_listing_capture_receipt

    packet = _packet_artifact()
    packet["source_listing_url"] = "https://eduscol.education.gouv.fr/resource"
    pdf_url = "https://eduscol.education.gouv.fr/exact.pdf"
    pdf = b"%PDF-1.4\nsynthetic exact identity\n%%EOF\n"
    sha = hashlib.sha256(pdf).hexdigest()
    packet["content_sha256"] = sha
    record = _v2_record(sha)
    record.update(source_uri=pdf_url, byte_size=len(pdf))
    mirror_path = tmp_path / "mirror" / packet["source_path"]
    mirror_path.parent.mkdir(parents=True)
    mirror_path.write_bytes(pdf)
    evidence = tmp_path / "docs/reports/go_live/student_rights_evidence"
    listing_root = evidence / "provenance/listings"
    listing_root.mkdir(parents=True)
    html = f'<html><a href="{pdf_url}">Document exact</a></html>\n'.encode()
    text = b"Document exact\n"
    png = b"\x89PNG\r\n\x1a\nsynthetic"
    receipt = build_listing_capture_receipt(
        requested_url=packet["source_listing_url"], final_url=packet["source_listing_url"],
        http_status=200, observed_at_utc=UTC, normalized_html=html,
        extracted_text=text, screenshot=png, browser_version="test-chromium",
        playwright_version="test-playwright", capture_script_sha256=H("3"),
        normalized_html_file="listing.normalized.html",
        extracted_text_file="listing.extracted.txt", screenshot_file="listing.png",
    )
    for name, content in (("listing.normalized.html", html),
                          ("listing.extracted.txt", text), ("listing.png", png)):
        (listing_root / name).write_bytes(content)
    capture_path = listing_root / "listing.receipt.json"
    capture_path.write_bytes(canonical_json_bytes(receipt))
    capture_script = tmp_path / "scripts/go_live/capture_eduscol_source_listings.py"
    capture_script.parent.mkdir(parents=True)
    capture_script.write_text("# synthetic listing capture\n")
    receipt["capture_script_sha256"] = hashlib.sha256(capture_script.read_bytes()).hexdigest()
    capture_path.write_bytes(canonical_json_bytes(receipt))
    checkpoint = {
        "kind": "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1",
        "content_sha256": sha, "inventory_sha256": H("1"),
        "authority_yaml_sha256": H("2"),
        "source_checker_code_sha256": H("3"),
        "source_listing_url": packet["source_listing_url"],
        "checked_at_utc": UTC, "raw_http_status_diagnostic": 403,
        "source_provenance": {
            "status": "EXACT_CURRENT_SOURCE",
            "listing_capture_receipt_relpath": "provenance/listings/listing.receipt.json",
            "listing_capture_receipt_sha256": hashlib.sha256(capture_path.read_bytes()).hexdigest(),
            "matched_anchor": receipt["pdf_links"][0],
            "pdf_fetch": {"requested_url": pdf_url, "final_url": pdf_url,
                          "http_status": 200, "observed_at_utc": UTC,
                          "content_sha256": sha, "byte_count": len(pdf),
                          "etag": None, "last_modified": None},
            "source_updated_at": {"date": UTC, "kind": "DATED_OFFICIAL_SNAPSHOT",
                                  "evidence_ref": {"pdf_url": pdf_url,
                                                   "downloaded_sha256": sha,
                                                   "http_status": 200,
                                                   "listing_capture_receipt_sha256":
                                                   hashlib.sha256(capture_path.read_bytes()).hexdigest()}},
            "listing_observed_at_utc": UTC,
            "retraction_notice_associated": False,
            "currentness_status": "PASS",
            "currentness_observed_at_utc": UTC,
            "currentness_evidence_ref": {"pdf_url": pdf_url, "pdf_sha256": sha,
                                         "listing_capture_receipt_sha256":
                                         hashlib.sha256(capture_path.read_bytes()).hexdigest()},
            "revocation_status": "PASS_CURRENT_OFFICIAL_PUBLICATION",
            "revocation_observed_at_utc": UTC,
            "revocation_evidence_ref": {"pdf_url": pdf_url, "pdf_sha256": sha,
                                        "listing_capture_receipt_sha256":
                                        hashlib.sha256(capture_path.read_bytes()).hexdigest(),
                                        "notice_scan": "ANCHOR_NEIGHBORHOOD_V1"},
            "historical_capture": None, "reason_codes": [],
        },
        "rights_basis_kind": "SITEWIDE_DOWNLOAD_AUTHORITY",
        "rights_basis_status": "CANDIDATE_PENDING_FINAL_APPROVAL",
    }
    checkpoint_path = evidence / "provenance/checkpoints" / f"{sha}.json"
    checkpoint_path.parent.mkdir(parents=True)

    def reseal() -> None:
        checkpoint.pop("checkpoint_sha256", None)
        checkpoint["checkpoint_sha256"] = hashlib.sha256(canonical_json_bytes(checkpoint)).hexdigest()
        raw = canonical_json_bytes(checkpoint)
        checkpoint_path.write_bytes(raw)
        record["source_receipt_sha256"] = hashlib.sha256(raw).hexdigest()

    reseal()
    args = (record, packet, tmp_path, evidence, tmp_path / "mirror", H("1"), H("2"), H("3"))
    def fetch(_uri, _limit):
        return pdf
    assert _verify_source_provenance(*args, fetch=fetch)[0] == []
    checkpoint["source_provenance"]["source_updated_at"]["date"] = "2026-10-01T00:00:00Z"
    reseal()
    assert "SOURCE_SNAPSHOT_DATE_MISMATCH" in _verify_source_provenance(*args, fetch=fetch)[0]
    checkpoint["source_provenance"]["source_updated_at"]["date"] = UTC
    checkpoint["source_checker_code_sha256"] = H("4")
    reseal()
    assert "SOURCE_CHECKPOINT_BINDING" in _verify_source_provenance(*args, fetch=fetch)[0]
    checkpoint["source_checker_code_sha256"] = H("3")
    checkpoint["source_provenance"]["revocation_status"] = "PASS_CURRENT_OFFICIAL_PUBLICATION"
    checkpoint["source_provenance"]["retraction_notice_associated"] = True
    reseal()
    assert "SOURCE_REVOCATION_PROOF_MISMATCH" in _verify_source_provenance(*args, fetch=fetch)[0]
    checkpoint["source_provenance"]["retraction_notice_associated"] = False
    checkpoint["checked_at_utc"] = "2099-01-01T00:00:00Z"
    reseal()
    assert "SOURCE_CHECKPOINT_TIME_INVALID" in _verify_source_provenance(*args, fetch=fetch)[0]
    checkpoint["checked_at_utc"] = UTC
    original_listing = packet["source_listing_url"]
    packet["source_listing_url"] = pdf_url
    checkpoint["source_listing_url"] = pdf_url
    checkpoint["source_provenance"]["discovered_official_listing_url"] = original_listing
    reseal()
    assert _verify_source_provenance(*args, fetch=fetch)[0] == []
    checkpoint["source_provenance"]["discovered_official_listing_url"] = (
        "https://eduscol.education.gouv.fr.evil.org/resource"
    )
    reseal()
    assert "SOURCE_DISCOVERED_LISTING_INVALID" in _verify_source_provenance(
        *args, fetch=fetch)[0]


def test_official_listing_url_requires_https_exact_host():
    from check_delegated_student_rights_gate import _official_listing_url

    assert _official_listing_url("https://eduscol.education.gouv.fr/ressources")
    for url in ("http://eduscol.education.gouv.fr/ressources",
                "https://eduscol.education.gouv.fr.evil.org/ressources",
                "https://evil.org@eduscol.education.gouv.fr/ressources",
                "https://eduscol.education.gouv.fr:8443/ressources"):
        assert not _official_listing_url(url)


def test_excluded_derivative_receipt_cas_is_required_and_bound(tmp_path: Path):
    record = _v2_record()
    packet = _packet_artifact()
    evidence = tmp_path / "evidence"
    receipt = {
        "kind": "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1",
        "source_content_sha256": SHA, "source_packet_artifact_sha256":
            hashlib.sha256(_receipt_bytes(packet)).hexdigest(),
        "adjudication_policy_sha256": H("1"),
        "extraction_policy_sha256": H("2"), "generator_code_sha256": H("3"),
        "status": "EXCLUDE", "reason_codes": ["SOURCE_PROVENANCE_INSUFFICIENT"],
        "derivative_content_sha256": None, "candidate_relpath": None,
        "publication_authorized": False,
    }
    raw = _receipt_bytes(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    path = evidence / "derivative_receipts" / digest[:2] / f"{digest}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    checkpoint = {"kind": "NEXUS-STUDENT-DERIVATIVE-CHECKPOINT-V1",
                  "source_content_sha256": SHA, "derivative_content_sha256": None,
                  "derivative_receipt_sha256": digest, "status": "EXCLUDE",
                  "candidate_relpath": None}
    sidecar = evidence / "derivatives" / f"{SHA}.json"
    sidecar.parent.mkdir()
    sidecar.write_bytes(_receipt_bytes(checkpoint))
    record["derivative_receipt_sha256"] = digest
    assert _verify_derivative_receipt_cas(
        record, packet, evidence, H("1"), H("2"), H("3"))[0] == []
    receipt["candidate_relpath"] = "candidates/forged.txt"
    path.write_bytes(_receipt_bytes(receipt))
    assert "DERIVATIVE_RECEIPT_DIGEST" in _verify_derivative_receipt_cas(
        record, packet, evidence, H("1"), H("2"), H("3"))[0]

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
        "assembly_protocol": "NEXUS_REVIEW_TEXT_ASSEMBLY_V5",
        "text_assembly": [
            {
                "page_number": n,
                "assembly_protocol": "NEXUS_REVIEW_TEXT_ASSEMBLY_V5",
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


def _v2_record(sha: str = SHA) -> dict:
    record = _record(sha)
    record.update(
        record_kind="NEXUS_AUTOMATED_ARTIFACT_REVIEW_V2",
        source_disposition="EXCLUDE", final_disposition="EXCLUDE",
        derivative_disposition="EXCLUDE", derivative_content_sha256=None,
        derivative_receipt_sha256=None, rights_authority_id=None,
        rights_authority_sha256=None, rights_basis="NONE",
        reason_codes=["RIGHTS_NOT_PROVEN"],
    )
    return record


def test_v2_source_pdf_can_never_be_approved_public():
    record = _v2_record()
    record.update(source_disposition="APPROVE_PUBLIC", final_disposition="APPROVE_PUBLIC")
    assert "SOURCE_PDF_PUBLIC_FORBIDDEN" in _errors(record)


def test_v2_final_disposition_is_strict_alias_of_source():
    record = _v2_record()
    record["final_disposition"] = "REPLACE_WITH_NEW_CONTENT"
    assert "SOURCE_DISPOSITION_ALIAS_MISMATCH" in _errors(record)


def test_v2_source_replacement_requires_approved_derivative():
    record = _v2_record()
    record.update(source_disposition="REPLACE_WITH_NEW_CONTENT",
                  final_disposition="REPLACE_WITH_NEW_CONTENT",
                  derivative_disposition="EXCLUDE")
    assert "SOURCE_REPLACEMENT_WITHOUT_APPROVED_DERIVATIVE" in _errors(record)


def test_v2_derivative_cannot_approve_without_distinct_sha_and_receipt():
    record = _v2_record()
    record.update(source_disposition="REPLACE_WITH_NEW_CONTENT",
                  final_disposition="REPLACE_WITH_NEW_CONTENT",
                  derivative_disposition="APPROVE_PUBLIC")
    errors = _errors(record)
    assert "DERIVATIVE_IDENTITY_MISSING" in errors
    assert "DERIVATIVE_RIGHTS_UNPROVEN" in errors


def test_v2_exclusion_still_requires_source_and_derivative_cas_receipts():
    record = _v2_record()
    assert "SOURCE_RECEIPT_MISSING" in _errors(record)
    assert "DERIVATIVE_RECEIPT_MISSING" in _errors(record)


def test_v2_cftr_remains_excluded_even_with_derivative_claim():
    record = _v2_record(CFTR)
    record.update(derivative_disposition="APPROVE_PUBLIC")
    assert "CFTR_NOT_EXCLUDED" in _errors(record)


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


def test_v2_sheet_matches_source_and_derivative_decisions():
    record = _v2_record()
    record.update(source_disposition="REPLACE_WITH_NEW_CONTENT",
                  final_disposition="REPLACE_WITH_NEW_CONTENT",
                  derivative_disposition="APPROVE_PUBLIC",
                  derivative_content_sha256=H("4"),
                  derivative_receipt_sha256=H("5"),
                  rights_basis="SITEWIDE_DOWNLOAD_AUTHORITY",
                  rights_authority_id="EDUSCOL_ETALAB_2_0_SITEWIDE",
                  rights_authority_sha256=H("6"))
    content = render_decision_sheet([(record, _packet_artifact(), H("0"))])
    row = next(csv.DictReader(content.decode("utf-8").splitlines(), delimiter="\t"))
    assert row["rights_review"] == "PUBLIC_DERIVATIVE_RIGHTS_CONFIRMED"
    assert row["student_suitability"] == "STUDENT_DERIVATIVE_APPROVED"
    assert row["third_party_exception_review"] == "CLEARED_WITH_EVIDENCE"
    assert row["pii_recheck"] == "PASS_WITH_EVIDENCE"
    assert row["currentness_recheck"] == "PASS_WITH_EVIDENCE"
    assert row["revocation_recheck"] == "PASS_WITH_EVIDENCE"
    assert row["rights_evidence_ref"] == "https://eduscol.education.gouv.fr/4656/mentions-legales"
    assert row["student_public_disposition"] == "REPLACE_WITH_NEW_CONTENT"
    assert row["human_reviewer"] == ""


def test_v2_excluded_sheet_uses_explicit_none_in_terminal_authority_columns():
    record = _v2_record()
    content = render_decision_sheet([(record, _packet_artifact(), H("0"))])
    row = next(csv.DictReader(content.decode("utf-8").splitlines(), delimiter="\t"))
    assert row["rights_authority_id"] == "NONE"
    assert row["rights_authority_sha256"] == "NONE"
    assert not content.splitlines()[1].endswith(b"\t")


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


def test_parallel_rescans_check_every_pdf_and_preserve_failure_identity(tmp_path: Path):
    fitz = pytest.importorskip("fitz")
    from student_rights_pdf_scan import scan_pdf

    items = []
    for index in range(2):
        document = fitz.open()
        document.new_page().insert_text((50, 50), f"Document témoin {index}")
        data = document.tobytes()
        document.close()
        sha = hashlib.sha256(data).hexdigest()
        relpath = f"pdf/document-{index}.pdf"
        path = tmp_path / relpath
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        packet = {"content_sha256": sha, "page_count": 1, "source_path": relpath}
        record = {"pdf_scan_evidence": scan_pdf(path, sha, 1)}
        if index == 1:
            record["pdf_scan_evidence"]["pages"][0]["text_sha256"] = H("0")
        items.append((record, packet, H("1")))

    passed, errors = gate._rescan_all_pdfs(items, tmp_path)
    assert passed == 1
    assert errors == [f"PDF_RESCAN_MISMATCH:{items[1][1]['content_sha256'][:12]}"]


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
    forged_path.parent.mkdir(parents=True, exist_ok=True)
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
    forged_path.parent.mkdir(exist_ok=True)
    forged_path.write_bytes(raw)
    record["reviewer_a"]["evidence_refs"][0] = f"sha256:{forged_sha}"
    assert "REVIEWER_A_RECEIPT_REQUEST_MISMATCH" in _verify_review_receipts(
        record, tmp_path / "evidence", proofs
    )


def test_v5_xmp_image_and_residual_ocr_requests_reconstruct(
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
    assert facts["assembly_protocol"] == "NEXUS_REVIEW_TEXT_ASSEMBLY_V5"
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


def test_v5_page_render_pixel_cap_reconstructs_image_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    import math

    fitz = pytest.importorskip("fitz")
    import student_rights_pdf_scan as scanner
    import student_rights_reviewers as reviewers

    pdf = tmp_path / "pdf" / "large-page.pdf"
    pdf.parent.mkdir()
    document = fitz.open()
    page = document.new_page(width=1040, height=1090)
    page.insert_text((50, 50), "Document témoin graphique.")
    page.draw_rect(fitz.Rect(50, 70, 100, 100))
    pdf.write_bytes(document.tobytes())
    document.close()
    sha = hashlib.sha256(pdf.read_bytes()).hexdigest()
    monkeypatch.setattr(scanner, "_ocr_text", lambda _png: "")
    monkeypatch.setattr(reviewers, "_ocr_text", lambda _png: "")
    images: list[bytes] = []

    def transport(_model_id, _system_prompt, payload, _parameters, image_png):
        if image_png is not None:
            images.append(image_png)
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
    assert reviewed["assembly_protocol"] == "NEXUS_REVIEW_TEXT_ASSEMBLY_V5"
    assert images
    rendered = fitz.Pixmap(images[0])
    assert rendered.width * rendered.height <= 150_000
    assert 520 * 545 > 150_000
    record = {
        "content_sha256": sha, "page_count": 1,
        "assembly_protocol": reviewed["assembly_protocol"],
        "text_assembly": reviewed["text_assembly"],
        "reviewer_a": reviewed["reviewer_a"], "reviewer_b": reviewed["reviewer_b"],
    }
    packet = {"source_path": "pdf/large-page.pdf", "content_sha256": sha,
              "page_count": 1}
    proofs, errors = _reconstruct_review_requests(record, packet, tmp_path)
    assert errors == []
    assert _verify_review_receipts(record, tmp_path / "evidence", proofs) == []
    with fitz.open(pdf) as original:
        original_page = original[0]
        scale = min(0.5, math.sqrt(
            200_000 / (original_page.rect.width * original_page.rect.height)
        ))
        for _ in range(8):
            old_pixmap = original_page.get_pixmap(
                matrix=fitz.Matrix(scale, scale), alpha=False,
            )
            if old_pixmap.width * old_pixmap.height <= 200_000:
                break
            scale *= 0.995
        else:
            pytest.fail("Le rendu V4 témoin n'atteint pas son plafond")
        assert old_pixmap.width * old_pixmap.height > 150_000
        old_image_sha = hashlib.sha256(old_pixmap.tobytes("png")).hexdigest()
    assert old_image_sha != hashlib.sha256(images[0]).hexdigest()
    ref = record["reviewer_a"]["evidence_refs"][0]
    digest = ref.split(":", 1)[1]
    receipt_path = tmp_path / "evidence" / "receipts" / digest[:2] / f"{digest}.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["image_sha256"] = old_image_sha
    forged = _receipt_bytes(receipt)
    forged_digest = hashlib.sha256(forged).hexdigest()
    forged_path = (tmp_path / "evidence" / "receipts" / forged_digest[:2]
                   / f"{forged_digest}.json")
    forged_path.parent.mkdir(parents=True, exist_ok=True)
    forged_path.write_bytes(forged)
    record["reviewer_a"]["evidence_refs"][0] = f"sha256:{forged_digest}"
    assert "REVIEWER_A_RECEIPT_REQUEST_MISMATCH" in _verify_review_receipts(
        record, tmp_path / "evidence", proofs
    )


def test_gate_requires_source_mirror_for_existing_index(tmp_path: Path):
    index = tmp_path / DEFAULTS["index"]
    index.parent.mkdir(parents=True)
    index.write_text("{}\n")
    result = check_gate(tmp_path, expected_count=2)
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
