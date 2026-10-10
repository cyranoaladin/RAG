"""La provenance du PDF et la base de droits sont des preuves distinctes."""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

import student_rights_source_provenance as provenance  # noqa: E402
import capture_eduscol_source_listings as listing_capture  # noqa: E402
from student_rights_source_check import HTTPResponse  # noqa: E402


LISTING = "https://eduscol.education.gouv.fr/5793/programmes-et-ressources-en-francais-voie-gt"
PDF = "https://eduscol.education.gouv.fr/sites/default/files/document/exact.pdf"
PDF_BYTES = b"%PDF-1.4\nexact synthetic PDF\n%%EOF\n"
SHA = hashlib.sha256(PDF_BYTES).hexdigest()
UTC = "2026-10-10T05:45:00Z"


def _listing_capture(html: bytes) -> dict:
    return {
        "requested_url": LISTING,
        "final_url": LISTING,
        "http_status": 200,
        "observed_at_utc": UTC,
        "normalized_html_sha256": hashlib.sha256(html).hexdigest(),
    }


def _pdf_fetch(sha: str = SHA) -> dict:
    return {
        "requested_url": PDF,
        "final_url": PDF,
        "http_status": 200,
        "observed_at_utc": UTC,
        "content_sha256": sha,
        "byte_count": len(PDF_BYTES),
        "etag": '"pdf"',
        "last_modified": "Thu, 08 Oct 2026 10:30:00 GMT",
    }


def test_captured_official_link_and_exact_pdf_bytes_establish_current_source() -> None:
    html = f'<html><a href="{PDF}">Exact synthetic PDF</a></html>\n'.encode()

    result = provenance.classify_source_provenance(
        {"content_sha256": SHA, "source_listing_url": LISTING},
        listing_capture=_listing_capture(html),
        listing_html=html,
        pdf_fetches={PDF: _pdf_fetch()},
    )

    assert result["status"] == "EXACT_CURRENT_SOURCE"
    assert result["matched_anchor"] == {
        "href": PDF, "label": "Exact synthetic PDF", "occurrence_index": 0,
    }
    assert result["pdf_fetch"]["content_sha256"] == SHA


def test_raw_http_403_does_not_erase_positive_sitewide_basis_when_exact_link_is_proven() -> None:
    result = provenance.resolve_rights_basis_kind(
        source_status="EXACT_CURRENT_SOURCE",
        authority_status="CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL",
        raw_http_status_diagnostic=403,
        resource_link_proven=True,
        revocation_status="PASS_CURRENT_OFFICIAL_PUBLICATION",
    )

    assert result == {
        "rights_basis_kind": "SITEWIDE_DOWNLOAD_AUTHORITY",
        "rights_basis_status": "CANDIDATE_PENDING_FINAL_APPROVAL",
    }


def test_sitewide_authority_without_exact_resource_link_is_source_unproven() -> None:
    html = b"<html><a href='/unrelated'>Other</a></html>\n"

    source = provenance.classify_source_provenance(
        {"content_sha256": SHA, "source_listing_url": LISTING},
        listing_capture=_listing_capture(html),
        listing_html=html,
        pdf_fetches={},
    )
    rights = provenance.resolve_rights_basis_kind(
        source_status=source["status"],
        authority_status="CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL",
        raw_http_status_diagnostic=403,
        resource_link_proven=False,
    )

    assert source["status"] == "SOURCE_UNPROVEN"
    assert rights["rights_basis_kind"] == "NONE"
    assert rights["rights_basis_status"] == "SOURCE_UNPROVEN"


def test_direct_official_pdf_requires_exact_sha_and_http_200() -> None:
    artifact = {"content_sha256": SHA, "source_listing_url": PDF}

    exact = provenance.classify_source_provenance(
        artifact, listing_capture=None, listing_html=None,
        pdf_fetches={PDF: _pdf_fetch()},
    )
    mismatched = provenance.classify_source_provenance(
        artifact, listing_capture=None, listing_html=None,
        pdf_fetches={PDF: _pdf_fetch("0" * 64)},
    )

    assert exact["status"] == "EXACT_CURRENT_SOURCE"
    assert exact["matched_anchor"] is None
    assert mismatched["status"] == "SOURCE_UNPROVEN"


def test_direct_pdf_is_bound_to_discovered_official_listing_without_changing_acquisition_url() -> None:
    html = f'<a href="{PDF}">Current programme</a>\n'.encode()
    captures = {LISTING: {
        "receipt": _listing_capture(html), "html": html,
        "receipt_relpath": "provenance/listings/discovered.receipt.json",
        "receipt_sha256": "4" * 64,
    }}

    records = provenance.materialize_provenance_records(
        [{"content_sha256": SHA, "source_listing_url": PDF}],
        captures=captures, pdf_fetches={PDF: _pdf_fetch()},
        inventory_sha256="2" * 64, authority_yaml_sha256="3" * 64,
        authority_status="CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL",
        checked_at_utc=UTC, raw_http_status_by_sha={SHA: 403},
    )

    record = records[SHA]
    assert record["source_listing_url"] == PDF
    assert record["source_provenance"]["discovered_official_listing_url"] == LISTING
    assert record["source_provenance"]["matched_anchor"]["href"] == PDF
    assert record["source_provenance"]["listing_capture_receipt_sha256"] == "4" * 64
    assert record["source_provenance"]["revocation_status"] == "PASS_CURRENT_OFFICIAL_PUBLICATION"
    assert record["rights_basis_kind"] == "SITEWIDE_DOWNLOAD_AUTHORITY"


def test_direct_pdf_discovery_refuses_similar_pdf_url_and_retraction() -> None:
    other_pdf = PDF.replace("exact.pdf", "other.pdf")
    same_sha_other_url = dict(_pdf_fetch(), requested_url=other_pdf, final_url=other_pdf)
    wrong_html = f'<a href="{other_pdf}">Similar programme</a>\n'.encode()
    withdrawn_html = f'<li>Ressource retirée : <a href="{PDF}">Current programme</a></li>\n'.encode()
    for html, fetches, expected_anchor in (
        (wrong_html, {PDF: _pdf_fetch(), other_pdf: same_sha_other_url}, None),
        (withdrawn_html, {PDF: _pdf_fetch()}, PDF),
    ):
        captures = {LISTING: {
            "receipt": _listing_capture(html), "html": html,
            "receipt_relpath": "provenance/listings/discovered.receipt.json",
            "receipt_sha256": "4" * 64,
        }}
        record = provenance.materialize_provenance_records(
            [{"content_sha256": SHA, "source_listing_url": PDF}],
            captures=captures, pdf_fetches=fetches,
            inventory_sha256="2" * 64, authority_yaml_sha256="3" * 64,
            authority_status="CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL",
            checked_at_utc=UTC, raw_http_status_by_sha={},
        )[SHA]
        anchor = record["source_provenance"]["matched_anchor"]
        assert (anchor["href"] if anchor else None) == expected_anchor
        assert record["rights_basis_kind"] == "NONE"


def test_capture_url_set_can_add_only_official_html_pages() -> None:
    extra = "https://eduscol.education.gouv.fr/5781/programmes-et-ressources-en-droit"
    artifacts = [{"source_listing_url": LISTING}, {"source_listing_url": PDF}]

    assert listing_capture.listing_urls(artifacts, [extra]) == sorted([LISTING, extra])
    for invalid in (PDF, "https://example.com/other", LISTING):
        try:
            listing_capture.listing_urls(artifacts, [invalid])
        except ValueError:
            pass
        else:
            raise AssertionError("invalid extra listing accepted")


def test_tampered_listing_html_is_rejected_even_if_pdf_sha_matches() -> None:
    original = f'<a href="{PDF}">Original</a>\n'.encode()
    tampered = f'<a href="{PDF}">Tampered</a>\n'.encode()

    result = provenance.classify_source_provenance(
        {"content_sha256": SHA, "source_listing_url": LISTING},
        listing_capture=_listing_capture(original), listing_html=tampered,
        pdf_fetches={PDF: _pdf_fetch()},
    )

    assert result["status"] == "SOURCE_UNPROVEN"
    assert result["reason_codes"] == ["LISTING_CAPTURE_INVALID"]


def test_redirect_to_non_official_pdf_host_is_not_exact_source() -> None:
    html = f'<a href="{PDF}">Source</a>\n'.encode()
    fetch = _pdf_fetch()
    fetch["final_url"] = "https://example.com/exact.pdf"

    result = provenance.classify_source_provenance(
        {"content_sha256": SHA, "source_listing_url": LISTING},
        listing_capture=_listing_capture(html), listing_html=html,
        pdf_fetches={PDF: fetch},
    )

    assert result["status"] == "SOURCE_UNPROVEN"


def test_listing_capture_receipt_binds_browser_bytes_and_pdf_anchors() -> None:
    html = f'<html><a href="{PDF}">Exact synthetic PDF</a></html>\n'.encode()
    text = b"Exact synthetic PDF\n"
    screenshot = b"synthetic-png-bytes"

    receipt = provenance.build_listing_capture_receipt(
        requested_url=LISTING, final_url=LISTING, http_status=200,
        observed_at_utc=UTC, normalized_html=html, extracted_text=text,
        screenshot=screenshot, browser_version="151.0", playwright_version="1.62.0",
        capture_script_sha256="1" * 64,
        normalized_html_file="listing.html", extracted_text_file="listing.txt",
        screenshot_file="listing.png",
    )

    assert receipt["kind"] == "NEXUS_EDUSCOL_LISTING_BROWSER_CAPTURE_V1"
    assert receipt["normalized_html_sha256"] == hashlib.sha256(html).hexdigest()
    assert receipt["extracted_text_sha256"] == hashlib.sha256(text).hexdigest()
    assert receipt["screenshot_sha256"] == hashlib.sha256(screenshot).hexdigest()
    assert receipt["pdf_link_count"] == 1
    assert receipt["pdf_links"][0] == {
        "href": PDF, "label": "Exact synthetic PDF", "occurrence_index": 0,
    }


def test_listing_capture_receipt_rejects_offsite_redirect() -> None:
    try:
        provenance.build_listing_capture_receipt(
            requested_url=LISTING, final_url="https://example.com/page",
            http_status=200, observed_at_utc=UTC, normalized_html=b"<html></html>",
            extracted_text=b"", screenshot=b"png", browser_version="151.0",
            playwright_version="1.62.0", capture_script_sha256="1" * 64,
            normalized_html_file="listing.html", extracted_text_file="listing.txt",
            screenshot_file="listing.png",
        )
    except ValueError as error:
        assert str(error) == "LISTING_FINAL_URL_NOT_OFFICIAL"
    else:
        raise AssertionError("offsite redirect accepted")


def test_pdf_fetch_receipt_hashes_exact_bytes_without_storing_pdf() -> None:
    receipt = provenance.build_pdf_fetch_receipt(
        requested_url=PDF, final_url=PDF, http_status=200, body=PDF_BYTES,
        observed_at_utc=UTC, etag='"pdf"', last_modified="Thu, 08 Oct 2026 10:30:00 GMT",
    )

    assert receipt == _pdf_fetch()
    assert b"synthetic" not in str(receipt).encode()


def test_pdf_fetch_receipt_refuses_non_pdf_and_offsite_final_url() -> None:
    for final_url, body in ((PDF, b"<html>not PDF</html>"),
                            ("https://example.com/exact.pdf", PDF_BYTES)):
        try:
            provenance.build_pdf_fetch_receipt(
                requested_url=PDF, final_url=final_url, http_status=200, body=body,
                observed_at_utc=UTC, etag=None, last_modified=None,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("invalid PDF fetch accepted")


def test_checkpoint_internal_digest_excludes_only_its_own_hash() -> None:
    source = {"status": "EXACT_CURRENT_SOURCE", "matched_anchor": None,
              "pdf_fetch": _pdf_fetch(), "source_updated_at": None,
              "historical_capture": None, "reason_codes": []}
    record = provenance.make_provenance_checkpoint(
        artifact={"content_sha256": SHA, "source_listing_url": PDF},
        inventory_sha256="2" * 64, authority_yaml_sha256="3" * 64,
        checked_at_utc=UTC, raw_http_status_diagnostic=403,
        source_provenance=source, listing_capture_receipt_relpath=None,
        listing_capture_receipt_sha256=None,
        authority_status="CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL",
    )

    digest = record.pop("checkpoint_sha256")
    assert record["rights_basis_kind"] == "NONE"
    assert record["rights_basis_status"] == "RESOURCE_LINK_UNPROVEN"
    assert hashlib.sha256(provenance.canonical_json_bytes(record)).hexdigest() == digest
    record["checkpoint_sha256"] = digest
    assert hashlib.sha256(provenance.canonical_json_bytes(record)).hexdigest() != digest


def test_fetch_pdf_observation_hashes_response_and_rejects_offsite_redirect() -> None:
    good = provenance.fetch_pdf_observation(
        PDF, observed_at_utc=UTC,
        transport=lambda url, _limit: HTTPResponse(
            200, {"ETag": '"pdf"', "Last-Modified": "Thu, 08 Oct 2026 10:30:00 GMT"},
            PDF_BYTES,
        ),
    )
    bad = provenance.fetch_pdf_observation(
        PDF, observed_at_utc=UTC,
        transport=lambda url, _limit: HTTPResponse(
            302, {"Location": "https://example.com/not-official.pdf"}, b"",
        ),
    )

    assert good["content_sha256"] == SHA
    assert good["http_status"] == 200
    assert bad["content_sha256"] is None
    assert bad["reason_code"] == "PDF_FETCH_FAILED_CLOSED"


def test_sitewide_authority_capture_verification_is_bound_to_cas_bytes(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    authority = root / "governance/student_public_rights/authorities/eduscol_etalab_2_0_sitewide_20261010.yml"
    evidence = root / "docs/reports/go_live/student_rights_evidence/authorities"
    destination_authority = tmp_path / authority.relative_to(root)
    destination_authority.parent.mkdir(parents=True)
    shutil.copy2(authority, destination_authority)
    destination_evidence = tmp_path / evidence.relative_to(root)
    shutil.copytree(evidence, destination_evidence)
    capture_script = root / "scripts/go_live/capture_eduscol_sitewide_authority.js"
    destination_script = tmp_path / capture_script.relative_to(root)
    destination_script.parent.mkdir(parents=True)
    shutil.copy2(capture_script, destination_script)

    verified = provenance.verify_sitewide_authority(tmp_path, destination_authority)
    assert verified["status"] == "CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL"
    assert verified["authority_yaml_sha256"] == hashlib.sha256(authority.read_bytes()).hexdigest()

    html = destination_evidence / "eduscol_legal_notice.normalized.html"
    html.write_bytes(html.read_bytes() + b"\nTAMPERED\n")
    invalid = provenance.verify_sitewide_authority(tmp_path, destination_authority)
    assert invalid["status"] == "AUTHORITY_UNVERIFIED"


def test_materializer_yields_one_checkpoint_per_sha_without_pending() -> None:
    html = f'<a href="{PDF}">Exact synthetic PDF</a>\n'.encode()
    other_sha = "a" * 64
    artifacts = [
        {"content_sha256": SHA, "source_listing_url": LISTING},
        {"content_sha256": other_sha, "source_listing_url": LISTING},
    ]
    captures = {LISTING: {
        "receipt": _listing_capture(html), "html": html,
        "receipt_relpath": "provenance/listings/test.receipt.json",
        "receipt_sha256": "4" * 64,
    }}

    records = provenance.materialize_provenance_records(
        artifacts, captures=captures, pdf_fetches={PDF: _pdf_fetch()},
        inventory_sha256="2" * 64, authority_yaml_sha256="3" * 64,
        authority_status="CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL",
        checked_at_utc=UTC, raw_http_status_by_sha={SHA: 403, other_sha: 403},
    )

    assert len(records) == 2
    assert records[SHA]["source_provenance"]["status"] == "EXACT_CURRENT_SOURCE"
    assert records[SHA]["rights_basis_kind"] == "SITEWIDE_DOWNLOAD_AUTHORITY"
    assert records[SHA]["source_provenance"]["source_updated_at"]["kind"] == "DATED_OFFICIAL_SNAPSHOT"
    assert records[SHA]["source_provenance"]["currentness_status"] == "PASS"
    assert records[SHA]["source_provenance"]["currentness_evidence_ref"]["pdf_sha256"] == SHA
    assert records[SHA]["source_provenance"]["revocation_status"] == "PASS_CURRENT_OFFICIAL_PUBLICATION"
    assert records[other_sha]["source_provenance"]["status"] == "SOURCE_UNPROVEN"
    assert records[other_sha]["rights_basis_status"] == "SOURCE_UNPROVEN"
    assert not any("PENDING" == x["source_provenance"]["status"] for x in records.values())


def test_retraction_notice_adjacent_to_exact_link_blocks_revocation_pass() -> None:
    html = f'<li>Ressource retirée : <a href="{PDF}">Exact synthetic PDF</a></li>\n'.encode()
    captures = {LISTING: {
        "receipt": _listing_capture(html), "html": html,
        "receipt_relpath": "provenance/listings/test.receipt.json",
        "receipt_sha256": "4" * 64,
    }}
    records = provenance.materialize_provenance_records(
        [{"content_sha256": SHA, "source_listing_url": LISTING}],
        captures=captures, pdf_fetches={PDF: _pdf_fetch()},
        inventory_sha256="2" * 64, authority_yaml_sha256="3" * 64,
        authority_status="CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL",
        checked_at_utc=UTC, raw_http_status_by_sha={},
    )

    assert records[SHA]["source_provenance"]["status"] == "EXACT_CURRENT_SOURCE"
    assert records[SHA]["source_provenance"]["revocation_status"] == "UNVERIFIABLE"


def test_listing_capture_loader_rechecks_html_text_and_screenshot_hashes(tmp_path: Path) -> None:
    html = f'<a href="{PDF}">Exact synthetic PDF</a>\n'.encode()
    text = b"Exact synthetic PDF\n"
    screenshot = b"synthetic-png-bytes"
    script = tmp_path / "capture.py"
    script.write_text("# synthetic capture script\n")
    code_sha = hashlib.sha256(script.read_bytes()).hexdigest()
    receipt = provenance.build_listing_capture_receipt(
        requested_url=LISTING, final_url=LISTING, http_status=200,
        observed_at_utc=UTC, normalized_html=html, extracted_text=text,
        screenshot=screenshot, browser_version="151.0", playwright_version="1.62.0",
        capture_script_sha256=code_sha, normalized_html_file="page.html",
        extracted_text_file="page.txt", screenshot_file="page.png",
    )
    folder = tmp_path / "evidence"
    folder.mkdir()
    (folder / "page.html").write_bytes(html)
    (folder / "page.txt").write_bytes(text)
    (folder / "page.png").write_bytes(screenshot)
    (folder / "page.receipt.json").write_text(json.dumps(receipt) + "\n")

    loaded = provenance.load_listing_capture(
        tmp_path, folder / "page.receipt.json", script,
    )
    assert loaded["receipt"] == receipt
    assert loaded["html"] == html
    relative_loaded = provenance.load_listing_capture(
        tmp_path, Path("evidence/page.receipt.json"), script,
    )
    assert relative_loaded["receipt_sha256"] == loaded["receipt_sha256"]

    (folder / "page.png").write_bytes(b"tampered")
    try:
        provenance.load_listing_capture(tmp_path, folder / "page.receipt.json", script)
    except ValueError as error:
        assert str(error) == "LISTING_CAPTURE_BYTES_MISMATCH"
    else:
        raise AssertionError("tampered screenshot accepted")
