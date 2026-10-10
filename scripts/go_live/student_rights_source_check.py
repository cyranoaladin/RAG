"""Vérification d'identité documentaire distante, distincte des droits.

Un domaine officiel ou une page thématique accessible ne prouvent ni l'identité
du PDF local ni le droit de réutiliser ses extraits pour des élèves.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import sys
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Mapping

ALLOWED_HOST = "eduscol.education.gouv.fr"
MAX_HTML_BYTES = 2 * 1024 * 1024
MAX_PDF_BYTES = 16 * 1024 * 1024
MAX_REDIRECTS = 5
MAX_CANDIDATES = 100
EDUSCOL_LEGAL_URI = "https://eduscol.education.gouv.fr/4656/mentions-legales"
ETALAB_LICENSE_URI = "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0"
SOURCE_RIGHTS_RECEIPT_KIND = "NEXUS-STUDENT-SOURCE-RIGHTS-RECEIPT-V1"
SOURCE_CHECKPOINT_KIND = "NEXUS-STUDENT-SOURCE-CHECKPOINT-V1"
HTTP_CACHE_MAX_BYTES = 32 * 1024 * 1024
CHECKPOINT_MAX_AGE = timedelta(hours=24)


@dataclass(frozen=True)
class HTTPResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class SourceCheckFailure(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        return None


def _fetch_urllib(url: str, max_bytes: int) -> HTTPResponse:
    opener = urllib.request.build_opener(_NoRedirect)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "NexusSourceIdentityVerifier/1", "Accept-Encoding": "identity"},
    )
    try:
        response = opener.open(request, timeout=20)
    except urllib.error.HTTPError as exc:
        response = exc
    try:
        headers = dict(response.headers.items())
        content_length = _header(headers, "Content-Length")
        if content_length is not None and content_length.isdecimal() and int(content_length) > max_bytes:
            raise SourceCheckFailure("SOURCE_RESPONSE_TOO_LARGE")
        if response.status in (301, 302, 303, 307, 308) or response.status >= 400:
            body = b""
        else:
            body = response.read(max_bytes + 1)
            if len(body) > max_bytes:
                raise SourceCheckFailure("SOURCE_RESPONSE_TOO_LARGE")
        return HTTPResponse(response.status, headers, body)
    finally:
        response.close()


def _header(headers: Mapping[str, str], name: str) -> str | None:
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None


def _validate_url(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        port = parsed.port
    except ValueError:
        raise SourceCheckFailure("SOURCE_URL_NOT_ALLOWED") from None
    if (
        parsed.scheme != "https"
        or parsed.hostname != ALLOWED_HOST
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
    ):
        raise SourceCheckFailure("SOURCE_URL_NOT_ALLOWED")
    return urllib.parse.urldefrag(url).url


def _get_with_redirects(
    url: str, max_bytes: int, transport: Callable[[str, int], HTTPResponse]
) -> tuple[str, HTTPResponse]:
    current = _validate_url(url)
    for _ in range(MAX_REDIRECTS + 1):
        response = transport(current, max_bytes)
        if len(response.body) > max_bytes:
            raise SourceCheckFailure("SOURCE_RESPONSE_TOO_LARGE")
        if response.status not in (301, 302, 303, 307, 308):
            return current, response
        location = _header(response.headers, "Location")
        if not location:
            raise SourceCheckFailure("SOURCE_REDIRECT_WITHOUT_LOCATION")
        current = _validate_url(urllib.parse.urljoin(current, location))
    raise SourceCheckFailure("SOURCE_TOO_MANY_REDIRECTS")


class _PdfLinks(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        candidate = attributes.get("href") if tag == "a" else attributes.get("src")
        if tag == "object":
            candidate = attributes.get("data")
        if not candidate:
            return
        url = urllib.parse.urljoin(self.base_url, candidate)
        if urllib.parse.urlsplit(url).path.lower().endswith(".pdf"):
            try:
                self.links.append(_validate_url(url))
            except SourceCheckFailure:
                return


def _last_modified_utc(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
        if parsed.tzinfo is None or not math.isfinite(parsed.timestamp()):
            return None
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    except (TypeError, ValueError, OverflowError):
        return None


def verify_source(
    artifact: dict,
    transport: Callable[[str, int], HTTPResponse] | None = None,
    checked_at_utc: str | None = None,
) -> dict:
    """Tente de relier un PDF distant aux octets exacts de l'inventaire.

    Les champs `status=VERIFIED` et `source_identity_verified=True` ne portent
    que sur l'identité distante. Termes, licence et révocation restent à établir
    par un contrôle distinct et ne sont jamais présumés ici.
    """
    source_uri = artifact["source_listing_url"]
    expected_sha256 = artifact["content_sha256"]
    observed = checked_at_utc or datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    result = {
        "status": "UNVERIFIABLE",
        "source_uri": source_uri,
        "listing_uri": source_uri,
        "checked_at_utc": observed,
        "observed_at_utc": observed,
        "source_http_status": None,
        "source_final_url": None,
        "source_etag": None,
        "source_last_modified": None,
        "candidate_pdf_count": 0,
        "matched_pdf_url": None,
        "matched_pdf_sha256": None,
        "pdf_http_status": None,
        "pdf_etag": None,
        "pdf_last_modified": None,
        "exact_document_url": None,
        "downloaded_sha256": None,
        "last_updated_at": None,
        "exact_pdf_uri": None,
        "remote_pdf_sha256": None,
        "source_last_updated_at_utc": None,
        "exact_bytes_match": False,
        "source_identity_verified": False,
        "reason_code": None,
    }
    get = transport or _fetch_urllib
    try:
        source_limit = (
            MAX_PDF_BYTES
            if urllib.parse.urlsplit(source_uri).path.lower().endswith(".pdf")
            else MAX_HTML_BYTES
        )
        source_final, source_response = _get_with_redirects(source_uri, source_limit, get)
        result.update(
            source_http_status=source_response.status,
            source_final_url=source_final,
            source_etag=_header(source_response.headers, "ETag"),
            source_last_modified=_header(source_response.headers, "Last-Modified"),
        )
        if source_response.status != 200:
            raise SourceCheckFailure(f"SOURCE_HTTP_{source_response.status}")

        if source_response.body.startswith(b"%PDF-"):
            urls = [source_final]
            direct_response = source_response
        else:
            links = _PdfLinks(source_final)
            links.feed(source_response.body.decode("utf-8", errors="replace"))
            urls = list(dict.fromkeys(links.links))
            if len(urls) > MAX_CANDIDATES:
                raise SourceCheckFailure("SOURCE_CANDIDATE_LIMIT_EXCEEDED")
            result["candidate_pdf_count"] = len(urls)
            if not urls:
                raise SourceCheckFailure("SOURCE_NO_PDF_CANDIDATE")
            direct_response = None

        if direct_response is not None:
            result["candidate_pdf_count"] = 1
        mismatch = False
        for url in urls:
            if direct_response is not None:
                pdf_url, pdf_response = url, direct_response
            else:
                try:
                    pdf_url, pdf_response = _get_with_redirects(url, MAX_PDF_BYTES, get)
                except (SourceCheckFailure, OSError, TimeoutError):
                    continue
            result["pdf_http_status"] = pdf_response.status
            if pdf_response.status != 200 or not pdf_response.body.startswith(b"%PDF-"):
                continue
            if len(pdf_response.body) > MAX_PDF_BYTES:
                raise SourceCheckFailure("SOURCE_RESPONSE_TOO_LARGE")
            remote_sha = hashlib.sha256(pdf_response.body).hexdigest()
            result["downloaded_sha256"] = remote_sha
            result["remote_pdf_sha256"] = remote_sha
            if remote_sha != expected_sha256:
                mismatch = True
                continue
            modified = _header(pdf_response.headers, "Last-Modified")
            updated_at = _last_modified_utc(modified)
            result.update(
                status="VERIFIED",
                matched_pdf_url=pdf_url,
                matched_pdf_sha256=remote_sha,
                pdf_etag=_header(pdf_response.headers, "ETag"),
                pdf_last_modified=modified,
                exact_document_url=pdf_url,
                exact_pdf_uri=pdf_url,
                last_updated_at=updated_at,
                source_last_updated_at_utc=updated_at,
                exact_bytes_match=True,
                source_identity_verified=True,
                reason_code=None,
            )
            return result
        result["status"] = "MISMATCH" if mismatch else "UNVERIFIABLE"
        result["reason_code"] = (
            "SOURCE_PDF_SHA256_MISMATCH" if mismatch else "SOURCE_NO_EXACT_PDF_MATCH"
        )
    except SourceCheckFailure as exc:
        result["reason_code"] = exc.reason_code
    except Exception:
        result["reason_code"] = "SOURCE_FETCH_FAILED"
    return result


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _normalized_visible_html(body: bytes) -> str:
    parser = _VisibleText()
    parser.feed(body.decode("utf-8", errors="replace"))
    plain = " ".join(parser.parts)
    unaccented = unicodedata.normalize("NFKD", plain)
    return " ".join("".join(c for c in unaccented if not unicodedata.combining(c)).lower().split())


def _terms_present(legal: bytes, license_text: bytes) -> bool:
    eduscol = _normalized_visible_html(legal)
    etalab = _normalized_visible_html(license_text)
    if any(
        phrase in eduscol
        for phrase in (
            "licence etalab-2.0 ne s'applique plus",
            "licence etalab-2.0 retiree",
            "documents proposes en telechargement exclus de la licence",
        )
    ):
        return False
    return all(
        phrase in eduscol
        for phrase in (
            "documents proposes en telechargement",
            "licence etalab-2.0",
            "sont exclus",
            "tiers",
        )
    ) and all(
        phrase in etalab
        for phrase in (
            "licence ouverte 2.0",
            "reproduire",
            "extraire",
            "mentionner la paternite",
            "date de la derniere mise a jour",
        )
    )


def _write_source_receipt(root: Path, receipt: dict) -> str:
    """Scelle un reçu de métadonnées ; aucun octet HTML/PDF n'est conservé ici."""
    raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
           + "\n").encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    path = root / digest[:2] / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.exists():
        if path.read_bytes() != raw:
            raise SourceCheckFailure("SOURCE_RECEIPT_CAS_COLLISION")
        return digest
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return digest


def _canonical_json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n").encode("utf-8")


def _write_atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(_canonical_json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class _CachedTransport:
    """Cache LRU des réponses pendant le processus, sans corps HTTP sur disque."""

    def __init__(self, fetch: Callable[[str, int], HTTPResponse]) -> None:
        self.fetch = fetch
        self.entries: OrderedDict[str, HTTPResponse] = OrderedDict()
        self.bytes_used = 0

    def __call__(self, url: str, max_bytes: int) -> HTTPResponse:
        cached = self.entries.get(url)
        if cached is not None:
            self.entries.move_to_end(url)
            return cached
        response = self.fetch(url, max_bytes)
        size = len(response.body)
        if size <= HTTP_CACHE_MAX_BYTES:
            while self.entries and self.bytes_used + size > HTTP_CACHE_MAX_BYTES:
                _, old = self.entries.popitem(last=False)
                self.bytes_used -= len(old.body)
            self.entries[url] = response
            self.bytes_used += size
        return response


def _utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not value.endswith("Z") or parsed.tzinfo != timezone.utc:
        raise ValueError("SOURCE_CHECK_TIMESTAMP_NOT_UTC")
    return parsed


def _valid_source_checkpoint(
    path: Path, artifact: Mapping[str, str], inventory_sha: str, code_sha: str,
    now: datetime,
) -> bool:
    try:
        stat = path.stat()
        if stat.st_mode & 0o077:
            return False
        record = json.loads(path.read_bytes())
        digest = record.pop("checkpoint_sha256")
        checked = _utc_datetime(record["checked_at_utc"])
        age = now - checked
        if (
            record.get("kind") != SOURCE_CHECKPOINT_KIND
            or record.get("content_sha256") != artifact["content_sha256"]
            or record.get("source_listing_url") != artifact["source_listing_url"]
            or record.get("inventory_sha256") != inventory_sha
            or record.get("source_checker_code_sha256") != code_sha
            or not timedelta(0) <= age < CHECKPOINT_MAX_AGE
            or digest != hashlib.sha256(_canonical_json_bytes(record)).hexdigest()
            or not isinstance(record.get("source_identity"), dict)
            or not isinstance(record.get("rights_check"), dict)
            or record["rights_check"].get("rights_basis") != "NONE"
        ):
            return False
        return True
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return False


def verify_source_rights(
    artifact: Mapping[str, str],
    source_identity: Mapping[str, object],
    *,
    transport: Callable[[str, int], HTTPResponse] | None = None,
    checked_at_utc: str | None = None,
    receipt_root: Path | None = None,
) -> dict:
    """Vérifie les termes officiels applicables sans présumer tiers, actualité ou révocation.

    Le résultat est une **base de droits candidate**, pas une décision de
    publication. Les deux URL de termes sont fixes. Une erreur, un 403, une
    redirection ou une notice incomplète refusent toute base positive.
    """
    observed = checked_at_utc or datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    source_uri = artifact.get("source_listing_url")
    expected_sha = artifact.get("content_sha256")
    exact_uri = source_identity.get("exact_pdf_uri")
    remote_sha = source_identity.get("remote_pdf_sha256")
    result = {
        "source_verification": {
            "status": "UNVERIFIABLE",
            "listing_uri": source_uri,
            "exact_pdf_uri": None,
            "final_uri": None,
            "http_status": source_identity.get("pdf_http_status"),
            "observed_at_utc": observed,
            "etag": source_identity.get("pdf_etag"),
            "last_modified": source_identity.get("pdf_last_modified"),
            "remote_pdf_sha256": None,
            "terms_uri": None,
            "terms_sha256": None,
            "terms_observed_at_utc": None,
            "source_last_updated_at_utc": source_identity.get("source_last_updated_at_utc"),
            "revocation_evidence_uri": None,
        },
        "rights_basis": "NONE",
        "rights_evidence_uri": None,
        "license_or_terms_excerpt_hash": None,
        "license_snapshot_sha256": None,
        "source_receipt_sha256": None,
        "evidence_pages": [],
        "currentness_status": "UNVERIFIABLE",
        "revocation_status": "UNVERIFIABLE",
        "reason_codes": ["SOURCE_IDENTITY_NOT_PROVEN"],
    }
    if (
        source_identity.get("status") != "VERIFIED"
        or source_identity.get("source_identity_verified") is not True
        or source_identity.get("exact_bytes_match") is not True
        or source_identity.get("source_uri") != source_uri
        or source_identity.get("source_http_status") != 200
        or source_identity.get("pdf_http_status") != 200
        or not isinstance(exact_uri, str)
        or not isinstance(expected_sha, str)
        or remote_sha != expected_sha
        or source_identity.get("matched_pdf_url") != exact_uri
        or source_identity.get("matched_pdf_sha256") != expected_sha
        or source_identity.get("downloaded_sha256") != expected_sha
    ):
        return result
    try:
        _validate_url(exact_uri)
    except SourceCheckFailure:
        return result

    # L'identité des octets est une preuve indépendante des conditions de
    # réutilisation. Une notice indisponible laisse les droits inconnus, sans
    # effacer le résultat exact du contrôle du PDF.
    result["source_verification"].update(
        status="VERIFIED",
        exact_pdf_uri=exact_uri,
        final_uri=exact_uri,
        remote_pdf_sha256=remote_sha,
        observed_at_utc=source_identity.get("observed_at_utc") or observed,
    )
    result["reason_codes"] = ["OFFICIAL_TERMS_UNVERIFIABLE"]

    get = transport or _fetch_urllib
    try:
        legal = get(EDUSCOL_LEGAL_URI, MAX_HTML_BYTES)
        if (
            legal.status != 200
            or len(legal.body) > MAX_HTML_BYTES
            or not (_header(legal.headers, "Content-Type") or "").lower().startswith("text/html")
        ):
            raise SourceCheckFailure("EDUSCOL_TERMS_UNVERIFIABLE")
        license_response = get(ETALAB_LICENSE_URI, MAX_HTML_BYTES)
        if (
            license_response.status != 200
            or len(license_response.body) > MAX_HTML_BYTES
            or not (_header(license_response.headers, "Content-Type") or "")
            .lower()
            .startswith("text/html")
        ):
            raise SourceCheckFailure("ETALAB_LICENSE_UNVERIFIABLE")
        if not _terms_present(legal.body, license_response.body):
            raise SourceCheckFailure("TERMS_SCOPE_NOT_PROVEN")
    except (SourceCheckFailure, OSError, TimeoutError, urllib.error.URLError):
        result["reason_codes"] = ["OFFICIAL_TERMS_UNVERIFIABLE"]
        return result
    except Exception:
        result["reason_codes"] = ["OFFICIAL_TERMS_UNVERIFIABLE"]
        return result

    legal_sha = hashlib.sha256(legal.body).hexdigest()
    license_sha = hashlib.sha256(license_response.body).hexdigest()
    if receipt_root is None:
        result["reason_codes"] = ["SOURCE_RECEIPT_ROOT_REQUIRED"]
        return result
    receipt = {
        "kind": SOURCE_RIGHTS_RECEIPT_KIND,
        "artifact_content_sha256": expected_sha,
        "listing_uri": source_uri,
        "pdf": {
            "final_uri": exact_uri,
            "http_status": source_identity.get("pdf_http_status"),
            "observed_at_utc": source_identity.get("observed_at_utc") or observed,
            "etag": source_identity.get("pdf_etag"),
            "last_modified": source_identity.get("pdf_last_modified"),
            "content_sha256": remote_sha,
        },
        "legal_terms": {
            "final_uri": EDUSCOL_LEGAL_URI,
            "http_status": legal.status,
            "observed_at_utc": observed,
            "etag": _header(legal.headers, "ETag"),
            "last_modified": _header(legal.headers, "Last-Modified"),
            "body_sha256": legal_sha,
        },
        "license": {
            "final_uri": ETALAB_LICENSE_URI,
            "http_status": license_response.status,
            "observed_at_utc": observed,
            "etag": _header(license_response.headers, "ETag"),
            "last_modified": _header(license_response.headers, "Last-Modified"),
            "body_sha256": license_sha,
        },
        "rights_scope": "EDUSCOL_DOWNLOADS_EXCLUDING_THIRD_PARTY",
        "source_checker_code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "transport_kind": (
            "URLLIB_HTTPS_GET_NO_REDIRECT_V1"
            if transport is None or (
                isinstance(transport, _CachedTransport) and transport.fetch is _fetch_urllib
            ) else "INJECTED_TEST_TRANSPORT"
        ),
    }
    try:
        receipt_sha = _write_source_receipt(receipt_root, receipt)
    except (OSError, SourceCheckFailure):
        result["reason_codes"] = ["SOURCE_RECEIPT_WRITE_FAILED"]
        return result
    result["source_verification"].update(
        terms_uri=EDUSCOL_LEGAL_URI,
        terms_sha256=legal_sha,
        terms_observed_at_utc=observed,
    )
    result.update(
        rights_basis="EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE",
        rights_evidence_uri=EDUSCOL_LEGAL_URI,
        license_or_terms_excerpt_hash=legal_sha,
        license_snapshot_sha256=license_sha,
        source_receipt_sha256=receipt_sha,
        reason_codes=["CURRENTNESS_UNVERIFIABLE", "REVOCATION_UNVERIFIABLE"],
    )
    return result


def run_source_check_batch(
    packet_path: Path,
    output_dir: Path,
    *,
    transport: Callable[[str, int], HTTPResponse] | None = None,
    expected_count: int = 315,
    checked_at_utc: str | None = None,
) -> dict[str, int | str]:
    """Examine le packet complet avec reprise par SHA et cache HTTP en mémoire.

    Un checkpoint déjà positif est toujours rafraîchi : une licence ou une
    révocation peut changer entre deux passages. Le reçu CAS positif est stocké
    sous ``output_dir/receipts`` ; les corps PDF/HTML restent seulement en RAM.
    """
    raw_packet = packet_path.read_bytes()
    packet = json.loads(raw_packet)
    artifacts = packet.get("artifacts") if isinstance(packet, dict) else None
    if not isinstance(artifacts, list) or len(artifacts) != expected_count:
        raise ValueError("SOURCE_PACKET_COUNT_INVALID")
    by_sha: dict[str, dict[str, str]] = {}
    for row in artifacts:
        if not isinstance(row, dict):
            raise ValueError("SOURCE_PACKET_ARTIFACT_INVALID")
        sha, uri = row.get("content_sha256"), row.get("source_listing_url")
        if (
            not isinstance(sha, str) or len(sha) != 64
            or any(c not in "0123456789abcdef" for c in sha)
            or not isinstance(uri, str) or not uri or sha in by_sha
        ):
            raise ValueError("SOURCE_PACKET_ARTIFACT_INVALID")
        by_sha[sha] = row
    observed = checked_at_utc or datetime.now(timezone.utc).isoformat(
        timespec="seconds"
    ).replace("+00:00", "Z")
    now = _utc_datetime(observed)
    inventory_sha = hashlib.sha256(raw_packet).hexdigest()
    code_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    cache = _CachedTransport(transport or _fetch_urllib)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    processed = reused = identities = rights_candidates = 0
    for sha, artifact in sorted(by_sha.items()):
        checkpoint_path = output_dir / f"{sha}.json"
        if _valid_source_checkpoint(checkpoint_path, artifact, inventory_sha, code_sha, now):
            checkpoint = json.loads(checkpoint_path.read_bytes())
            reused += 1
        else:
            identity = verify_source(artifact, transport=cache, checked_at_utc=observed)
            rights = verify_source_rights(
                artifact, identity, transport=cache, checked_at_utc=observed,
                receipt_root=output_dir / "receipts",
            )
            checkpoint = {
                "kind": SOURCE_CHECKPOINT_KIND,
                "content_sha256": sha,
                "source_listing_url": artifact["source_listing_url"],
                "inventory_sha256": inventory_sha,
                "source_checker_code_sha256": code_sha,
                "checked_at_utc": observed,
                "source_identity": identity,
                "rights_check": rights,
            }
            checkpoint["checkpoint_sha256"] = hashlib.sha256(
                _canonical_json_bytes(checkpoint)
            ).hexdigest()
            _write_atomic_json(checkpoint_path, checkpoint)
            processed += 1
        identities += checkpoint["source_identity"].get("source_identity_verified") is True
        rights_candidates += checkpoint["rights_check"].get("rights_basis") != "NONE"
    return {
        "inventory_count": len(by_sha),
        "processed_count": processed,
        "reused_count": reused,
        "source_identity_verified_count": identities,
        "rights_basis_candidates": rights_candidates,
        "inventory_sha256": inventory_sha,
        "source_checker_code_sha256": code_sha,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Vérification checkpointée des 315 sources PDF")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = run_source_check_batch(args.packet, args.output_dir)
    except (OSError, ValueError, TypeError, KeyError) as error:
        print(json.dumps({"status": "FAIL_CLOSED", "error_type": type(error).__name__}))
        return 1
    print(json.dumps({"status": "COMPLETE", **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
