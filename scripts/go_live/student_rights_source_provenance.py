"""Provenance des PDF Éduscol, séparée des droits et de leur décision finale."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path
from typing import Mapping

import yaml

from student_rights_source_check import _fetch_urllib, _get_with_redirects, _header
from student_rights_source_check import _terms_present


OFFICIAL_HOST = "eduscol.education.gouv.fr"
MAX_PDF_BYTES = 16 * 1024 * 1024


def _official_url(url: object) -> bool:
    if not isinstance(url, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname == OFFICIAL_HOST
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
        )
    except ValueError:
        return False


class _PdfAnchors(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.anchors: list[dict[str, object]] = []
        self._href: str | None = None
        self._label: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        raw = dict(attrs).get("href")
        url = urllib.parse.urljoin(self.base_url, raw) if raw else None
        self._href = (
            url if _official_url(url) and urllib.parse.urlsplit(url).path.lower().endswith(".pdf")
            else None
        )
        self._label = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._label.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            label = " ".join(" ".join(self._label).split())
            self.anchors.append(
                {"href": self._href, "label": label, "occurrence_index": len(self.anchors)}
            )
            self._href = None
            self._label = []


def _blank_provenance(reason: str) -> dict:
    return {
        "status": "SOURCE_UNPROVEN",
        "discovered_official_listing_url": None,
        "matched_anchor": None,
        "pdf_fetch": None,
        "source_updated_at": None,
        "historical_capture": None,
        "reason_codes": [reason],
    }


def _retraction_notice_near_link(html: bytes, pdf_url: str) -> bool:
    """Détecte les signaux de retrait voisins ; l'absence de lien reste inconnue."""
    source = html.decode("utf-8", errors="replace")
    needle = urllib.parse.urlsplit(pdf_url).path.rsplit("/", 1)[-1]
    position = source.find(needle)
    if position < 0:
        return True
    vicinity = source[max(0, position - 250):position + len(needle) + 250]
    plain = re.sub(r"<[^>]*>", " ", vicinity)
    normalized = unicodedata.normalize("NFKD", plain).lower()
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return any(signal in normalized for signal in (
        "retire", "revoque", "abroge", "supprime", "obsolete", "caduc",
        "ne plus utiliser", "remplace", "withdrawn", "removed",
    ))


def build_listing_capture_receipt(
    *,
    requested_url: str,
    final_url: str,
    http_status: int,
    observed_at_utc: str,
    normalized_html: bytes,
    extracted_text: bytes,
    screenshot: bytes,
    browser_version: str,
    playwright_version: str,
    capture_script_sha256: str,
    normalized_html_file: str,
    extracted_text_file: str,
    screenshot_file: str,
) -> dict:
    """Lie la capture navigateur et les ancres PDF sans inférer de droits."""
    if not _official_url(requested_url):
        raise ValueError("LISTING_REQUESTED_URL_NOT_OFFICIAL")
    if not _official_url(final_url):
        raise ValueError("LISTING_FINAL_URL_NOT_OFFICIAL")
    anchors = _PdfAnchors(final_url)
    anchors.feed(normalized_html.decode("utf-8", errors="replace"))
    return {
        "kind": "NEXUS_EDUSCOL_LISTING_BROWSER_CAPTURE_V1",
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": http_status,
        "observed_at_utc": observed_at_utc,
        "browser": "chromium",
        "browser_version": browser_version,
        "playwright_version": playwright_version,
        "capture_script_sha256": capture_script_sha256,
        "normalized_html_file": normalized_html_file,
        "normalized_html_sha256": hashlib.sha256(normalized_html).hexdigest(),
        "extracted_text_file": extracted_text_file,
        "extracted_text_sha256": hashlib.sha256(extracted_text).hexdigest(),
        "screenshot_file": screenshot_file,
        "screenshot_sha256": hashlib.sha256(screenshot).hexdigest(),
        "pdf_link_count": len(anchors.anchors),
        "pdf_links": anchors.anchors,
    }


def load_listing_capture(root: Path, receipt_path: Path, capture_script_path: Path) -> dict:
    """Relit les trois corps CAS et recalcule toutes les ancres du reçu."""
    if not receipt_path.is_absolute():
        receipt_path = root / receipt_path
    try:
        raw = receipt_path.read_bytes()
        receipt = json.loads(raw)
        if receipt.get("capture_script_sha256") != hashlib.sha256(
            capture_script_path.read_bytes()
        ).hexdigest():
            raise ValueError("LISTING_CAPTURE_CODE_MISMATCH")
        bodies = []
        for key in ("normalized_html_file", "extracted_text_file", "screenshot_file"):
            name = receipt[key]
            if not isinstance(name, str) or Path(name).name != name:
                raise ValueError("LISTING_CAPTURE_PATH_INVALID")
            bodies.append((receipt_path.parent / name).read_bytes())
        expected = build_listing_capture_receipt(
            requested_url=receipt["requested_url"], final_url=receipt["final_url"],
            http_status=receipt["http_status"], observed_at_utc=receipt["observed_at_utc"],
            normalized_html=bodies[0], extracted_text=bodies[1], screenshot=bodies[2],
            browser_version=receipt["browser_version"],
            playwright_version=receipt["playwright_version"],
            capture_script_sha256=receipt["capture_script_sha256"],
            normalized_html_file=receipt["normalized_html_file"],
            extracted_text_file=receipt["extracted_text_file"],
            screenshot_file=receipt["screenshot_file"],
        )
        if receipt != expected:
            raise ValueError("LISTING_CAPTURE_BYTES_MISMATCH")
        return {
            "receipt": receipt,
            "html": bodies[0],
            "receipt_relpath": receipt_path.relative_to(root).as_posix(),
            "receipt_sha256": hashlib.sha256(raw).hexdigest(),
        }
    except (OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("LISTING_CAPTURE_INVALID") from error


def build_pdf_fetch_receipt(
    *, requested_url: str, final_url: str, http_status: int, body: bytes,
    observed_at_utc: str, etag: str | None, last_modified: str | None,
) -> dict:
    """Conserve le SHA des octets PDF téléchargés, jamais les octets eux-mêmes."""
    if not _official_url(requested_url) or not _official_url(final_url):
        raise ValueError("PDF_URL_NOT_OFFICIAL")
    if http_status != 200 or not body.startswith(b"%PDF-") or len(body) > MAX_PDF_BYTES:
        raise ValueError("PDF_RESPONSE_NOT_VALID")
    return {
        "requested_url": requested_url,
        "final_url": final_url,
        "http_status": http_status,
        "observed_at_utc": observed_at_utc,
        "content_sha256": hashlib.sha256(body).hexdigest(),
        "byte_count": len(body),
        "etag": etag,
        "last_modified": last_modified,
    }


def fetch_pdf_observation(
    url: str, *, observed_at_utc: str,
    transport=None,
) -> dict:
    """GET HTTPS borné d'un PDF officiel, sans conserver ses octets en preuve."""
    failure = {
        "requested_url": url,
        "final_url": None,
        "http_status": None,
        "observed_at_utc": observed_at_utc,
        "content_sha256": None,
        "byte_count": None,
        "etag": None,
        "last_modified": None,
        "reason_code": "PDF_FETCH_FAILED_CLOSED",
    }
    try:
        if not _official_url(url):
            return failure
        final_url, response = _get_with_redirects(url, MAX_PDF_BYTES, transport or _fetch_urllib)
        receipt = build_pdf_fetch_receipt(
            requested_url=url, final_url=final_url, http_status=response.status,
            body=response.body, observed_at_utc=observed_at_utc,
            etag=_header(response.headers, "ETag"),
            last_modified=_header(response.headers, "Last-Modified"),
        )
        return receipt
    except Exception:
        return failure


def verify_sitewide_authority(root: Path, authority_path: Path) -> dict[str, str]:
    """Vérifie les octets de la notice/licence capturées, sans décider les tiers."""
    result = {"status": "AUTHORITY_UNVERIFIED", "authority_yaml_sha256": ""}
    try:
        authority_bytes = authority_path.read_bytes()
        result["authority_yaml_sha256"] = hashlib.sha256(authority_bytes).hexdigest()
        authority = yaml.safe_load(authority_bytes)
        if (
            authority.get("authority_kind") != "SITEWIDE_DOWNLOAD_AUTHORITY"
            or authority.get("status") != "SEALED_PENDING_FINAL_EXACT_HEAD_APPROVAL"
            or authority.get("authority_id") != "EDUSCOL_ETALAB_2_0_SITEWIDE"
            or authority.get("resource_binding_required") is not True
            or authority.get("full_pdf_redistribution_allowed_by_product") is not False
            or not authority.get("excluded_components")
        ):
            return result
        capture = authority["browser_capture"]
        script_path = root / capture["capture_script"]
        if hashlib.sha256(script_path.read_bytes()).hexdigest() != capture["capture_script_sha256"]:
            return result
        bodies = []
        for key, expected_url in (
            ("legal_notice", authority["legal_notice_url"]),
            ("etalab_2_0_licence", authority["licence_url"]),
        ):
            entry = capture[key]
            receipt_path = root / entry["receipt"]
            raw = receipt_path.read_bytes()
            if hashlib.sha256(raw).hexdigest() != entry["receipt_sha256"]:
                return result
            receipt = json.loads(raw)
            if (
                receipt.get("kind") != "NEXUS_EDUSCOL_SITEWIDE_BROWSER_CAPTURE_V1"
                or receipt.get("requested_url") != expected_url
                or receipt.get("final_url") != expected_url
                or receipt.get("http_status") != 200
                or receipt.get("observed_at_utc") != entry["observed_at_utc"]
                or receipt.get("capture_script_sha256") != capture["capture_script_sha256"]
                or receipt.get("browser") != "chromium"
                or receipt.get("browser_version") != capture["chromium_version"]
                or receipt.get("playwright_version") != capture["capture_tool_version"]
            ):
                return result
            for receipt_key, digest_key, entry_key in (
                ("normalized_html_file", "normalized_html_sha256", "normalized_html_sha256"),
                ("extracted_text_file", "extracted_text_sha256", "extracted_text_sha256"),
                ("screenshot_file", "screenshot_sha256", "screenshot_sha256"),
            ):
                filename = receipt[receipt_key]
                if not isinstance(filename, str) or Path(filename).name != filename:
                    return result
                body = (receipt_path.parent / filename).read_bytes()
                digest = hashlib.sha256(body).hexdigest()
                if digest != receipt[digest_key] or digest != entry[entry_key]:
                    return result
                if receipt_key == "normalized_html_file":
                    bodies.append(body)
        if len(bodies) != 2 or not _terms_present(bodies[0], bodies[1]):
            return result
        result["status"] = "CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL"
        return result
    except (OSError, ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
        return result


def _exact_pdf_fetch(fetch: Mapping[str, object] | None, url: str, expected: str) -> bool:
    return isinstance(fetch, Mapping) and all(
        (
            fetch.get("requested_url") == url,
            _official_url(fetch.get("final_url")),
            fetch.get("http_status") == 200,
            isinstance(fetch.get("byte_count"), int),
            isinstance(fetch.get("byte_count"), int) and fetch["byte_count"] > 0,
            fetch.get("content_sha256") == expected,
        )
    )


def classify_source_provenance(
    artifact: Mapping[str, object],
    *,
    listing_capture: Mapping[str, object] | None,
    listing_html: bytes | None,
    pdf_fetches: Mapping[str, Mapping[str, object]],
) -> dict:
    """Classe le lien observé, sans en déduire une autorisation de publication.

    Le caller fournit les réponses PDF qu'il vient de hacher ; le gate relit les
    captures et refait le GET indépendamment avant toute approbation positive.
    """
    source = artifact.get("source_listing_url")
    expected = artifact.get("content_sha256")
    if not _official_url(source) or not isinstance(expected, str) or len(expected) != 64:
        return _blank_provenance("SOURCE_INPUT_INVALID")
    if urllib.parse.urlsplit(str(source)).path.lower().endswith(".pdf"):
        fetch = pdf_fetches.get(str(source))
        if _exact_pdf_fetch(fetch, str(source), expected):
            assert fetch is not None
            discovered = None
            anchor = None
            if isinstance(listing_capture, Mapping) and isinstance(listing_html, bytes):
                candidate_url = listing_capture.get("requested_url")
                if (
                    _official_url(candidate_url)
                    and not urllib.parse.urlsplit(str(candidate_url)).path.lower().endswith(".pdf")
                    and _official_url(listing_capture.get("final_url"))
                    and listing_capture.get("http_status") == 200
                    and listing_capture.get("normalized_html_sha256")
                    == hashlib.sha256(listing_html).hexdigest()
                ):
                    parser = _PdfAnchors(str(listing_capture["final_url"]))
                    parser.feed(listing_html.decode("utf-8", errors="replace"))
                    anchor = next(
                        (item for item in parser.anchors if item["href"] == source), None
                    )
                    if anchor is not None:
                        discovered = str(candidate_url)
            return {
                "status": "EXACT_CURRENT_SOURCE",
                "discovered_official_listing_url": discovered,
                "matched_anchor": anchor,
                "pdf_fetch": dict(fetch),
                "source_updated_at": fetch.get("source_updated_at"),
                "historical_capture": None,
                "reason_codes": [],
            }
        return _blank_provenance("DIRECT_PDF_NOT_EXACT")
    if not isinstance(listing_capture, Mapping) or not isinstance(listing_html, bytes):
        return _blank_provenance("LISTING_CAPTURE_MISSING")
    if (
        listing_capture.get("requested_url") != source
        or not _official_url(listing_capture.get("final_url"))
        or listing_capture.get("http_status") != 200
        or listing_capture.get("normalized_html_sha256") != hashlib.sha256(listing_html).hexdigest()
    ):
        return _blank_provenance("LISTING_CAPTURE_INVALID")
    parser = _PdfAnchors(str(listing_capture["final_url"]))
    parser.feed(listing_html.decode("utf-8", errors="replace"))
    for anchor in parser.anchors:
        url = str(anchor["href"])
        fetch = pdf_fetches.get(url)
        if not isinstance(fetch, Mapping):
            continue
        if _exact_pdf_fetch(fetch, url, expected):
            return {
                "status": "EXACT_CURRENT_SOURCE",
                "discovered_official_listing_url": None,
                "matched_anchor": anchor,
                "pdf_fetch": dict(fetch),
                "source_updated_at": fetch.get("source_updated_at"),
                "historical_capture": None,
                "reason_codes": [],
            }
    return _blank_provenance("NO_EXACT_CURRENT_PDF_LINK")


def resolve_rights_basis_kind(
    *, source_status: str, authority_status: str, raw_http_status_diagnostic: int | None,
    resource_link_proven: bool, revocation_status: str = "UNVERIFIABLE",
) -> dict[str, str]:
    """Un 403 de transport historique ne vaut jamais verdict juridique."""
    del raw_http_status_diagnostic
    if (
        source_status == "EXACT_CURRENT_SOURCE"
        and authority_status == "CAPTURE_VERIFIED_PENDING_FINAL_APPROVAL"
        and resource_link_proven
        and revocation_status == "PASS_CURRENT_OFFICIAL_PUBLICATION"
    ):
        return {
            "rights_basis_kind": "SITEWIDE_DOWNLOAD_AUTHORITY",
            "rights_basis_status": "CANDIDATE_PENDING_FINAL_APPROVAL",
        }
    return {
        "rights_basis_kind": "NONE",
        "rights_basis_status": (
            "SOURCE_UNPROVEN" if source_status == "SOURCE_UNPROVEN" else
            "RESOURCE_LINK_UNPROVEN" if not resource_link_proven else
            "CURRENT_PUBLICATION_UNVERIFIABLE"
            if revocation_status != "PASS_CURRENT_OFFICIAL_PUBLICATION" else
            "AUTHORITY_UNVERIFIED"
        ),
    }


def canonical_json_bytes(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n").encode("utf-8")


def make_provenance_checkpoint(
    *, artifact: Mapping[str, object], inventory_sha256: str,
    authority_yaml_sha256: str, checked_at_utc: str,
    raw_http_status_diagnostic: int | None, source_provenance: Mapping[str, object],
    listing_capture_receipt_relpath: str | None,
    listing_capture_receipt_sha256: str | None, authority_status: str,
) -> dict:
    """Scelle un constat par SHA sans transformer une base candidate en décision."""
    source = dict(source_provenance)
    source["listing_capture_receipt_relpath"] = listing_capture_receipt_relpath
    source["listing_capture_receipt_sha256"] = listing_capture_receipt_sha256
    fetch = source.get("pdf_fetch")
    if source.get("status") == "EXACT_CURRENT_SOURCE" and isinstance(fetch, Mapping):
        if source.get("source_updated_at") is None:
            source["source_updated_at"] = {
                "date": fetch.get("observed_at_utc"),
                "kind": "DATED_OFFICIAL_SNAPSHOT",
                "evidence_ref": {
                    "pdf_url": fetch.get("final_url"),
                    "downloaded_sha256": fetch.get("content_sha256"),
                    "http_status": fetch.get("http_status"),
                    "listing_capture_receipt_sha256": listing_capture_receipt_sha256,
                },
            }
        source["currentness_status"] = "PASS"
        source["currentness_observed_at_utc"] = fetch.get("observed_at_utc")
        source["currentness_evidence_ref"] = {
            "pdf_url": fetch.get("final_url"),
            "pdf_sha256": fetch.get("content_sha256"),
            "listing_capture_receipt_sha256": listing_capture_receipt_sha256,
        }
        has_listing = (
            listing_capture_receipt_sha256 is not None
            and source.get("matched_anchor") is not None
        )
        no_retraction = source.get("retraction_notice_associated") is False
        if has_listing and no_retraction:
            source["revocation_status"] = "PASS_CURRENT_OFFICIAL_PUBLICATION"
            source["revocation_evidence_ref"] = {
                "listing_capture_receipt_sha256": listing_capture_receipt_sha256,
                "pdf_url": fetch.get("final_url"),
                "pdf_sha256": fetch.get("content_sha256"),
                "notice_scan": "ANCHOR_NEIGHBORHOOD_V1",
            }
            source["revocation_observed_at_utc"] = source.get("listing_observed_at_utc")
        else:
            source["revocation_status"] = "UNVERIFIABLE"
            source["revocation_evidence_ref"] = None
            source["revocation_observed_at_utc"] = None
    else:
        source.update(
            currentness_status="UNVERIFIABLE", currentness_evidence_ref=None,
            currentness_observed_at_utc=None, revocation_status="UNVERIFIABLE",
            revocation_evidence_ref=None, revocation_observed_at_utc=None,
        )
    rights = resolve_rights_basis_kind(
        source_status=str(source.get("status")), authority_status=authority_status,
        raw_http_status_diagnostic=raw_http_status_diagnostic,
        resource_link_proven=(
            listing_capture_receipt_sha256 is not None
            and source.get("matched_anchor") is not None
        ),
        revocation_status=str(source.get("revocation_status")),
    )
    record = {
        "kind": "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1",
        "content_sha256": artifact["content_sha256"],
        "inventory_sha256": inventory_sha256,
        "authority_yaml_sha256": authority_yaml_sha256,
        "source_checker_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "source_listing_url": artifact["source_listing_url"],
        "checked_at_utc": checked_at_utc,
        "raw_http_status_diagnostic": raw_http_status_diagnostic,
        "source_provenance": source,
        **rights,
    }
    record["checkpoint_sha256"] = hashlib.sha256(canonical_json_bytes(record)).hexdigest()
    return record


def materialize_provenance_records(
    artifacts: list[dict], *, captures: Mapping[str, Mapping[str, object]],
    pdf_fetches: Mapping[str, Mapping[str, object]], inventory_sha256: str,
    authority_yaml_sha256: str, authority_status: str, checked_at_utc: str,
    raw_http_status_by_sha: Mapping[str, int | None],
) -> dict[str, dict]:
    """Produit un constat final pour chaque SHA, y compris les sources inconnues."""
    records: dict[str, dict] = {}
    for artifact in artifacts:
        sha = artifact.get("content_sha256")
        uri = artifact.get("source_listing_url")
        if not isinstance(sha, str) or len(sha) != 64 or sha in records:
            raise ValueError("SOURCE_INVENTORY_SHA_INVALID_OR_DUPLICATE")
        if not isinstance(uri, str):
            raise ValueError("SOURCE_INVENTORY_URI_INVALID")
        capture = captures.get(uri)
        if urllib.parse.urlsplit(uri).path.lower().endswith(".pdf"):
            for candidate_uri, candidate in sorted(captures.items()):
                candidate_html = candidate.get("html")
                candidate_receipt = candidate.get("receipt")
                if not isinstance(candidate_html, bytes) or not isinstance(candidate_receipt, Mapping):
                    continue
                if not _official_url(candidate_uri):
                    continue
                parser = _PdfAnchors(str(candidate_receipt.get("final_url", candidate_uri)))
                parser.feed(candidate_html.decode("utf-8", errors="replace"))
                if any(anchor["href"] == uri for anchor in parser.anchors):
                    capture = candidate
                    break
        receipt = capture.get("receipt") if isinstance(capture, Mapping) else None
        html = capture.get("html") if isinstance(capture, Mapping) else None
        source = classify_source_provenance(
            artifact, listing_capture=receipt if isinstance(receipt, Mapping) else None,
            listing_html=html if isinstance(html, bytes) else None,
            pdf_fetches=pdf_fetches,
        )
        if (
            source["status"] == "EXACT_CURRENT_SOURCE"
            and isinstance(html, bytes)
            and isinstance(source.get("matched_anchor"), Mapping)
        ):
            source["listing_observed_at_utc"] = receipt.get("observed_at_utc")
            source["retraction_notice_associated"] = _retraction_notice_near_link(
                html, str(source["matched_anchor"]["href"]),
            )
        receipt_path = capture.get("receipt_relpath") if isinstance(capture, Mapping) else None
        receipt_sha = capture.get("receipt_sha256") if isinstance(capture, Mapping) else None
        records[sha] = make_provenance_checkpoint(
            artifact=artifact, inventory_sha256=inventory_sha256,
            authority_yaml_sha256=authority_yaml_sha256,
            checked_at_utc=checked_at_utc,
            raw_http_status_diagnostic=raw_http_status_by_sha.get(sha),
            source_provenance=source,
            listing_capture_receipt_relpath=(
                str(receipt_path) if isinstance(receipt_path, str) else None
            ),
            listing_capture_receipt_sha256=(
                str(receipt_sha) if isinstance(receipt_sha, str) else None
            ),
            authority_status=authority_status,
        )
    return records
