"""La source exacte est prouvée par ses octets, jamais par son domaine seul."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from student_rights_source_check import HTTPResponse, verify_source  # noqa: E402
import student_rights_source_check as source_checker  # noqa: E402

LISTING = "https://eduscol.education.gouv.fr/5793/ressources"
PDF = "https://eduscol.education.gouv.fr/sites/default/files/document/exact.pdf"
PDF_BYTES = b"%PDF-1.4\nsynthetic exact document\n%%EOF\n"
SHA = hashlib.sha256(PDF_BYTES).hexdigest()
UTC = "2026-10-09T20:00:00Z"
LEGAL = "https://eduscol.education.gouv.fr/4656/mentions-legales"
LICENSE = "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0"
LEGAL_HTML = (
    b"<html>documents proposes en telechargement licence etalab-2.0 "
    b"Sont exclus les contenus de tiers photographies textes</html>"
)
LICENSE_HTML = (
    b"<html>Licence Ouverte 2.0 reproduire extraire mentionner la paternite "
    b"date de la derniere mise a jour</html>"
)


class FakeTransport:
    def __init__(self, responses: dict[str, HTTPResponse | Exception]) -> None:
        self.responses = responses
        self.called: list[str] = []

    def __call__(self, url: str, _max_bytes: int) -> HTTPResponse:
        self.called.append(url)
        response = self.responses[url]
        if isinstance(response, Exception):
            raise response
        return response


def _artifact(url: str = LISTING, sha: str = SHA) -> dict[str, str]:
    return {"source_listing_url": url, "content_sha256": sha}


def _verified_identity() -> dict:
    return {
        "status": "VERIFIED",
        "source_identity_verified": True,
        "exact_bytes_match": True,
        "source_uri": LISTING,
        "source_http_status": 200,
        "source_final_url": LISTING,
        "source_etag": '"listing"',
        "source_last_modified": None,
        "pdf_http_status": 200,
        "pdf_etag": '"pdf"',
        "pdf_last_modified": "Thu, 08 Oct 2026 10:30:00 GMT",
        "exact_pdf_uri": PDF,
        "remote_pdf_sha256": SHA,
        "matched_pdf_url": PDF,
        "matched_pdf_sha256": SHA,
        "downloaded_sha256": SHA,
        "observed_at_utc": UTC,
        "source_last_updated_at_utc": "2026-10-08T10:30:00Z",
    }


def test_403_fails_closed_without_rights_or_document_identity() -> None:
    result = verify_source(
        _artifact(), transport=FakeTransport({LISTING: HTTPResponse(403, {}, b"")}),
        checked_at_utc=UTC,
    )

    assert result["source_http_status"] == 403
    assert result["source_identity_verified"] is False
    assert result["exact_document_url"] is None
    assert result["reason_code"] == "SOURCE_HTTP_403"


def test_thematic_html_without_pdf_link_cannot_match_by_official_domain() -> None:
    transport = FakeTransport(
        {LISTING: HTTPResponse(200, {"Content-Type": "text/html"}, b"<html>Official page</html>")}
    )

    result = verify_source(_artifact(), transport=transport, checked_at_utc=UTC)

    assert result["candidate_pdf_count"] == 0
    assert result["source_identity_verified"] is False
    assert result["reason_code"] == "SOURCE_NO_PDF_CANDIDATE"


def test_exact_pdf_candidate_is_bound_to_downloaded_bytes_and_pdf_header() -> None:
    html = b'<a href="/sites/default/files/document/exact.pdf">PDF</a>'
    transport = FakeTransport(
        {
            LISTING: HTTPResponse(200, {"ETag": '"listing"'}, html),
            PDF: HTTPResponse(
                200,
                {
                    "ETag": '"pdf-etag"',
                    "Last-Modified": "Thu, 08 Oct 2026 10:30:00 GMT",
                },
                PDF_BYTES,
            ),
        }
    )

    result = verify_source(_artifact(), transport=transport, checked_at_utc=UTC)

    assert result["checked_at_utc"] == UTC
    assert result["source_final_url"] == LISTING
    assert result["source_etag"] == '"listing"'
    assert result["source_last_modified"] is None
    assert result["candidate_pdf_count"] == 1
    assert result["source_identity_verified"] is True
    assert result["exact_bytes_match"] is True
    assert result["matched_pdf_url"] == PDF
    assert result["exact_document_url"] == PDF
    assert result["matched_pdf_sha256"] == SHA
    assert result["downloaded_sha256"] == SHA
    assert result["pdf_etag"] == '"pdf-etag"'
    assert result["last_updated_at"] == "2026-10-08T10:30:00Z"
    assert "rights_basis_verified" not in result
    assert "license_verified" not in result


def test_wrong_pdf_sha_is_not_accepted() -> None:
    wrong_pdf = b"%PDF-1.4\nwrong\n%%EOF\n"
    transport = FakeTransport({PDF: HTTPResponse(200, {}, wrong_pdf)})

    result = verify_source(_artifact(PDF), transport=transport, checked_at_utc=UTC)

    assert result["source_identity_verified"] is False
    assert result["downloaded_sha256"] == hashlib.sha256(wrong_pdf).hexdigest()
    assert result["exact_document_url"] is None
    assert result["reason_code"] == "SOURCE_PDF_SHA256_MISMATCH"


def test_redirect_to_another_host_is_rejected_before_request() -> None:
    transport = FakeTransport(
        {PDF: HTTPResponse(302, {"Location": "https://example.com/document.pdf"}, b"")}
    )

    result = verify_source(_artifact(PDF), transport=transport, checked_at_utc=UTC)

    assert result["source_identity_verified"] is False
    assert result["reason_code"] == "SOURCE_URL_NOT_ALLOWED"
    assert transport.called == [PDF]


def test_timeout_fails_closed_without_leaking_transport_error() -> None:
    transport = FakeTransport({PDF: TimeoutError("secret URL or token in error")})

    result = verify_source(_artifact(PDF), transport=transport, checked_at_utc=UTC)

    assert result["source_identity_verified"] is False
    assert result["reason_code"] == "SOURCE_FETCH_FAILED"
    assert "secret" not in str(result)


def test_direct_pdf_can_exceed_html_limit_without_exceeding_pdf_limit() -> None:
    large_pdf = b"%PDF-1.4\n" + b"x" * (2 * 1024 * 1024) + b"\n%%EOF"
    expected = hashlib.sha256(large_pdf).hexdigest()
    transport = FakeTransport({PDF: HTTPResponse(200, {}, large_pdf)})

    result = verify_source(_artifact(PDF, expected), transport=transport, checked_at_utc=UTC)

    assert result["source_identity_verified"] is True


def test_stops_after_first_exact_candidate_without_fetching_following_pdfs() -> None:
    later = "https://eduscol.education.gouv.fr/sites/default/files/document/later.pdf"
    html = (
        f'<a href="{PDF}">first</a><a href="{later}">later</a>'.encode("utf-8")
    )
    transport = FakeTransport(
        {
            LISTING: HTTPResponse(200, {}, html),
            PDF: HTTPResponse(200, {}, PDF_BYTES),
            later: AssertionError("unnecessary download"),
        }
    )

    result = verify_source(_artifact(), transport=transport, checked_at_utc=UTC)

    assert result["source_identity_verified"] is True
    assert transport.called == [LISTING, PDF]


def test_official_terms_prove_narrow_license_basis_but_not_currentness_or_revocation(
    tmp_path: Path,
) -> None:
    transport = FakeTransport(
        {
            LEGAL: HTTPResponse(200, {"Content-Type": "text/html; charset=utf-8"}, LEGAL_HTML),
            LICENSE: HTTPResponse(200, {"Content-Type": "text/html"}, LICENSE_HTML),
        }
    )

    result = source_checker.verify_source_rights(
        _artifact(), _verified_identity(), transport=transport, checked_at_utc=UTC,
        receipt_root=tmp_path,
    )

    assert result["rights_basis"] == "EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE"
    assert result["rights_evidence_uri"] == LEGAL
    assert result["license_or_terms_excerpt_hash"] == hashlib.sha256(LEGAL_HTML).hexdigest()
    assert result["evidence_pages"] == []
    assert result["currentness_status"] == "UNVERIFIABLE"
    assert result["revocation_status"] == "UNVERIFIABLE"
    assert result["reason_codes"] == ["CURRENTNESS_UNVERIFIABLE", "REVOCATION_UNVERIFIABLE"]
    assert result["source_verification"]["status"] == "VERIFIED"
    assert result["source_verification"]["remote_pdf_sha256"] == SHA
    assert result["source_verification"]["terms_sha256"] == hashlib.sha256(LEGAL_HTML).hexdigest()
    assert result["source_verification"]["revocation_evidence_uri"] is None
    assert result["source_receipt_sha256"] is not None
    assert transport.called == [LEGAL, LICENSE]


def test_positive_fetch_writes_metadata_only_cas_receipt(tmp_path: Path) -> None:
    transport = FakeTransport({
        LEGAL: HTTPResponse(200, {"Content-Type": "text/html", "ETag": '"legal"'}, LEGAL_HTML),
        LICENSE: HTTPResponse(200, {"Content-Type": "text/html"}, LICENSE_HTML),
    })
    result = source_checker.verify_source_rights(
        _artifact(), _verified_identity(), transport=transport,
        checked_at_utc=UTC, receipt_root=tmp_path,
    )

    digest = result["source_receipt_sha256"]
    assert isinstance(digest, str) and len(digest) == 64
    receipt_path = tmp_path / digest[:2] / f"{digest}.json"
    raw = receipt_path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == digest
    assert receipt_path.stat().st_mode & 0o077 == 0
    receipt = json.loads(raw)
    assert receipt["pdf"]["content_sha256"] == SHA
    assert receipt["legal_terms"]["body_sha256"] == hashlib.sha256(LEGAL_HTML).hexdigest()
    assert receipt["license"]["body_sha256"] == hashlib.sha256(LICENSE_HTML).hexdigest()
    assert receipt["rights_scope"] == "EDUSCOL_DOWNLOADS_EXCLUDING_THIRD_PARTY"
    assert receipt["transport_kind"] == "INJECTED_TEST_TRANSPORT"
    assert LEGAL_HTML not in raw and LICENSE_HTML not in raw


def test_batch_cache_keeps_production_transport_identity(tmp_path: Path, monkeypatch) -> None:
    fake = FakeTransport({
        LEGAL: HTTPResponse(200, {"Content-Type": "text/html"}, LEGAL_HTML),
        LICENSE: HTTPResponse(200, {"Content-Type": "text/html"}, LICENSE_HTML),
    })
    monkeypatch.setattr(source_checker, "_fetch_urllib", fake)
    cache = source_checker._CachedTransport(source_checker._fetch_urllib)
    result = source_checker.verify_source_rights(
        _artifact(), _verified_identity(), transport=cache,
        checked_at_utc=UTC, receipt_root=tmp_path,
    )
    digest = result["source_receipt_sha256"]
    receipt = json.loads((tmp_path / digest[:2] / f"{digest}.json").read_bytes())
    assert receipt["transport_kind"] == "URLLIB_HTTPS_GET_NO_REDIRECT_V1"


def test_failed_terms_fetch_writes_no_positive_receipt(tmp_path: Path) -> None:
    result = source_checker.verify_source_rights(
        _artifact(), _verified_identity(),
        transport=FakeTransport({LEGAL: HTTPResponse(403, {}, b"")}),
        checked_at_utc=UTC, receipt_root=tmp_path,
    )
    assert result["source_receipt_sha256"] is None
    assert not list(tmp_path.rglob("*.json"))


def test_batch_checkpoints_all_sources_with_memory_http_cache(tmp_path: Path) -> None:
    packet_path = tmp_path / "packet.json"
    shas = ["a" * 64, "b" * 64]
    packet_path.write_text(json.dumps({"artifacts": [
        {"content_sha256": sha, "source_listing_url": LISTING} for sha in shas
    ]}))
    transport = FakeTransport({LISTING: HTTPResponse(403, {}, b"")})
    output = tmp_path / "checkpoints"

    summary = source_checker.run_source_check_batch(
        packet_path, output, transport=transport, expected_count=2,
        checked_at_utc=UTC,
    )

    assert summary["inventory_count"] == 2
    assert summary["processed_count"] == 2
    assert summary["reused_count"] == 0
    assert summary["rights_basis_candidates"] == 0
    assert transport.called == [LISTING]
    for sha in shas:
        raw = (output / f"{sha}.json").read_bytes()
        checkpoint = json.loads(raw)
        digest = checkpoint.pop("checkpoint_sha256")
        assert hashlib.sha256(source_checker._canonical_json_bytes(checkpoint)).hexdigest() == digest
        assert checkpoint["source_identity"]["status"] == "UNVERIFIABLE"
        assert checkpoint["rights_check"]["rights_basis"] == "NONE"
        assert b"%PDF" not in raw and b"<html" not in raw


def test_batch_reuses_valid_checkpoint_and_rechecks_tampered_one(tmp_path: Path) -> None:
    packet_path = tmp_path / "packet.json"
    packet_path.write_text(json.dumps({"artifacts": [
        {"content_sha256": SHA, "source_listing_url": LISTING}
    ]}))
    output = tmp_path / "checkpoints"
    source_checker.run_source_check_batch(
        packet_path, output,
        transport=FakeTransport({LISTING: HTTPResponse(403, {}, b"")}),
        expected_count=1, checked_at_utc=UTC,
    )
    reused = source_checker.run_source_check_batch(
        packet_path, output,
        transport=FakeTransport({LISTING: AssertionError("must use checkpoint")}),
        expected_count=1, checked_at_utc=UTC,
    )
    assert reused["reused_count"] == 1
    path = output / f"{SHA}.json"
    checkpoint = json.loads(path.read_bytes())
    checkpoint["rights_check"]["rights_basis"] = "EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE"
    path.write_text(json.dumps(checkpoint))
    transport = FakeTransport({LISTING: HTTPResponse(403, {}, b"")})
    refreshed = source_checker.run_source_check_batch(
        packet_path, output, transport=transport, expected_count=1,
        checked_at_utc=UTC,
    )
    assert refreshed["processed_count"] == 1
    assert refreshed["reused_count"] == 0
    assert transport.called == [LISTING]
    assert json.loads(path.read_bytes())["rights_check"]["rights_basis"] == "NONE"


def test_terms_are_not_checked_when_exact_bytes_flag_is_false() -> None:
    identity = _verified_identity()
    identity["exact_bytes_match"] = False
    transport = FakeTransport(
        {
            LEGAL: HTTPResponse(200, {"Content-Type": "text/html"}, LEGAL_HTML),
            LICENSE: HTTPResponse(200, {"Content-Type": "text/html"}, LICENSE_HTML),
        }
    )

    result = source_checker.verify_source_rights(
        _artifact(), identity, transport=transport, checked_at_utc=UTC
    )

    assert result["rights_basis"] == "NONE"
    assert result["source_verification"]["status"] == "UNVERIFIABLE"
    assert transport.called == []


def test_explicit_license_withdrawal_on_official_page_cannot_pass_phrase_probe() -> None:
    withdrawn = LEGAL_HTML.replace(
        b"</html>", b" La licence etalab-2.0 ne s'applique plus aux documents telecharges.</html>"
    )
    transport = FakeTransport(
        {
            LEGAL: HTTPResponse(200, {"Content-Type": "text/html"}, withdrawn),
            LICENSE: HTTPResponse(200, {"Content-Type": "text/html"}, LICENSE_HTML),
        }
    )

    result = source_checker.verify_source_rights(
        _artifact(), _verified_identity(), transport=transport, checked_at_utc=UTC
    )

    assert result["rights_basis"] == "NONE"
    assert result["rights_evidence_uri"] is None
    assert result["source_verification"]["status"] == "VERIFIED"
    assert result["source_verification"]["terms_sha256"] is None


def test_conflicting_exact_pdf_identity_fields_cannot_produce_rights_basis() -> None:
    identity = _verified_identity()
    identity["matched_pdf_url"] = "https://eduscol.education.gouv.fr/other.pdf"
    transport = FakeTransport(
        {
            LEGAL: HTTPResponse(200, {"Content-Type": "text/html"}, LEGAL_HTML),
            LICENSE: HTTPResponse(200, {"Content-Type": "text/html"}, LICENSE_HTML),
        }
    )

    result = source_checker.verify_source_rights(
        _artifact(), identity, transport=transport, checked_at_utc=UTC
    )

    assert result["rights_basis"] == "NONE"
    assert transport.called == []


def test_wrong_mime_on_legal_terms_refuses_license_basis() -> None:
    transport = FakeTransport(
        {
            LEGAL: HTTPResponse(200, {"Content-Type": "application/pdf"}, LEGAL_HTML),
            LICENSE: HTTPResponse(200, {"Content-Type": "text/html"}, LICENSE_HTML),
        }
    )

    result = source_checker.verify_source_rights(
        _artifact(), _verified_identity(), transport=transport, checked_at_utc=UTC
    )

    assert result["rights_basis"] == "NONE"
    assert result["source_verification"]["terms_sha256"] is None


def test_403_on_official_legal_terms_fails_closed_without_fetching_license() -> None:
    transport = FakeTransport({LEGAL: HTTPResponse(403, {}, b"")})

    result = source_checker.verify_source_rights(
        _artifact(), _verified_identity(), transport=transport, checked_at_utc=UTC
    )

    assert result["rights_basis"] == "NONE"
    assert result["rights_evidence_uri"] is None
    # L'identité des octets a été vérifiée séparément : le 403 légal ne doit
    # ni effacer ce fait ni devenir une preuve de droits.
    assert result["source_verification"]["status"] == "VERIFIED"
    assert result["source_verification"]["remote_pdf_sha256"] == _artifact()["content_sha256"]
    assert result["source_verification"]["exact_pdf_uri"] == _verified_identity()["exact_pdf_uri"]
    assert result["source_verification"]["terms_sha256"] is None
    assert result["reason_codes"] == ["OFFICIAL_TERMS_UNVERIFIABLE"]
    assert transport.called == [LEGAL]
