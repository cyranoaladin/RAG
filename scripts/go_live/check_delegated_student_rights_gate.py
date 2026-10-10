"""Vérification indépendante, fail-closed, des droits étudiants délégués.

Ce module ne charge jamais le moteur d'adjudication. Il relit les preuves, la
politique, le mandat, les manifests sources et la feuille depuis leurs octets.
Un exit 0 signifie uniquement que le pack de décisions est cohérent ; il ne
constitue ni la review humaine exacte du HEAD ni une autorisation de déployer.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import csv
import hashlib
import io
import json
import math
import re
import subprocess
import sys
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

import jsonschema
import yaml

CFTR = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
REVIEW_MAX_CHARS_PER_SEGMENT = 4000
REVIEW_VISION_RENDER_SCALE = 0.5
REVIEW_VISION_MAX_PIXELS = 150_000
REVIEW_VISION_MODELS = frozenset({
    "qwen3-vl:2b", "qwen2.5vl:3b", "moondream:latest", "granite3.2-vision:2b",
})
REVIEW_ASSEMBLY_PROTOCOL = "NEXUS_REVIEW_TEXT_ASSEMBLY_V5"
SOURCE_LEGAL_URI = "https://eduscol.education.gouv.fr/4656/mentions-legales"
SOURCE_LICENSE_URI = "https://www.data.gouv.fr/pages/legal/licences/etalab-2.0"
TRUE_CHECKS = (
    "exact_bytes_match", "full_document_scan_complete", "annexes_scan_complete",
    "explicit_rights_basis_present", "reuse_scope_covers_student_retrieval_excerpt",
    "source_exact_document_match", "pii_gate_pass", "currentness_gate_pass",
    "revocation_gate_pass", "student_suitability_pass",
)
FALSE_CHECKS = (
    "restrictive_notice_detected", "teacher_only_detected",
    "non_disclosure_instruction_detected", "unlicensed_third_party_content_detected",
)
RIGHTS_BASES = frozenset({
    "NEXUS_FIRST_PARTY_OWNED_WITH_REGISTRY_PROOF",
    "EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE",
    "EXPLICIT_REUSE_TERMS_COVERING_THE_AUTHORIZED_USE",
    "PUBLIC_DOMAIN_OR_EQUIVALENT_WITH_VERIFIABLE_BASIS",
})
DISPOSITIONS = frozenset({"APPROVE_PUBLIC", "EXCLUDE", "REPLACE_WITH_NEW_CONTENT"})
SHEET_COLUMNS = (
    "content_sha256", "source_release", "collections", "source_path",
    "source_listing_url", "page_count", "source_pii_status",
    "source_currentness_disposition", "automated_signal_pages",
    "explicit_student_exclusion_signal", "rights_review", "student_suitability",
    "third_party_exception_review", "pii_recheck", "currentness_recheck",
    "revocation_recheck", "student_public_disposition", "rights_evidence_ref",
    "decision_evidence_pages", "decision_reason", "human_reviewer", "reviewed_at_utc",
    "decision_executor", "delegation_id", "evidence_sha256",
    "source_disposition", "derivative_disposition", "derivative_content_sha256",
    "derivative_receipt_sha256", "rights_authority_id", "rights_authority_sha256",
)
DEFAULTS = {
    "index": "docs/reports/go_live/student_rights_evidence/index.json",
    "packet": "docs/reports/go_live/student_public_rights_individual_review_packet_20261009.json",
    "sheet": "docs/reports/go_live/student_public_rights_individual_review_sheet_20261009.tsv",
    "policy": "governance/student_public_rights/delegated_review_policy_v1.yml",
    "mandate": "governance/student_public_rights/delegation_abenrhouma_20261009.yml",
    "schema": "governance/student_public_rights/schemas/automated_artifact_review_v1.schema.json",
    "engine": "scripts/go_live/adjudicate_student_public_rights.py",
    "scanner": "scripts/go_live/student_rights_pdf_scan.py",
    "source_checker": "scripts/go_live/student_rights_source_provenance.py",
    "reviewer": "scripts/go_live/student_rights_reviewers.py",
    "derivative_builder": "scripts/go_live/student_rights_text_derivative.py",
    "extraction_policy": "governance/student_public_rights/text_derivative_extraction_policy_v1.yml",
    "candidate_manifest": "docs/reports/go_live/student_rights_evidence/public_derivative_candidate_manifest_20261010.json",
}


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            + "\n").encode("utf-8")


def _compact_json_bytes(value: Any) -> bytes:
    """Octets CAS du reviewer (le format de ses reçus n'a pas de LF final)."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA_RE.fullmatch(value) is not None


def _is_git_sha(value: Any) -> bool:
    return isinstance(value, str) and GIT_SHA_RE.fullmatch(value) is not None


def _is_nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _mapping(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _unique_object_pairs(pairs: list[tuple[str, Any]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path) -> tuple[dict, bytes]:
    data = path.read_bytes()
    value = json.loads(data, object_pairs_hook=_unique_object_pairs)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value, data


def _secure_path(root: Path, relative: Any) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("path is not relative")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("path escapes repository root")
    return path


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):  # type: ignore[override]
        return None


def _live_source_bytes(url: str, limit: int) -> bytes:
    parsed = urllib.parse.urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in {
            "eduscol.education.gouv.fr", "www.data.gouv.fr"}
            or parsed.username is not None or parsed.password is not None
            or parsed.port not in (None, 443)):
        raise ValueError("source URI outside allowed hosts")
    request = urllib.request.Request(
        url, headers={"User-Agent": "NexusIndependentRightsGate/1",
                      "Accept-Encoding": "identity"},
    )
    with urllib.request.build_opener(_NoRedirect).open(request, timeout=20) as response:
        if response.status != 200:
            raise ValueError("source HTTP not 200")
        body = response.read(limit + 1)
    if len(body) > limit:
        raise ValueError("source response exceeds limit")
    return body


class _VisibleHtml(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _visible_terms(body: bytes) -> str:
    parser = _VisibleHtml()
    parser.feed(body.decode("utf-8", errors="replace"))
    plain = unicodedata.normalize("NFKD", " ".join(parser.parts))
    return " ".join("".join(c for c in plain if not unicodedata.combining(c)).lower().split())


def _normalized_terms(body: bytes) -> str:
    value = unicodedata.normalize("NFKD", body.decode("utf-8"))
    return " ".join("".join(c for c in value if not unicodedata.combining(c)).lower().split())


def _verify_sitewide_authority(root: Path, authority: dict) -> list[str]:
    """Relit les captures Chromium versionnées, sans traiter un HTTP 403 comme avis de droit."""
    errors: list[str] = []
    if (authority.get("authority_kind") != "SITEWIDE_DOWNLOAD_AUTHORITY"
            or authority.get("authority_id") != "EDUSCOL_ETALAB_2_0_SITEWIDE"
            or authority.get("status") != "SEALED_PENDING_FINAL_EXACT_HEAD_APPROVAL"
            or authority.get("licence_id") != "ETALAB-2.0"
            or authority.get("full_pdf_redistribution_allowed_by_product") is not False
            or authority.get("answer_generation_allowed") is not False):
        errors.append("AUTHORITY_SCOPE")
    if (authority.get("legal_notice_url") != SOURCE_LEGAL_URI
            or authority.get("licence_url") != SOURCE_LICENSE_URI):
        errors.append("AUTHORITY_DOMAIN_MISMATCH")
    attribution = authority.get("attribution_required")
    if not isinstance(attribution, list) or not {
            "source", "concédant", "URL", "date de dernière mise à jour",
    } <= set(attribution):
        errors.append("AUTHORITY_ATTRIBUTION_SCOPE")
    excluded = authority.get("excluded_components")
    if not isinstance(excluded, list) or not {
            "photographie tierce", "extrait textuel tiers",
            "tout composant dont le ministère ne détient pas les droits",
    } <= set(excluded):
        errors.append("AUTHORITY_THIRD_PARTY_SCOPE")
    if (authority.get("resource_binding_for_original_derivative_accepted")
            != ["EXACT_CURRENT_SOURCE", "HISTORICAL_OFFICIAL_SNAPSHOT"]
            or authority.get("old_sha_derivative_forbidden_on_replacement_alone") is not True
            or authority.get("replacement_requires_new_artifact_sha256") is not True):
        errors.append("AUTHORITY_RESOURCE_BINDING")
    capture = authority.get("browser_capture")
    if not isinstance(capture, dict):
        return sorted(set(errors + ["AUTHORITY_CAPTURE_MISSING"]))
    script = capture.get("capture_script")
    try:
        if (capture.get("capture_tool") != "Playwright Chromium"
                or not _is_nonempty(capture.get("capture_tool_version"))
                or not _is_nonempty(capture.get("chromium_version"))
                or _sha256(_secure_path(root, script).read_bytes())
                != capture.get("capture_script_sha256")):
            errors.append("AUTHORITY_CAPTURE_TOOL")
    except (OSError, ValueError):
        errors.append("AUTHORITY_CAPTURE_TOOL")
    proof_dir = root / "docs/reports/go_live/student_rights_evidence/authorities"
    for name, url, phrases in (
        ("legal_notice", SOURCE_LEGAL_URI, (
            "documents proposes en telechargement", "licence etalab-2.0",
            "sont exclus", "realises par des tiers", "extraits de textes",
        )),
        ("etalab_2_0_licence", SOURCE_LICENSE_URI, (
            "informations derivees", "mentionner la paternite",
            "date de la derniere mise a jour", "extraire", "publier",
        )),
    ):
        meta = capture.get(name)
        if not isinstance(meta, dict):
            errors.append("AUTHORITY_CAPTURE_MISSING")
            continue
        try:
            receipt_path = _secure_path(root, meta.get("receipt"))
            if receipt_path.parent != proof_dir.resolve():
                raise ValueError("capture outside evidence directory")
            receipt, receipt_bytes = _read_json(receipt_path)
            if _sha256(receipt_bytes) != meta.get("receipt_sha256"):
                errors.append("AUTHORITY_CAPTURE_DIGEST")
            if (receipt.get("kind") != "NEXUS_EDUSCOL_SITEWIDE_BROWSER_CAPTURE_V1"
                    or receipt.get("requested_url") != url
                    or receipt.get("final_url") != url
                    or receipt.get("http_status") != 200
                    or meta.get("http_status") != 200):
                errors.append("AUTHORITY_CAPTURE_ORIGIN")
            if (receipt.get("observed_at_utc") != meta.get("observed_at_utc")
                    or receipt.get("browser") != "chromium"
                    or receipt.get("browser_version") != capture.get("chromium_version")
                    or receipt.get("playwright_version") != capture.get("capture_tool_version")
                    or receipt.get("capture_script_sha256") != capture.get("capture_script_sha256")):
                errors.append("AUTHORITY_CAPTURE_METADATA")
            observed = datetime.fromisoformat(str(meta.get("observed_at_utc")).replace("Z", "+00:00"))
            if observed.tzinfo is None or observed > datetime.now(timezone.utc):
                errors.append("AUTHORITY_CAPTURE_DATE")
            contents: dict[str, bytes] = {}
            for label, file_key, hash_key in (
                ("html", "normalized_html_file", "normalized_html_sha256"),
                ("text", "extracted_text_file", "extracted_text_sha256"),
                ("png", "screenshot_file", "screenshot_sha256"),
            ):
                file_name = receipt.get(file_key)
                if not isinstance(file_name, str) or Path(file_name).name != file_name:
                    raise ValueError("invalid capture filename")
                contents[label] = (proof_dir / file_name).read_bytes()
                if (_sha256(contents[label]) != receipt.get(hash_key)
                        or receipt.get(hash_key) != meta.get(hash_key)):
                    errors.append("AUTHORITY_CAPTURE_DIGEST")
            if not contents["png"].startswith(b"\x89PNG\r\n\x1a\n"):
                errors.append("AUTHORITY_CAPTURE_FORMAT")
            if not all(phrase in _normalized_terms(contents["text"]) for phrase in phrases):
                errors.append("AUTHORITY_LEGAL_CLAUSE")
            if not all(phrase in _visible_terms(contents["html"]) for phrase in phrases):
                errors.append("AUTHORITY_HTML_CLAUSE")
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            errors.append("AUTHORITY_CAPTURE_MISSING")
    return sorted(set(errors))


_DERIVATIVE_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_DERIVATIVE_PHONE = re.compile(r"(?<!\d)(?:\+33|\+216|0)(?:[\s.()\-]*\d){8,}(?!\d)")
_DERIVATIVE_TEACHER = re.compile(
    r"\b(?:corrig[ée]|bar[èe]me|enseignant(?:s|es)?|professeur(?:s)?|"
    r"r[ée]serv[ée] aux (?:enseignants|professeurs)|r[ée]ponses? attendues?|"
    r"solutions?|ne pas communiquer|non.divulgation)\b", re.I,
)
_DERIVATIVE_THIRD = re.compile(
    r"(?:©|\bcopyright\b|\btous droits r[ée]serv[ée]s\b|"
    r"\breproduit avec l.autorisation\b|\bextrait de\b|\badapt[ée] de\b|"
    r"\bcr[ée]dits?\b|\b[ée]diteur\b|\b[ée]ditions?\b|\blicen[cs]e\b|"
    r"\bcreative commons\b|\bCC[- ]?BY\b|\bISBN\b|\bDOI\b|"
    r"\bbibliographie\b|\bsitographie\b|\ben partenariat avec\b|"
    r"\bavec le concours de\b|\b(?:Nathan|Hachette|Belin|Hatier|Bordas|"
    r"Magnard|Flammarion|Gallimard|Larousse|Pearson|Dunod)\b)", re.I,
)
_DERIVATIVE_THIRD_PAGE = re.compile(
    r"(?:\bcr[ée]dits?\s+(?:photo|photographique|illustration|image|auteur)\b|"
    r"\breproduit avec l.autorisation\b|\btous droits r[ée]serv[ée]s\b|"
    r"\bbibliographie\b|\bsitographie\b|\ben partenariat avec\b|"
    r"\bavec le concours de\b|\bISBN\b|"
    r"\b(?:[ée]ditions?\s+)?(?:Nathan|Hachette|Belin|Hatier|Bordas|"
    r"Magnard|Flammarion|Gallimard|Larousse|Pearson|Dunod)\b)", re.I,
)
_DERIVATIVE_LONG_QUOTE = re.compile(r"[«“][\s\S]{120,}?[»”]")
_OFFICIAL_PUBLISHER = re.compile(
    r"(?:\bDGESCO\b|direction\s+g[ée]n[ée]rale\s+de\s+l.enseignement\s+scolaire|"
    r"minist[èe]re\s+de\s+l.[ée]ducation\s+nationale|\bMENJS?\b)", re.I,
)
_PUBLISHER_IMPRINT = re.compile(
    r"(?:©|\bcopyright\b|\b[ée]diteur\s*:?|\b[ée]dit[ée]\s+par\b|"
    r"\bpubli[ée]\s+par\b|\br[ée]alis[ée]\s+par\b|\bcon[çc]u\s+par\b)"
    r"\s*[:\-]?\s*[^\n]{0,80}?"
    r"(?:\bDGESCO\b|direction\s+g[ée]n[ée]rale\s+de\s+l.enseignement\s+scolaire|"
    r"minist[èe]re\s+de\s+l.[ée]ducation\s+nationale|\bMENJS?\b)", re.I,
)
_FIRST_PARTY_COPYRIGHT = re.compile(
    r"(?:©|\bcopyright\b)\s*(?:\bDGESCO\b|"
    r"direction\s+g[ée]n[ée]rale\s+de\s+l.enseignement\s+scolaire|"
    r"minist[èe]re\s+de\s+l.[ée]ducation\s+nationale|\bMENJS?\b)", re.I,
)


def _derivative_reason(text: str) -> str | None:
    if _DERIVATIVE_EMAIL.search(text) or _DERIVATIVE_PHONE.search(text):
        return "PII_PATTERN"
    if _DERIVATIVE_TEACHER.search(text):
        return "TEACHER_OR_NONDISCLOSURE_SIGNAL"
    if (_DERIVATIVE_THIRD.search(_FIRST_PARTY_COPYRIGHT.sub("", text))
            or _DERIVATIVE_LONG_QUOTE.search(text)):
        return "THIRD_PARTY_SIGNAL"
    return None


def _derivative_class(reason: str | None) -> str:
    if reason is None:
        return "SAFE_TEXT_CANDIDATE"
    if reason in {"THIRD_PARTY_SIGNAL", "THIRD_PARTY_PAGE_SIGNAL"}:
        return "THIRD_PARTY_TEXT_SUSPECT"
    if reason == "TEACHER_OR_NONDISCLOSURE_SIGNAL":
        return "TEACHER_ONLY"
    if reason in {"PII_PATTERN", "PACKET_AUTOMATED_REVIEW_SIGNAL",
                  "PACKET_PII_NOT_CLEARED", "PUBLISHER_NOT_PROVEN",
                  "NATIVE_BLOCK_EXCEEDS_REVIEW_BUDGET"}:
        return "PII_OR_UNCERTAIN"
    return "EXCLUDED_NON_TEXT"


def _bbox_digest(box: Any) -> str:
    values = [format(float(value), ".6f") for value in box[:4]]
    return _sha256(json.dumps(values, separators=(",", ":")).encode("ascii"))


def _boxes_overlap(left: Any, right: Any) -> bool:
    return (max(float(left[0]), float(right[0])) < min(float(left[2]), float(right[2]))
            and max(float(left[1]), float(right[1])) < min(float(left[3]), float(right[3])))


def _publisher_proof_from_exact_pdf(
    document: Any, source_sha: str, source_uri: str | None,
    provenance_checkpoint: dict | None, authority_sha: str | None,
) -> dict:
    """Reconstitue l'éditeur depuis les octets PDF ou une capture officielle liée."""
    author = unicodedata.normalize("NFC", str((document.metadata or {}).get("author") or ""))
    author = author.replace("\r\n", "\n").replace("\r", "\n").strip()
    if author and _OFFICIAL_PUBLISHER.search(author):
        return {"status": "PASS", "kind": "OFFICIAL_PDF_AUTHOR_METADATA",
                "metadata_field": "author",
                "normalized_value_sha256": _sha256(author.encode("utf-8"))}
    for page_index in sorted({0, len(document) - 1}):
        for block_index, block in enumerate(document.load_page(page_index).get_text(
                "blocks", sort=True)):
            if block[6] != 0:
                continue
            native = unicodedata.normalize("NFC", str(block[4]))
            native = native.replace("\r\n", "\n").replace("\r", "\n").strip()
            if _PUBLISHER_IMPRINT.search(native):
                return {"status": "PASS", "kind": "EXPLICIT_DOCUMENT_IMPRINT",
                        "page_number": page_index + 1, "block_index": block_index,
                        "normalized_text_sha256": _sha256(native.encode("utf-8"))}
    checkpoint = _mapping(provenance_checkpoint)
    source = _mapping(checkpoint.get("source_provenance"))
    anchor = _mapping(source.get("matched_anchor"))
    pdf = _mapping(source.get("pdf_fetch"))
    if (checkpoint.get("kind") == "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1"
            and source.get("status") == "EXACT_CURRENT_SOURCE"
            and source.get("revocation_status") == "PASS_CURRENT_OFFICIAL_PUBLICATION"
            and checkpoint.get("rights_basis_kind") == "SITEWIDE_DOWNLOAD_AUTHORITY"
            and checkpoint.get("authority_yaml_sha256") == authority_sha
            and _is_sha(authority_sha)
            and _is_sha(checkpoint.get("checkpoint_sha256"))
            and _is_sha(source.get("listing_capture_receipt_sha256"))
            and checkpoint.get("content_sha256") == source_sha
            and pdf.get("content_sha256") == source_sha
            and pdf.get("final_url") == source_uri
            and anchor.get("href") == source_uri):
        return {"status": "PASS", "kind": "OFFICIAL_CAPTURED_DOWNLOAD_PUBLISHER",
                "listing_capture_receipt_sha256": source["listing_capture_receipt_sha256"],
                "source_provenance_checkpoint_sha256": checkpoint["checkpoint_sha256"],
                "rights_authority_sha256": authority_sha,
                "source_content_sha256": source_sha,
                "matched_anchor_href": anchor["href"], "source_pdf_url": source_uri}
    return {"status": "UNPROVEN", "kind": None}


def _derivative_policy_errors(policy: Any) -> list[str]:
    rules = _mapping(_mapping(policy).get("classification"))
    expected = {
        "publisher_name_regex": _OFFICIAL_PUBLISHER.pattern,
        "first_party_copyright_regex": _FIRST_PARTY_COPYRIGHT.pattern,
        "third_party_block_regex": _DERIVATIVE_THIRD.pattern,
        "third_party_page_regex": _DERIVATIVE_THIRD_PAGE.pattern,
        "long_quotation_regex": _DERIVATIVE_LONG_QUOTE.pattern,
    }
    if any(rules.get(key) != pattern for key, pattern in expected.items()):
        return ["DERIVATIVE_POLICY_REGEX_MISMATCH"]
    imprint = (str(rules.get("publisher_imprint_marker_regex"))
               + r"\s*[:\-]?\s*[^\n]{0,80}?"
               + str(rules.get("publisher_name_regex")))
    if (imprint != _PUBLISHER_IMPRINT.pattern
            or rules.get("publisher_imprint_max_same_line_gap_chars") != 80
            or rules.get("third_party_page_signal_excludes_all_blocks") is not True
            or rules.get("publisher_identity_missing_disposition") != "EXCLUDE"
            or rules.get("model_review_may_override_excluded_class") is not False):
        return ["DERIVATIVE_POLICY_REGEX_MISMATCH"]
    return []


def _verify_text_derivative(
    receipt: dict, pdf_path: Path, packet_artifact: dict, candidate_bytes: bytes,
    extraction_policy_sha: str, adjudication_policy_sha: str, builder_code_sha: str,
    provenance_checkpoint: dict | None = None, rights_authority_sha: str | None = None,
) -> list[str]:
    """Reconstruit les octets et la carte complète des blocs sans importer le générateur."""
    import fitz

    errors: list[str] = []
    source_sha = packet_artifact.get("content_sha256")
    try:
        pdf_bytes = pdf_path.read_bytes()
    except OSError:
        return ["DERIVATIVE_SOURCE_UNREADABLE"]
    if _sha256(pdf_bytes) != source_sha:
        return ["DERIVATIVE_SOURCE_SHA_MISMATCH"]
    attribution = _mapping(receipt.get("source_attribution"))
    if (not all(_is_nonempty(attribution.get(key)) for key in (
            "source_uri", "source_label", "source_updated_at", "source_date_kind", "licensor",
            "licence_id", "derivative_notice"))
            or set(attribution) != {"source_uri", "source_label", "source_updated_at",
                                    "source_date_kind",
                                    "licensor", "licence_id", "derivative_notice"}):
        errors.append("DERIVATIVE_ATTRIBUTION_MISSING")
    if attribution.get("source_date_kind") not in {
            "PDF_EXPLICIT_UPDATE_DATE", "OFFICIAL_RESOURCE_UPDATE_DATE", "DATED_OFFICIAL_SNAPSHOT"}:
        errors.append("DERIVATIVE_ATTRIBUTION_DATE")
    if (attribution.get("source_date_kind") == "DATED_OFFICIAL_SNAPSHOT"
            and f"snapshot du {attribution.get('source_updated_at')}".lower() not in str(
                attribution.get("derivative_notice", "")).lower()):
        errors.append("DERIVATIVE_SNAPSHOT_NOTICE_MISSING")
    try:
        updated = datetime.fromisoformat(str(attribution.get("source_updated_at")).replace("Z", "+00:00"))
        if updated.tzinfo is None or updated > datetime.now(timezone.utc):
            errors.append("DERIVATIVE_ATTRIBUTION_DATE")
    except ValueError:
        errors.append("DERIVATIVE_ATTRIBUTION_DATE")
    if (receipt.get("kind") != "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1"
            or receipt.get("source_content_sha256") != source_sha
            or receipt.get("source_file_size_bytes") != len(pdf_bytes)
            or receipt.get("source_page_count") != packet_artifact.get("page_count")
            or receipt.get("source_packet_artifact_sha256")
            != _sha256(_compact_json_bytes(packet_artifact))
            or receipt.get("extraction_policy_sha256") != extraction_policy_sha
            or receipt.get("adjudication_policy_sha256") != adjudication_policy_sha
            or receipt.get("generator_code_sha256") != builder_code_sha
            or receipt.get("extractor_pymupdf_version") != fitz.VersionBind
            or receipt.get("normalization") != "NFC_CRLF_TO_LF_STRIP_V1"
            or receipt.get("serialization_protocol")
            != "NEXUS-STUDENT-TEXT-DERIVATIVE-SERIALIZATION-V2"
            or receipt.get("block_extraction") != "page.get_text('blocks', sort=True)"
            or receipt.get("group_max_chars") != 4000
            or receipt.get("status") != "PREPARED_PRIVATE"
            or receipt.get("publication_authorized") is not False):
        errors.append("DERIVATIVE_PROVENANCE_MISMATCH")
    if (receipt.get("derivative_media_type") != "text/plain"
            or receipt.get("derivative_encoding") != "utf-8"
            or receipt.get("ocr_used") is not False
            or receipt.get("images_copied") is not False
            or receipt.get("graphic_renders_copied") is not False
            or receipt.get("all_source_pages_inspected") is not True):
        errors.append("DERIVATIVE_NON_TEXT_PUBLIC")
    signals = packet_artifact.get("automated_review_signals")
    if not isinstance(signals, list):
        return sorted(set(errors + ["DERIVATIVE_PACKET_SIGNALS_INVALID"]))
    by_page: dict[int, list[str]] = defaultdict(list)
    for signal in signals:
        if not isinstance(signal, dict) or set(signal) != {"kind", "page"}:
            return sorted(set(errors + ["DERIVATIVE_PACKET_SIGNALS_INVALID"]))
        by_page[signal["page"]].append(signal["kind"])
    if packet_artifact.get("explicit_student_exclusion_signal") is True or source_sha == CFTR:
        errors.append("DERIVATIVE_SOURCE_EXCLUDED")
    expected_pages: list[dict] = []
    reconstructed = bytearray(
        b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n"
        + _compact_json_bytes({"source_pdf_sha256": source_sha, **attribution}) + b"\n"
    )
    try:
        with fitz.open(stream=pdf_bytes, filetype="pdf") as document:
            if (document.is_encrypted or document.embfile_count()
                    or len(document) != packet_artifact.get("page_count")):
                return sorted(set(errors + ["DERIVATIVE_PDF_STRUCTURE"]))
            publisher_proof = _publisher_proof_from_exact_pdf(
                document, source_sha, attribution.get("source_uri"),
                provenance_checkpoint, rights_authority_sha,
            )
            if (receipt.get("publisher_proof") != publisher_proof
                    or receipt.get("publisher_status") != publisher_proof["status"]
                    or publisher_proof["status"] != "PASS"):
                errors.append("DERIVATIVE_PUBLISHER_PROOF_MISMATCH")
            for page_number, page in enumerate(document, 1):
                citation = {"source_pdf_sha256": source_sha,
                            "source_page": page_number, **attribution}
                blocks = page.get_text("blocks", sort=True)
                raster = [image["bbox"] for image in page.get_image_info()]
                vectors = [drawing["rect"] for drawing in page.get_drawings()]
                third_party_page = any(
                    _DERIVATIVE_THIRD_PAGE.search(
                        unicodedata.normalize("NFC", str(block[4])).replace(
                            "\r\n", "\n").replace("\r", "\n").strip()
                    ) for block in blocks if block[6] == 0
                )
                blocked = ("PACKET_PII_NOT_CLEARED"
                           if packet_artifact.get("source_pii_status") != "CLEARED"
                           else "PACKET_AUTOMATED_REVIEW_SIGNAL"
                           if page_number in by_page else None)
                all_blocks: list[dict] = []
                excluded: list[dict] = []
                selected: list[tuple[int, str]] = []
                native_hashes: list[str] = []
                for index, block in enumerate(blocks):
                    native = unicodedata.normalize("NFC", str(block[4]))
                    native = native.replace("\r\n", "\n").replace("\r", "\n").strip()
                    facts = {"block_index": index, "block_type": block[6],
                             "normalized_text_sha256": _sha256(native.encode("utf-8")),
                             "bbox_sha256": _bbox_digest(block)}
                    reason: str | None
                    if block[6] != 0:
                        reason = "NON_TEXT_BLOCK"
                    else:
                        native_hashes.append(facts["normalized_text_sha256"])
                        if blocked:
                            reason = blocked
                        elif publisher_proof["status"] != "PASS":
                            reason = "PUBLISHER_NOT_PROVEN"
                        elif third_party_page:
                            reason = "THIRD_PARTY_PAGE_SIGNAL"
                        elif not native:
                            reason = "EMPTY_NATIVE_BLOCK"
                        elif any(_boxes_overlap(block, image) for image in raster):
                            reason = "RASTER_OVERLAP"
                        elif any(_boxes_overlap(block, vector) for vector in vectors):
                            reason = "VECTOR_OVERLAP"
                        elif len(native) > 4000:
                            reason = "NATIVE_BLOCK_EXCEEDS_REVIEW_BUDGET"
                        else:
                            reason = _derivative_reason(native)
                    facts["block_class"] = _derivative_class(reason)
                    if reason is None:
                        facts["citation"] = citation
                        selected.append((index, native))
                    else:
                        excluded.append({**facts, "reason_code": reason})
                    all_blocks.append(facts)
                start = len(reconstructed)
                offsets: dict[int, tuple[int, int]] = {}
                if selected:
                    for index, native in selected:
                        reconstructed.extend(f"\n[PAGE {page_number} BLOCK {index}]\n".encode("ascii"))
                        reconstructed.extend(_compact_json_bytes(citation) + b"\n")
                        block_start = len(reconstructed)
                        reconstructed.extend(native.encode("utf-8"))
                        offsets[index] = (block_start, len(reconstructed))
                        all_blocks[index]["byte_start"] = block_start
                        all_blocks[index]["byte_end"] = len(reconstructed)
                        reconstructed.extend(b"\n")
                batches: list[tuple[list[int], str]] = []
                ids: list[int] = []
                group_text = ""
                for index, native in selected:
                    proposed = group_text + ("\n\n" if group_text else "") + native
                    if group_text and len(proposed) > 4000:
                        batches.append((ids, group_text))
                        ids, group_text = [index], native
                    else:
                        ids.append(index)
                        group_text = proposed
                if ids:
                    batches.append((ids, group_text))
                groups = [{"group_index": position,
                           "group_count": len(batches), "block_indices": ids,
                           "group_text_sha256": _sha256(group_text.encode("utf-8")),
                           "citation": citation,
                           "byte_start": offsets[ids[0]][0],
                           "byte_end": offsets[ids[-1]][1]}
                          for position, (ids, group_text) in enumerate(batches, 1)]
                expected_pages.append({
                    "page_number": page_number,
                    "native_text_blocks_sha256": _sha256("\n".join(native_hashes).encode("ascii")),
                    "all_blocks": all_blocks,
                    "selected_block_indices": [index for index, _ in selected],
                    "excluded_blocks": excluded,
                    "raster_image_count": len(raster),
                    "vector_drawing_count": len(vectors),
                    "third_party_page_signal": bool(third_party_page),
                    "packet_signal_kinds": sorted(by_page.get(page_number, [])),
                    "packet_pii_status": packet_artifact.get("source_pii_status"),
                    "review_groups": groups,
                    "byte_start": start, "byte_end": len(reconstructed),
                    "derived_page_text_sha256": _sha256(bytes(reconstructed[start:])),
                })
    except (OSError, ValueError, RuntimeError, KeyError, TypeError):
        return sorted(set(errors + ["DERIVATIVE_PDF_RECONSTRUCTION_FAILED"]))
    if canonical_json_bytes(expected_pages) != canonical_json_bytes(receipt.get("pages")):
        errors.append("DERIVATIVE_BLOCK_MAP_MISMATCH")
    derivative_sha = _sha256(bytes(reconstructed))
    if (not reconstructed or candidate_bytes != bytes(reconstructed)
            or receipt.get("derivative_content_sha256") != derivative_sha
            or receipt.get("derivative_byte_count") != len(reconstructed)
            or receipt.get("candidate_relpath") != f"candidates/{derivative_sha}.txt"
            or derivative_sha == source_sha):
        errors.append("DERIVATIVE_BYTES_MISMATCH")
    return sorted(set(errors))


def _verify_candidate_manifest(
    manifest: dict, records: dict[str, dict], packets: dict[str, dict],
    derivative_receipts: dict[str, dict], inventory_sha: str, authority_sha: str,
    extraction_policy_sha: str, source_collections: set[str],
    *, required_collections: int = 11,
) -> tuple[list[str], dict]:
    """Recompte les seuls dérivés candidats ; aucun ancien chunk PDF n'est reporté."""
    errors: list[str] = []
    if (set(manifest) != {"kind", "status", "inventory_sha256",
                          "rights_authority_sha256",
                          "text_derivative_extraction_policy_sha256", "entries",
                          "excluded_source_sha256", "counts"}
            or manifest.get("kind") != "NEXUS_STUDENT_PUBLIC_DERIVATIVE_CANDIDATE_MANIFEST_V1"
            or manifest.get("status") != "PRE_REVIEW_NOT_PROMOTABLE"
            or manifest.get("inventory_sha256") != inventory_sha
            or manifest.get("rights_authority_sha256") != authority_sha
            or manifest.get("text_derivative_extraction_policy_sha256") != extraction_policy_sha):
        errors.append("PUBLIC_MANIFEST_BINDING")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        return ["PUBLIC_MANIFEST_ENTRIES_INVALID"], {}
    seen_sources: set[str] = set()
    seen_derivatives: set[str] = set()
    collections: set[str] = set()
    placements = 0
    segments = 0
    for entry in entries:
        if not isinstance(entry, dict):
            errors.append("PUBLIC_MANIFEST_ENTRIES_INVALID")
            continue
        source_sha = entry.get("source_content_sha256")
        derivative_sha = entry.get("derivative_content_sha256")
        if (not isinstance(source_sha, str) or not _is_sha(source_sha)
                or source_sha not in packets or not isinstance(derivative_sha, str)
                or not _is_sha(derivative_sha) or derivative_sha == source_sha
                or source_sha in seen_sources or derivative_sha in seen_derivatives):
            errors.append("PUBLIC_MANIFEST_IDENTITY")
            continue
        record = records.get(source_sha, {})
        packet = packets.get(source_sha, {})
        receipt = derivative_receipts.get(source_sha, {})
        seen_sources.add(source_sha)
        seen_derivatives.add(derivative_sha)
        if (set(entry) != {"source_content_sha256", "derivative_content_sha256",
                           "derivative_receipt_sha256", "media_type",
                           "private_candidate_relpath", "collections", "citation",
                           "source_disposition", "derivative_disposition"}
                or entry.get("media_type") != "text/plain; charset=utf-8"
                or entry.get("private_candidate_relpath") != f"candidates/{derivative_sha}.txt"
                or entry.get("original_pdf_public") is True
                or entry.get("full_pdf_download_allowed") is True):
            errors.append("PUBLIC_MANIFEST_PDF_EXPOSED")
        if (record.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"
                or record.get("final_disposition") != "REPLACE_WITH_NEW_CONTENT"
                or record.get("derivative_disposition") != "APPROVE_PUBLIC"
                or record.get("derivative_content_sha256") != derivative_sha
                or record.get("derivative_receipt_sha256") != entry.get("derivative_receipt_sha256")
                or entry.get("source_disposition") != "REPLACE_WITH_NEW_CONTENT"
                or entry.get("derivative_disposition") != "APPROVE_PUBLIC"
                or receipt.get("derivative_content_sha256") != derivative_sha):
            errors.append("PUBLIC_MANIFEST_DECISION_MISMATCH")
        expected_collections = sorted({
            str(placement["collection"]) for placement in packet.get("placements", [])
            if isinstance(placement, dict) and isinstance(placement.get("collection"), str)
        })
        actual_collections = entry.get("collections")
        if actual_collections != expected_collections or not expected_collections:
            errors.append("PUBLIC_MANIFEST_COLLECTION_SCOPE")
        else:
            collections.update(actual_collections)
            placements += len(packet.get("placements", []))
        attribution = _mapping(receipt.get("source_attribution"))
        citation = _mapping(entry.get("citation"))
        if (not all(citation.get(key) == attribution.get(key) for key in (
                "source_uri", "source_label", "source_updated_at", "licensor",
                "licence_id", "derivative_notice", "source_date_kind"))):
            errors.append("PUBLIC_MANIFEST_CITATION")
        pages = receipt.get("pages")
        if not isinstance(pages, list):
            errors.append("PUBLIC_MANIFEST_SEGMENTS")
        else:
            segments += sum(len(_mapping(page).get("review_groups", [])) for page in pages)
    expected_excluded = sorted(set(packets) - seen_sources)
    approved_sources = {
        sha for sha, record in records.items()
        if record.get("derivative_disposition") == "APPROVE_PUBLIC"
    }
    if seen_sources != approved_sources:
        errors.append("PUBLIC_MANIFEST_APPROVAL_SET_MISMATCH")
    if manifest.get("excluded_source_sha256") != expected_excluded:
        errors.append("PUBLIC_MANIFEST_EXCLUSIONS")
    if collections != source_collections or len(collections) != required_collections:
        errors.append("PUBLIC_RELEASE_EMPTY_COLLECTION")
    if not entries or not segments:
        errors.append("PUBLIC_RELEASE_EMPTY_COLLECTION")
    population = {"collections": len(collections), "artifacts": len(seen_derivatives),
                  "placements": placements, "derivative_segments": segments,
                  "source_pdfs": len(packets), "original_pdf_public_count": 0}
    manifest_counts = {"source_pdfs": len(packets), "public_collections": len(collections),
                       "public_derivative_artifacts": len(seen_derivatives),
                       "public_placements": placements,
                       "public_derivative_segments": segments,
                       "original_pdf_public_count": 0}
    if manifest.get("counts") != manifest_counts:
        errors.append("PUBLIC_MANIFEST_COUNTS")
    return sorted(set(errors)), population


def _official_listing_url(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        return (parsed.scheme == "https" and parsed.hostname == "eduscol.education.gouv.fr"
                and parsed.username is None and parsed.password is None
                and parsed.port in (None, 443))
    except ValueError:
        return False


def _official_pdf_url(value: Any) -> bool:
    return (_official_listing_url(value)
            and urllib.parse.urlsplit(value).path.lower().endswith(".pdf"))


def _utc_not_future(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        observed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return observed.tzinfo is not None and observed <= datetime.now(timezone.utc)
    except ValueError:
        return False


def _retraction_notice_near_anchor(html: bytes, pdf_url: str) -> bool:
    source = html.decode("utf-8", errors="replace")
    needle = urllib.parse.urlsplit(pdf_url).path.rsplit("/", 1)[-1]
    position = source.find(needle)
    if position < 0:
        return True
    vicinity = source[max(0, position - 250):position + len(needle) + 250]
    plain = re.sub(r"<[^>]*>", " ", vicinity)
    normalized = _normalized_terms(plain.encode("utf-8"))
    return any(signal in normalized for signal in (
        "retire", "revoque", "abroge", "supprime", "obsolete", "caduc",
        "ne plus utiliser", "remplace", "withdrawn", "removed",
    ))


class _IndependentPdfAnchors(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.anchors: list[dict[str, Any]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            raw = dict(attrs).get("href")
            url = urllib.parse.urljoin(self.base_url, raw) if raw else None
            self._href = url if _official_pdf_url(url) else None
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.anchors.append({"href": self._href,
                                 "label": " ".join(" ".join(self._parts).split()),
                                 "occurrence_index": len(self.anchors)})
            self._href = None
            self._parts = []


def _verify_source_provenance(
    record: dict, packet: dict, root: Path, evidence_root: Path,
    mirror_root: Path, inventory_sha: str, authority_sha: str,
    source_checker_sha: str,
    fetch: Callable[[str, int], bytes] = _live_source_bytes,
    *, allow_unproven: bool = False,
) -> tuple[list[str], dict]:
    """Relit checkpoint, capture d'ancre et PDF distant exact ; aucune inférence depuis 403."""
    errors: list[str] = []
    sha = packet.get("content_sha256")
    try:
        checkpoint_path = evidence_root / "provenance/checkpoints" / f"{sha}.json"
        checkpoint, raw = _read_json(checkpoint_path)
        digest = checkpoint.get("checkpoint_sha256")
        unsigned = dict(checkpoint)
        unsigned.pop("checkpoint_sha256", None)
        if (raw != canonical_json_bytes(checkpoint)
                or not _is_sha(digest)
                or _sha256(canonical_json_bytes(unsigned)) != digest
                or _sha256(raw) != record.get("source_receipt_sha256")):
            errors.append("SOURCE_CHECKPOINT_DIGEST")
        if (checkpoint.get("kind") != "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1"
                or checkpoint.get("content_sha256") != sha
                or checkpoint.get("inventory_sha256") != inventory_sha
                or checkpoint.get("authority_yaml_sha256") != authority_sha
                or checkpoint.get("source_checker_code_sha256") != source_checker_sha
                or checkpoint.get("source_listing_url") != packet.get("source_listing_url")):
            errors.append("SOURCE_CHECKPOINT_BINDING")
        if not _utc_not_future(checkpoint.get("checked_at_utc")):
            errors.append("SOURCE_CHECKPOINT_TIME_INVALID")
        provenance = _mapping(checkpoint.get("source_provenance"))
        if (provenance.get("status") != "EXACT_CURRENT_SOURCE"
                or checkpoint.get("rights_basis_kind") != "SITEWIDE_DOWNLOAD_AUTHORITY"
                or checkpoint.get("rights_basis_status") != "CANDIDATE_PENDING_FINAL_APPROVAL"):
            if not allow_unproven:
                errors.append("SOURCE_PROVENANCE_NOT_EXACT")
            return sorted(set(errors)), checkpoint
        listing_url = packet.get("source_listing_url")
        if not _official_listing_url(listing_url):
            errors.append("SOURCE_LISTING_ORIGIN_INVALID")
        direct_source = _official_pdf_url(listing_url)
        discovered = provenance.get("discovered_official_listing_url")
        if discovered is not None and (
            not direct_source or not _official_listing_url(discovered)
            or _official_pdf_url(discovered)
        ):
            errors.append("SOURCE_DISCOVERED_LISTING_INVALID")
        capture_listing_url = discovered if direct_source and discovered else listing_url
        matched = provenance.get("matched_anchor")
        listing_html: bytes | None = None
        listing_observed: str | None = None
        listing_receipt_sha = provenance.get("listing_capture_receipt_sha256")
        if direct_source and not discovered:
            if matched is not None:
                errors.append("SOURCE_DIRECT_PDF_ANCHOR_FORGED")
            pdf_url = listing_url
        else:
            rel = provenance.get("listing_capture_receipt_relpath")
            listing_root = evidence_root / "provenance/listings"
            try:
                capture_path = (_secure_path(root, rel)
                                if isinstance(rel, str) and rel.startswith("docs/")
                                else _secure_path(evidence_root, rel))
                if capture_path.parent != listing_root.resolve():
                    raise ValueError("listing capture outside allowed directory")
                capture, capture_raw = _read_json(capture_path)
                if _sha256(capture_raw) != provenance.get("listing_capture_receipt_sha256"):
                    errors.append("SOURCE_LISTING_CAPTURE_DIGEST")
                if (capture.get("kind") != "NEXUS_EDUSCOL_LISTING_BROWSER_CAPTURE_V1"
                        or capture.get("requested_url") != capture_listing_url
                        or capture.get("http_status") != 200
                        or not _official_listing_url(capture.get("final_url"))
                        or not _utc_not_future(capture.get("observed_at_utc"))
                        or capture.get("browser") != "chromium"
                        or not _is_nonempty(capture.get("browser_version"))
                        or not _is_nonempty(capture.get("playwright_version"))
                        or capture.get("capture_script_sha256") != _sha256(
                            (root / "scripts/go_live/capture_eduscol_source_listings.py").read_bytes())):
                    errors.append("SOURCE_LISTING_CAPTURE_ORIGIN")
                files: dict[str, bytes] = {}
                for kind, name_key, hash_key in (
                    ("html", "normalized_html_file", "normalized_html_sha256"),
                    ("text", "extracted_text_file", "extracted_text_sha256"),
                    ("png", "screenshot_file", "screenshot_sha256"),
                ):
                    name = capture.get(name_key)
                    if not isinstance(name, str) or Path(name).name != name:
                        raise ValueError("invalid listing filename")
                    files[kind] = (listing_root / name).read_bytes()
                    if _sha256(files[kind]) != capture.get(hash_key):
                        errors.append("SOURCE_LISTING_CAPTURE_DIGEST")
                if not files["png"].startswith(b"\x89PNG\r\n\x1a\n"):
                    errors.append("SOURCE_LISTING_CAPTURE_FORMAT")
                parser = _IndependentPdfAnchors(capture["final_url"])
                parser.feed(files["html"].decode("utf-8"))
                if (capture.get("pdf_links") != parser.anchors
                        or capture.get("pdf_link_count") != len(parser.anchors)
                        or matched not in parser.anchors):
                    errors.append("SOURCE_LISTING_ANCHOR_MISMATCH")
                pdf_url = _mapping(matched).get("href")
                if direct_source and pdf_url != listing_url:
                    errors.append("SOURCE_DISCOVERED_ANCHOR_MISMATCH")
                listing_html = files["html"]
                listing_observed = capture.get("observed_at_utc")
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                errors.append("SOURCE_LISTING_CAPTURE_MISSING")
                pdf_url = None
        pdf = _mapping(provenance.get("pdf_fetch"))
        if (not _official_pdf_url(pdf_url)
                or pdf.get("requested_url") != pdf_url
                or not _official_pdf_url(pdf.get("final_url"))
                or pdf.get("http_status") != 200
                or pdf.get("content_sha256") != sha
                or pdf.get("byte_count") != record.get("byte_size")
                or record.get("source_uri") != pdf.get("final_url")):
            errors.append("SOURCE_PDF_BINDING")
        try:
            observed = datetime.fromisoformat(str(pdf.get("observed_at_utc")).replace("Z", "+00:00"))
            if observed.tzinfo is None or observed > datetime.now(timezone.utc):
                errors.append("SOURCE_PDF_OBSERVED_DATE")
        except ValueError:
            errors.append("SOURCE_PDF_OBSERVED_DATE")
        updated = _mapping(provenance.get("source_updated_at"))
        date_kind = updated.get("kind")
        if (date_kind not in {"PDF_EXPLICIT_UPDATE_DATE", "OFFICIAL_RESOURCE_UPDATE_DATE",
                         "DATED_OFFICIAL_SNAPSHOT"}
                or not _is_nonempty(updated.get("date"))
                or not isinstance(updated.get("evidence_ref"), dict)):
            errors.append("SOURCE_ATTRIBUTION_DATE_MISSING")
        elif date_kind == "DATED_OFFICIAL_SNAPSHOT":
            expected_ref = {"pdf_url": pdf.get("final_url"),
                            "downloaded_sha256": sha, "http_status": 200,
                            "listing_capture_receipt_sha256": listing_receipt_sha}
            if (updated.get("date") != pdf.get("observed_at_utc")
                    or updated.get("evidence_ref") != expected_ref):
                errors.append("SOURCE_SNAPSHOT_DATE_MISMATCH")
        else:
            # Une date éditoriale exige la lecture indépendante du bloc PDF ou
            # de la notice ressource qui l'attache à cet artefact exact.
            errors.append("SOURCE_DATE_EVIDENCE_UNVERIFIED")
        currentness_ref = {"pdf_url": pdf.get("final_url"), "pdf_sha256": sha,
                           "listing_capture_receipt_sha256": listing_receipt_sha}
        if (provenance.get("currentness_status") != "PASS"
                or provenance.get("currentness_observed_at_utc") != pdf.get("observed_at_utc")
                or provenance.get("currentness_evidence_ref") != currentness_ref):
            errors.append("SOURCE_CURRENTNESS_PROOF_MISMATCH")
        expected_retracted = (True if listing_html is None or not isinstance(pdf_url, str)
                              else _retraction_notice_near_anchor(listing_html, pdf_url))
        revocation_ref = {"listing_capture_receipt_sha256": listing_receipt_sha,
                          "pdf_url": pdf.get("final_url"), "pdf_sha256": sha,
                          "notice_scan": "ANCHOR_NEIGHBORHOOD_V1"}
        if (expected_retracted
                or provenance.get("retraction_notice_associated") is not False
                or provenance.get("listing_observed_at_utc") != listing_observed
                or provenance.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION"
                or provenance.get("revocation_observed_at_utc") != listing_observed
                or provenance.get("revocation_evidence_ref") != revocation_ref):
            errors.append("SOURCE_REVOCATION_PROOF_MISMATCH")
        try:
            exact_pdf = fetch(pdf["final_url"], 16 * 1024 * 1024)
            mirror = _secure_path(mirror_root, packet.get("source_path")).read_bytes()
            if (exact_pdf != mirror or _sha256(exact_pdf) != sha
                    or len(exact_pdf) != pdf.get("byte_count")):
                errors.append("SOURCE_CURRENT_PDF_SHA_MISMATCH")
        except (OSError, ValueError, KeyError):
            errors.append("SOURCE_CURRENT_PDF_UNVERIFIABLE")
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return ["SOURCE_CHECKPOINT_MISSING"], {}
    return sorted(set(errors)), checkpoint


def _verify_derivative_receipt_cas(
    record: dict, packet: dict, evidence_root: Path,
    adjudication_policy_sha: str, extraction_policy_sha: str,
    builder_code_sha: str,
) -> tuple[list[str], dict]:
    """Contrôle le reçu et le checkpoint privé pour chaque source, y compris EXCLUDE."""
    errors: list[str] = []
    digest = record.get("derivative_receipt_sha256")
    sha = packet.get("content_sha256")
    if not isinstance(digest, str) or not _is_sha(digest) or not _is_sha(sha):
        return ["DERIVATIVE_RECEIPT_MISSING"], {}
    try:
        path = evidence_root / "derivative_receipts" / digest[:2] / f"{digest}.json"
        receipt, raw = _read_json(path)
        if raw != _compact_json_bytes(receipt) or _sha256(raw) != digest:
            errors.append("DERIVATIVE_RECEIPT_DIGEST")
        checkpoint, checkpoint_raw = _read_json(
            evidence_root / "derivatives" / f"{sha}.json"
        )
        if checkpoint_raw != _compact_json_bytes(checkpoint):
            errors.append("DERIVATIVE_CHECKPOINT_CANONICAL")
        if (checkpoint.get("kind") != "NEXUS-STUDENT-DERIVATIVE-CHECKPOINT-V1"
                or checkpoint.get("source_content_sha256") != sha
                or checkpoint.get("derivative_receipt_sha256") != digest
                or checkpoint.get("derivative_content_sha256")
                != record.get("derivative_content_sha256")
                or checkpoint.get("status") != receipt.get("status")
                or checkpoint.get("candidate_relpath") != receipt.get("candidate_relpath")):
            errors.append("DERIVATIVE_CHECKPOINT_MISMATCH")
        if (receipt.get("kind") != "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1"
                or receipt.get("source_content_sha256") != sha
                or receipt.get("source_packet_artifact_sha256")
                != _sha256(_compact_json_bytes(packet))
                or receipt.get("adjudication_policy_sha256") != adjudication_policy_sha
                or receipt.get("extraction_policy_sha256") != extraction_policy_sha
                or receipt.get("generator_code_sha256") != builder_code_sha
                or receipt.get("publication_authorized") is not False):
            errors.append("DERIVATIVE_RECEIPT_BINDING")
        if record.get("derivative_disposition") == "EXCLUDE":
            status = receipt.get("status")
            derivative_sha = receipt.get("derivative_content_sha256")
            if (status not in {"EXCLUDE", "PREPARED_PRIVATE"}
                    or (status == "EXCLUDE" and (
                        derivative_sha is not None or receipt.get("candidate_relpath") is not None
                        or not receipt.get("reason_codes")))
                    or (status == "PREPARED_PRIVATE" and (
                        not _is_sha(derivative_sha) or derivative_sha == sha
                        or receipt.get("candidate_relpath") != f"candidates/{derivative_sha}.txt"))
                    or derivative_sha != record.get("derivative_content_sha256")):
                errors.append("DERIVATIVE_EXCLUSION_RECEIPT_INVALID")
        elif (receipt.get("status") != "PREPARED_PRIVATE"
              or receipt.get("derivative_content_sha256")
              != record.get("derivative_content_sha256")):
            errors.append("DERIVATIVE_CANDIDATE_RECEIPT_INVALID")
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return ["DERIVATIVE_RECEIPT_MISSING"], {}
    return sorted(set(errors)), receipt


def _verify_approval_source_proof(
    record: dict, packet_artifact: dict, evidence_root: Path,
    fetch: Callable[[str, int], bytes] = _live_source_bytes,
) -> list[str]:
    """Rejoue octets PDF/termes en direct ; actualité/révocation restent séparées."""
    error = ["APPROVAL_SOURCE_PROOF_UNVERIFIABLE"]
    digest = record.get("source_receipt_sha256")
    if not isinstance(digest, str) or not _is_sha(digest):
        return error
    path = evidence_root / "source_receipts" / digest[:2] / f"{digest}.json"
    if not path.resolve().is_relative_to(evidence_root.resolve()):
        return error
    try:
        receipt, raw = _read_json(path)
        if raw != canonical_json_bytes(receipt) or _sha256(raw) != digest:
            return error
        pdf = _mapping(receipt.get("pdf"))
        legal = _mapping(receipt.get("legal_terms"))
        license_page = _mapping(receipt.get("license"))
        source = _mapping(record.get("source_verification"))
        if (receipt.get("kind") != "NEXUS-STUDENT-SOURCE-RIGHTS-RECEIPT-V1"
                or receipt.get("transport_kind") != "URLLIB_HTTPS_GET_NO_REDIRECT_V1"
                or receipt.get("rights_scope") != "EDUSCOL_DOWNLOADS_EXCLUDING_THIRD_PARTY"
                or receipt.get("artifact_content_sha256") != packet_artifact.get("content_sha256")
                or receipt.get("listing_uri") != packet_artifact.get("source_listing_url")
                or receipt.get("source_checker_code_sha256") != _sha256(
                    (evidence_root.parents[3] / "scripts/go_live/student_rights_source_check.py").read_bytes())
                or pdf.get("final_uri") != record.get("source_uri")
                or pdf.get("content_sha256") != record.get("content_sha256")
                or pdf.get("http_status") != 200
                or legal.get("final_uri") != SOURCE_LEGAL_URI
                or legal.get("body_sha256") != source.get("terms_sha256")
                or record.get("rights_evidence_uri") != SOURCE_LEGAL_URI
                or record.get("license_or_terms_excerpt_hash") != legal.get("body_sha256")
                or legal.get("observed_at_utc") != source.get("terms_observed_at_utc")
                or legal.get("http_status") != 200
                or license_page.get("final_uri") != SOURCE_LICENSE_URI
                or license_page.get("http_status") != 200
                or not _is_sha(license_page.get("body_sha256"))):
            return error
        for item in (pdf, legal, license_page):
            observed = datetime.fromisoformat(item["observed_at_utc"].replace("Z", "+00:00"))
            if not observed.tzinfo or observed > datetime.now(timezone.utc):
                return error
        exact_pdf = fetch(pdf["final_uri"], 16 * 1024 * 1024)
        legal_body = fetch(SOURCE_LEGAL_URI, 2 * 1024 * 1024)
        license_body = fetch(SOURCE_LICENSE_URI, 2 * 1024 * 1024)
        if (_sha256(exact_pdf) != record.get("content_sha256")
                or _sha256(legal_body) != legal.get("body_sha256")
                or _sha256(license_body) != license_page.get("body_sha256")):
            return error
        legal_text = _visible_terms(legal_body)
        license_text = _visible_terms(license_body)
        if (any(phrase in legal_text for phrase in (
                "licence etalab-2.0 ne s'applique plus",
                "licence etalab-2.0 retiree",
                "documents proposes en telechargement exclus de la licence"))
                or not all(phrase in legal_text for phrase in (
                "documents proposes en telechargement", "licence etalab-2.0",
                "sont exclus", "tiers"))
                or not all(phrase in license_text for phrase in (
                    "licence ouverte 2.0", "reproduire", "extraire",
                    "mentionner la paternite", "date de la derniere mise a jour"))):
            return error
        # Ce reçu ne documente ni l'actualité de chaque document ni l'absence
        # de révocation. Même avec les octets source concordants, pas d'APPROVE.
        return error
    except Exception:  # noqa: BLE001 - réseau/JSON hostile ; aucun contenu dans les diagnostics
        return error


def _git_source_binding(root: Path, mandate: dict, expected_head: str | None) -> list[str]:
    errors: list[str] = []
    binding = _mapping(mandate.get("source_binding"))
    source_commit = binding.get("source_main_commit_sha")
    source_tree = binding.get("source_main_tree_sha")
    if (not isinstance(source_commit, str) or not _is_git_sha(source_commit)
            or not _is_git_sha(source_tree)):
        return ["SOURCE_GIT_BINDING_MISSING"]
    try:
        tree = subprocess.run(
            ["git", "rev-parse", f"{source_commit}^{{tree}}"], cwd=root,
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root,
            capture_output=True, text=True, timeout=10, check=True,
        ).stdout.strip()
        ancestor = subprocess.run(
            ["git", "merge-base", "--is-ancestor", source_commit, head], cwd=root,
            capture_output=True, timeout=10, check=False,
        ).returncode
        checkout = subprocess.run(
            ["git", "status", "--porcelain=v1", "--untracked-files=all",
             "--ignore-submodules=none"], cwd=root,
            capture_output=True, timeout=30, check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return ["SOURCE_GIT_BINDING_UNVERIFIABLE"]
    if tree != source_tree or ancestor != 0:
        errors.append("SOURCE_GIT_BINDING_MISMATCH")
    if expected_head is not None and head != expected_head:
        errors.append("EXACT_HEAD_MISMATCH")
    if checkout:
        errors.append("CHECKOUT_NOT_CLEAN")
    return errors


def _review_metadata_projection(document: Any, fitz: Any) -> tuple[str, list[bytes], dict]:
    """Reconstitue la projection XMP V2 depuis les octets PDF, sans le reviewer."""
    xml = document.get_xml_metadata()
    if len(xml) > 2_000_000 or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("unsafe XMP")
    entries: list[list[str]] = []
    seen: set[tuple[str, str, str]] = set()
    duplicates = 0
    embedded_images: list[bytes] = []
    namespaces: dict[str, str] = {}
    if xml.strip():
        root = ET.fromstring(xml)
        uris = sorted({
            name[1:].split("}", 1)[0]
            for element in root.iter()
            for name in (element.tag, *element.attrib)
            if name.startswith("{") and "}" in name
        })
        namespaces = {f"n{number}": uri for number, uri in enumerate(uris)}
        aliases = {uri: alias for alias, uri in namespaces.items()}

        def qualified(name: str) -> str:
            if name.startswith("{") and "}" in name:
                uri, local = name[1:].split("}", 1)
                return f"{aliases[uri]}:{local}"
            return name

        for element in root.iter():
            fields: list[tuple[str, str | None]] = [
                ("@" + qualified(key), value)
                for key, value in sorted(element.attrib.items())
            ]
            fields.extend((("#text", element.text), ("#tail", element.tail)))
            for kind, raw_value in fields:
                if raw_value is None or not raw_value.strip():
                    continue
                value = raw_value.strip()
                if kind == "#text" and element.tag.rsplit("}", 1)[-1].lower() == "image":
                    encoded = "".join(value.split())
                    try:
                        image = (base64.b64decode(encoded, validate=True)
                                 if len(encoded) >= 16 and len(encoded) % 4 == 0
                                 else None)
                    except (ValueError, binascii.Error):
                        image = None
                    if image is not None:
                        if not (image.startswith(b"\x89PNG\r\n\x1a\n")
                                or image.startswith(b"\xff\xd8")):
                            raise ValueError("unsupported XMP image")
                        pixmap = fitz.Pixmap(image)
                        if pixmap.width * pixmap.height > 4_000_000:
                            raise ValueError("oversize XMP image")
                        embedded_images.append(image)
                        value = f"[EMBEDDED_IMAGE_SHA256:{_sha256(image)}]"
                entry = (qualified(element.tag), kind, value)
                if entry in seen:
                    duplicates += 1
                    continue
                seen.add(entry)
                entries.append(list(entry))
    projection = "[PDF_METADATA_V2]\n" + json.dumps(
        {"info": document.metadata, "xmp_namespaces": namespaces,
         "xmp_entries": entries}, sort_keys=True, ensure_ascii=False,
    ) + "\n"
    facts = {
        "xmp_full_sha256": _sha256(xml.encode("utf-8")),
        "xmp_projection_sha256": _sha256(projection.encode("utf-8")),
        "xmp_unique_value_count": len(entries),
        "xmp_duplicate_value_count": duplicates,
        "xmp_embedded_image_count": len(embedded_images),
        "xmp_embedded_image_sha256": [_sha256(image) for image in embedded_images],
    }
    return projection, embedded_images, facts


def _review_residual_ocr(extracted: str, ocr: str) -> tuple[str, int]:
    lines = {" ".join(line.casefold().split()) for line in extracted.splitlines()}
    retained: list[str] = []
    removed = 0
    for line in ocr.splitlines(keepends=True):
        normalized = " ".join(line.casefold().split())
        if normalized and normalized in lines:
            removed += 1
        else:
            retained.append(line)
    return "".join(retained), removed


def _reconstruct_review_requests(
    record: dict, packet_artifact: dict, mirror_root: Path,
) -> tuple[dict[tuple[str, int], dict[str, Any]], list[str]]:
    """Recompose les requêtes sans importer le reviewer ni persister le PDF.

    Ce protocole V5 fige segments de 4 000 caractères et rendu vision borné.
    Une évolution du producteur nécessite une version explicite du protocole.
    """
    try:
        import fitz
        from student_rights_pdf_scan import _ocr_text, _render_png

        path = _secure_path(mirror_root, packet_artifact.get("source_path"))
        sha = packet_artifact.get("content_sha256")
        if not _is_sha(sha) or record.get("content_sha256") != sha:
            return {}, ["REVIEW_REQUEST_SOURCE_IDENTITY"]
        before = _sha256(path.read_bytes())
        if before != sha:
            return {}, ["REVIEW_REQUEST_SOURCE_IDENTITY"]
        reviewers = {label: _mapping(record.get(f"reviewer_{label}"))
                     for label in ("a", "b")}
        hashes = {(label, nonce): hashlib.sha256()
                  for label in reviewers for nonce in (0, 1)}
        proofs: dict[tuple[str, int], dict[str, Any]] = {
            key: {"requests": {}} for key in hashes
        }
        with fitz.open(path) as document:
            if (document.is_encrypted or document.embfile_count()
                    or len(document) != packet_artifact.get("page_count")):
                return {}, ["REVIEW_REQUEST_PDF_INVALID"]
            metadata_projection, xmp_images, metadata_facts = (
                _review_metadata_projection(document, fitz)
            )
            assembly: list[dict] = []
            for page_index in range(len(document)):
                page = document.load_page(page_index)
                page_number = page_index + 1
                if page.first_widget is not None:
                    return {}, ["REVIEW_REQUEST_PDF_INVALID"]
                extracted = page.get_text("text", sort=True)
                annotations = []
                for annotation in page.annots() or ():
                    if annotation.type[1] == "FileAttachment":
                        return {}, ["REVIEW_REQUEST_PDF_INVALID"]
                    annotations.append({"type": annotation.type[1], "info": annotation.info})
                links = page.get_links()
                metadata = metadata_projection if page_index == 0 else ""
                page_xmp_images = xmp_images if page_index == 0 else []
                annotation_text = (
                    "\n[ANNOTATIONS_AND_LINKS]\n" + json.dumps(
                        {"annotations": annotations, "links": links},
                        sort_keys=True, ensure_ascii=False, default=str,
                    ) if annotations or links else ""
                )
                graphic = bool(page.get_image_info()) or bool(page.get_drawings()) or bool(annotations)
                ocr = ""
                vision_sha = None
                vision_png = None
                if graphic:
                    png, _ = _render_png(page, fitz)
                    ocr = _ocr_text(png)
                    area = page.rect.width * page.rect.height
                    if area <= 0:
                        return {}, ["REVIEW_REQUEST_VISION_RENDER_INVALID"]
                    scale = min(REVIEW_VISION_RENDER_SCALE,
                                math.sqrt(REVIEW_VISION_MAX_PIXELS / area))
                    for _ in range(8):
                        vision_pixmap = page.get_pixmap(
                            matrix=fitz.Matrix(scale, scale), alpha=False,
                        )
                        if (vision_pixmap.width * vision_pixmap.height
                                <= REVIEW_VISION_MAX_PIXELS):
                            vision_png = vision_pixmap.tobytes("png")
                            break
                        scale *= 0.995
                    if vision_png is None:
                        return {}, ["REVIEW_REQUEST_VISION_RENDER_INVALID"]
                    vision_sha = _sha256(vision_png)
                residual_ocr, removed_ocr_lines = _review_residual_ocr(extracted, ocr)
                combined = metadata + extracted + annotation_text + (
                    "\n[OCR_RESIDUAL]\n" + residual_ocr if residual_ocr else ""
                )
                segments = [combined[start:start + REVIEW_MAX_CHARS_PER_SEGMENT]
                            for start in range(0, len(combined), REVIEW_MAX_CHARS_PER_SEGMENT)] or [""]
                segment_images: dict[int, bytes] = {}
                visual_indices: set[int] = set()
                if graphic:
                    segments.insert(0, f"[PDF_PAGE_RENDER_SHA256:{vision_sha}]\n")
                    visual_indices.add(1)
                    if vision_png is not None:
                        segment_images[1] = vision_png
                for embedded_image in page_xmp_images:
                    image_sha = _sha256(embedded_image)
                    segments.append(f"[XMP_EMBEDDED_IMAGE_SHA256:{image_sha}]\n")
                    visual_indices.add(len(segments))
                    segment_images[len(segments)] = embedded_image
                page_facts = {
                    "page_number": page_number,
                    "assembly_protocol": REVIEW_ASSEMBLY_PROTOCOL,
                    "extracted_text_sha256": _sha256(extracted.encode("utf-8")),
                    "ocr_full_sha256": _sha256(ocr.encode("utf-8")),
                    "ocr_residual_sha256": _sha256(residual_ocr.encode("utf-8")),
                    "ocr_exact_duplicate_lines_removed": removed_ocr_lines,
                    "segment_count": len(segments),
                    "visual_segment_indices": sorted(visual_indices),
                }
                if page_index == 0:
                    page_facts.update(metadata_facts)
                assembly.append(page_facts)
                for label, reviewer in reviewers.items():
                    for nonce in (0, 1):
                        for segment_index, chunk in enumerate(segments, 1):
                            image = segment_images.get(segment_index)
                            segment_image_sha = (
                                _sha256(image) if image is not None
                                and reviewer.get("model_id") in REVIEW_VISION_MODELS
                                else None
                            )
                            payload = {
                                "page_number": page_number, "segment_index": segment_index,
                                "segment_count": len(segments), "page_text_segment": chunk,
                                "page_has_graphics": graphic or bool(page_xmp_images),
                                "review_domain": f"reviewer_{label}",
                            }
                            request = {
                                "content_sha256": sha,
                                "assembly_protocol": REVIEW_ASSEMBLY_PROTOCOL,
                                "reviewer_identity": reviewer.get("identity"),
                                "model_id": reviewer.get("model_id"),
                                "model_version": reviewer.get("model_version"),
                                "parameters_sha256": reviewer.get("parameters_sha256"),
                                "prompt_sha256": reviewer.get("prompt_sha256"),
                                "payload": payload, "image_sha256": segment_image_sha,
                                "run_nonce": nonce,
                            }
                            raw = _compact_json_bytes(request)
                            hashes[(label, nonce)].update(raw)
                            proofs[(label, nonce)]["requests"][(page_number, segment_index)] = {
                                "request_sha256": _sha256(raw),
                                "image_sha256": segment_image_sha,
                                "segment_count": len(segments),
                            }
            if (record.get("assembly_protocol") != REVIEW_ASSEMBLY_PROTOCOL
                    or record.get("text_assembly") != assembly):
                return {}, ["REVIEW_TEXT_ASSEMBLY_MISMATCH"]
        if _sha256(path.read_bytes()) != before:
            return {}, ["REVIEW_REQUEST_PDF_CHANGED"]
        for key, digest in hashes.items():
            proofs[key]["context_sha256"] = digest.hexdigest()
        return proofs, []
    except Exception:  # noqa: BLE001 - erreurs PDF/OCR fail-closed, sans texte dans le diagnostic
        return {}, ["REVIEW_REQUEST_RECONSTRUCTION_FAILED"]


def _verify_review_receipts(
    record: dict, evidence_root: Path,
    request_proofs: dict[tuple[str, int], dict[str, Any]], *, run_nonce: int = 0,
) -> list[str]:
    """Relit chaque reçu CAS A/B et recalcule la couverture et l'agrégat.

    Le contexte de requête contient du texte/une image et n'est pas persisté.
    Il est reconstruit depuis le PDF exact puis comparé à chaque reçu.
    """
    errors: list[str] = []
    page_count = record.get("page_count")
    if type(page_count) is not int or page_count < 1:
        return ["REVIEW_RECEIPT_PAGE_COUNT"]
    expected_pages = set(range(1, page_count + 1))
    assembly_pages = {
        page.get("page_number"): page
        for page in record.get("text_assembly", []) if isinstance(page, dict)
    }
    fields = frozenset({
        "kind", "content_sha256", "reviewer_identity", "page_number",
        "segment_index", "segment_count", "model_id", "model_version",
        "prompt_sha256", "parameters_sha256", "request_sha256", "image_sha256",
        "observation_sha256", "observation", "run_nonce", "assembly_protocol",
    })
    for label in ("a", "b"):
        prefix = f"REVIEWER_{label.upper()}_RECEIPT"
        reviewer = _mapping(record.get(f"reviewer_{label}"))
        expected = _mapping(request_proofs.get((label, run_nonce)))
        expected_requests = _mapping(expected.get("requests"))
        if reviewer.get("context_sha256") != expected.get("context_sha256"):
            errors.append(f"{prefix}_CONTEXT_MISMATCH")
        refs = reviewer.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"{prefix}_MISSING")
            continue
        observations: list[bytes] = []
        positions: list[tuple[int, int]] = []
        page_segments: dict[int, tuple[int, set[int]]] = {}
        rights_notice = False
        for ref in refs:
            digest = ref[7:] if isinstance(ref, str) and ref.startswith("sha256:") else None
            if not isinstance(digest, str) or not _is_sha(digest):
                errors.append(f"{prefix}_REF_INVALID")
                continue
            path = evidence_root / "receipts" / digest[:2] / f"{digest}.json"
            if not path.resolve().is_relative_to(evidence_root.resolve()):
                errors.append(f"{prefix}_PATH_INVALID")
                continue
            try:
                if path.stat().st_size > 1024 * 1024:
                    raise ValueError("oversize receipt")
                receipt, raw = _read_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                errors.append(f"{prefix}_MISSING_OR_INVALID")
                continue
            if raw != _compact_json_bytes(receipt) or _sha256(raw) != digest:
                errors.append(f"{prefix}_DIGEST")
                continue
            observation = receipt.get("observation")
            observation_fields = {
                "page_number", "segment_index", "segment_count", "verdict",
                "confidence", "reason_codes", "evidence_pages", "visual_examined",
            }
            if label == "a":
                observation_fields.add("positive_rights_notice_present")
            page = receipt.get("page_number")
            segment = receipt.get("segment_index")
            segment_count = receipt.get("segment_count")
            if (set(receipt) != fields
                    or receipt.get("kind") != "NEXUS-STUDENT-REVIEW-SEGMENT-RECEIPT-V1"
                    or type(receipt.get("run_nonce")) is not int
                    or receipt.get("run_nonce") != run_nonce
                    or receipt.get("assembly_protocol") != REVIEW_ASSEMBLY_PROTOCOL
                    or receipt.get("content_sha256") != record.get("content_sha256")
                    or any(receipt.get(field) != reviewer.get(field) for field in (
                        "model_id", "model_version", "prompt_sha256", "parameters_sha256"
                    ))
                    or receipt.get("reviewer_identity") != reviewer.get("identity")
                    or not _is_sha(receipt.get("request_sha256"))
                    or (receipt.get("image_sha256") is not None
                        and not _is_sha(receipt.get("image_sha256")))
                    or type(page) is not int or page not in expected_pages
                    or type(segment) is not int or type(segment_count) is not int
                    or segment < 1 or segment_count < 1 or segment > segment_count
                    or not isinstance(observation, dict)
                    or set(observation) != observation_fields
                    or any(observation.get(k) != receipt.get(k) for k in (
                        "page_number", "segment_index", "segment_count"
                    ))
                    or observation.get("evidence_pages") != [page]
                    or observation.get("verdict") not in {"PASS", "FAIL"}
                    or observation.get("confidence") not in {"HIGH", "LOW", "UNKNOWN"}
                    or type(observation.get("visual_examined")) is not bool
                    or (label == "a" and type(observation.get(
                        "positive_rights_notice_present")) is not bool)
                    or not isinstance(observation.get("reason_codes"), list)
                    or not all(isinstance(code, str) and re.fullmatch(
                        r"[A-Z][A-Z0-9_]*", code) for code in observation.get("reason_codes", []))
                    or receipt.get("observation_sha256") != _sha256(
                        _compact_json_bytes(observation))):
                errors.append(f"{prefix}_STRUCTURE")
                continue
            if reviewer.get("verdict") == "PASS":
                visual_segments = _mapping(assembly_pages.get(page)).get(
                    "visual_segment_indices", []
                )
                visual_required = (isinstance(visual_segments, list)
                                   and segment in visual_segments)
                if (observation["verdict"] != "PASS" or observation["confidence"] != "HIGH"
                        or observation["reason_codes"]
                        or (visual_required and (
                            not _is_sha(receipt.get("image_sha256"))
                            or observation["visual_examined"] is not True))):
                    errors.append(f"{prefix}_PASS_UNSUPPORTED")
                if label == "a" and observation["positive_rights_notice_present"] is True:
                    rights_notice = True
            request = _mapping(expected_requests.get((page, segment)))
            if (request.get("image_sha256") is None
                    and observation["visual_examined"] is True):
                errors.append(f"{prefix}_NONVISUAL_CLAIM")
            if (receipt.get("request_sha256") != request.get("request_sha256")
                    or receipt.get("image_sha256") != request.get("image_sha256")
                    or segment_count != request.get("segment_count")):
                errors.append(f"{prefix}_REQUEST_MISMATCH")
            previous = page_segments.get(page)
            if previous is None:
                page_segments[page] = (segment_count, {segment})
            elif previous[0] != segment_count or segment in previous[1]:
                errors.append(f"{prefix}_COVERAGE")
            else:
                previous[1].add(segment)
            positions.append((page, segment))
            observations.append(_compact_json_bytes(observation))
        if (set(page_segments) != expected_pages
                or any(seen != set(range(1, count + 1))
                       for count, seen in page_segments.values())
                or positions != sorted(positions)
                or len(positions) != len(refs)):
            errors.append(f"{prefix}_COVERAGE")
        if _sha256(b"".join(observations)) != reviewer.get("observation_sha256"):
            errors.append(f"{prefix}_AGGREGATE")
        if label == "a" and reviewer.get("verdict") == "PASS" and not rights_notice:
            errors.append(f"{prefix}_RIGHTS_NOTICE")
    return sorted(set(errors))


def _mandate_time_errors(mandate: dict) -> list[str]:
    errors: list[str] = []
    try:
        created = datetime.fromisoformat(mandate["created_at_utc"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(mandate["expires_at_utc"].replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        if not created.tzinfo or not expires.tzinfo or not created <= now < expires:
            errors.append("MANDATE_TIME_INVALID_OR_EXPIRED")
    except (KeyError, AttributeError, TypeError, ValueError):
        errors.append("MANDATE_TIME_INVALID_OR_EXPIRED")
    return errors


def _complete_page_scan(record: dict) -> bool:
    pages = record.get("page_scans")
    count = record.get("page_count")
    if not isinstance(count, int) or isinstance(count, bool) or count < 1:
        return False
    if not isinstance(pages, list) or len(pages) != count:
        return False
    for number, page in enumerate(pages, 1):
        if not isinstance(page, dict) or page.get("page_number") != number:
            return False
        if page.get("scan_complete") is not True or not _is_sha(page.get("text_sha256")):
            return False
        if page.get("annex_page") not in (True, False):
            return False
        graphic = page.get("graphics_detected") is True
        if graphic and (page.get("render_required") is not True
                        or page.get("render_inspected") is not True
                        or not _is_sha(page.get("render_sha256"))
                        or not _is_sha(page.get("ocr_sha256"))):
            return False
        if page.get("render_required") is True and (
            page.get("render_inspected") is not True or not _is_sha(page.get("render_sha256"))
        ):
            return False
        if page.get("ocr_required") is True and (
            page.get("ocr_complete") is not True or not _is_sha(page.get("ocr_sha256"))
        ):
            return False
    return True


def _scan_projection_complete(record: dict) -> bool:
    scan = _mapping(record.get("pdf_scan_evidence"))
    pages = scan.get("pages")
    projected = record.get("page_scans")
    if (scan.get("scanner_kind") != "NEXUS-STUDENT-RIGHTS-PDF-SCAN-V1"
            or scan.get("content_sha256") != record.get("content_sha256")
            or scan.get("exact_bytes_match") is not True
            or scan.get("file_size_bytes") != record.get("byte_size")
            or scan.get("page_count") != record.get("page_count")
            or scan.get("expected_page_count") != record.get("page_count")
            or scan.get("full_document_scan_complete") is not True
            or scan.get("annexes_scan_complete") is not True
            or scan.get("images_and_annexes_checked") is not True
            or scan.get("embedded_file_count") != 0
            or not _is_sha(scan.get("metadata_sha256"))
            or not isinstance(pages, list) or not isinstance(projected, list)
            or len(pages) != len(projected)):
        return False
    for proof, page in zip(pages, projected, strict=True):
        if not isinstance(proof, dict) or not isinstance(page, dict):
            return False
        graphic = any(proof.get(key, 0) > 0 for key in (
            "raster_image_count", "vector_drawing_count", "annotation_count",
        ))
        if (page.get("page_number") != proof.get("page_number")
                or page.get("text_sha256") != proof.get("text_sha256")
                or page.get("render_sha256") != proof.get("render_sha256")
                or page.get("ocr_sha256") != proof.get("ocr_sha256")
                or page.get("annex_page") is not proof.get("annex_page")
                or page.get("graphics_detected") is not graphic
                or page.get("render_required") is not graphic
                or page.get("render_inspected") is not graphic
                or page.get("scan_complete") is not True
                or proof.get("ocr_required") is not graphic
                or proof.get("ocr_complete") is not True):
            return False
    return True


def _dual_review_complete(record: dict) -> bool:
    count = record.get("page_count")
    if not isinstance(count, int) or count < 1:
        return False
    pages = set(range(1, count + 1))
    reviewers = [_mapping(record.get(f"reviewer_{label}")) for label in ("a", "b")]
    return all(
        reviewer.get("complete") is True
        and _is_nonempty(reviewer.get("identity"))
        and isinstance(reviewer.get("pages_covered"), list)
        and all(isinstance(page, int) for page in reviewer["pages_covered"])
        and set(reviewer["pages_covered"]) == pages
        for reviewer in reviewers
    ) and reviewers[0].get("context_sha256") != reviewers[1].get("context_sha256")


def _rescan_pdf(record: dict, packet_artifact: dict, mirror_root: Path) -> list[str]:
    try:
        from student_rights_pdf_scan import PdfScanError, scan_pdf

        path = _secure_path(mirror_root, packet_artifact.get("source_path"))
        fresh = scan_pdf(path, packet_artifact["content_sha256"], packet_artifact["page_count"])
    except (OSError, ValueError, KeyError, PdfScanError):
        return ["PDF_RESCAN_FAILED"]
    if canonical_json_bytes(fresh) != canonical_json_bytes(record.get("pdf_scan_evidence")):
        return ["PDF_RESCAN_MISMATCH"]
    return []


def _check_v2_disposition(record: dict, packet_artifact: dict) -> list[str]:
    """Le PDF source reste privé ; seul un nouvel SHA textuel peut être candidat."""
    errors: list[str] = []
    source = record.get("source_disposition")
    final = record.get("final_disposition")
    derivative = record.get("derivative_disposition")
    source_sha = packet_artifact.get("content_sha256")
    if not _is_sha(record.get("source_receipt_sha256")):
        errors.append("SOURCE_RECEIPT_MISSING")
    if not _is_sha(record.get("derivative_receipt_sha256")):
        errors.append("DERIVATIVE_RECEIPT_MISSING")
    if source == "APPROVE_PUBLIC" or final == "APPROVE_PUBLIC":
        errors.append("SOURCE_PDF_PUBLIC_FORBIDDEN")
    if source not in {"EXCLUDE", "REPLACE_WITH_NEW_CONTENT"}:
        errors.append("SOURCE_DISPOSITION_INVALID")
    if final != source:
        errors.append("SOURCE_DISPOSITION_ALIAS_MISMATCH")
    if derivative not in {"EXCLUDE", "APPROVE_PUBLIC"}:
        errors.append("DERIVATIVE_DISPOSITION_INVALID")
    if source == "REPLACE_WITH_NEW_CONTENT" and derivative != "APPROVE_PUBLIC":
        errors.append("SOURCE_REPLACEMENT_WITHOUT_APPROVED_DERIVATIVE")
    if source == "EXCLUDE" and not record.get("reason_codes"):
        errors.append("EXCLUSION_REASON_MISSING")
    if derivative == "APPROVE_PUBLIC":
        digest = record.get("derivative_content_sha256")
        replacement = _mapping(record.get("replacement"))
        if (source != "REPLACE_WITH_NEW_CONTENT"
                or not _is_sha(digest) or digest == source_sha
                or replacement.get("new_content_sha256") != digest
                or not _is_sha(record.get("derivative_receipt_sha256"))):
            errors.append("DERIVATIVE_IDENTITY_MISSING")
        if (record.get("rights_basis") not in {
                "INDIVIDUAL_EXPLICIT_LICENCE", "SITEWIDE_DOWNLOAD_AUTHORITY"}
                or not _is_sha(record.get("source_receipt_sha256"))
                or not _is_nonempty(record.get("rights_authority_id"))
                or not _is_sha(record.get("rights_authority_sha256"))):
            errors.append("DERIVATIVE_RIGHTS_UNPROVEN")
        if source_sha == CFTR:
            errors.append("CFTR_NOT_EXCLUDED")
    elif record.get("derivative_content_sha256") is not None and (
        not _is_sha(record.get("derivative_content_sha256"))
        or record.get("derivative_content_sha256") == source_sha
    ):
        errors.append("EXCLUDED_DERIVATIVE_IDENTITY_INVALID")
    if source_sha == CFTR and (
        source != "EXCLUDE" or final != "EXCLUDE"
        or derivative != "EXCLUDE" or record.get("student_suitability") != "FAIL"
        or 3 not in (record.get("evidence_pages") or [])
        or "TEACHER_NON_DISCLOSURE_INSTRUCTION" not in (record.get("reason_codes") or [])
    ):
        errors.append("CFTR_NOT_EXCLUDED")
    return errors


def check_artifact(
    record: dict, packet_artifact: dict, policy: dict, mandate: dict,
    expected_bindings: dict,
) -> list[str]:
    """Recalcule les contraintes de sûreté, sans appeler l'adjudicateur."""
    errors: list[str] = []
    sha = packet_artifact.get("content_sha256")
    if (not _is_sha(sha) or record.get("content_sha256") != sha
            or record.get("artifact_id") != sha
            or _mapping(record.get("bindings")).get("pdf_sha256") != sha):
        errors.append("CONTENT_IDENTITY")
    if record.get("page_count") != packet_artifact.get("page_count"):
        errors.append("PAGE_COUNT_MISMATCH")
    if not isinstance(record.get("byte_size"), int) or record["byte_size"] < 1:
        errors.append("BYTE_SIZE_MISSING")
    if (not _complete_page_scan(record) or not _scan_projection_complete(record)
            or record.get("scan_complete") is not True or (
        record.get("images_and_annexes_checked") is not True
    )):
        errors.append("FULL_SCAN_INCOMPLETE")
    bindings = _mapping(record.get("bindings"))
    for key, expected in expected_bindings.items():
        if bindings.get(key) != expected:
            errors.append(f"BINDING_{key.upper()}")
    if record.get("individual_human_review_claimed") is not False:
        errors.append("FALSE_HUMAN_REVIEW")
    if (record.get("decision_executor") != mandate.get("decision_executor")
            or record.get("delegation_id") != mandate.get("delegation_id")):
        errors.append("DELEGATION_IDENTITY")
    if (policy.get("authorized_use") != "student_retrieval_excerpt_only"
            or policy.get("full_pdf_redistribution_allowed") is not False
            or policy.get("answer_generation_allowed") is not False
            or mandate.get("authorized_use") != "student_retrieval_excerpt_only"
            or mandate.get("full_pdf_redistribution_allowed") is not False
            or mandate.get("answer_generation_allowed") is not False):
        errors.append("PUBLIC_USE_SCOPE_INVALID")
    if record.get("record_kind") == "NEXUS_AUTOMATED_ARTIFACT_REVIEW_V2":
        errors.extend(_check_v2_disposition(record, packet_artifact))
        return sorted(set(errors))
    disposition = record.get("final_disposition")
    if disposition not in DISPOSITIONS:
        errors.append("DISPOSITION_INVALID")
    if disposition == "EXCLUDE" and not record.get("reason_codes"):
        errors.append("EXCLUSION_REASON_MISSING")

    count = record.get("page_count")
    expected_pages = set(range(1, count + 1)) if isinstance(count, int) and count > 0 else set()
    reviewers = []
    for label in ("a", "b"):
        reviewer = _mapping(record.get(f"reviewer_{label}"))
        reviewers.append(reviewer)
        if (not _is_nonempty(reviewer.get("identity"))
                or not _is_nonempty(reviewer.get("model_id"))
                or not _is_nonempty(reviewer.get("model_version"))
                or not _is_sha(reviewer.get("prompt_sha256"))
                or not _is_sha(reviewer.get("parameters_sha256"))
                or not _is_sha(reviewer.get("context_sha256"))
                or not _is_sha(reviewer.get("observation_sha256"))
                or reviewer.get("complete") is not True
                or not isinstance(reviewer.get("pages_covered"), list)
                or not all(isinstance(page, int) for page in reviewer.get("pages_covered", []))
                or set(reviewer.get("pages_covered", [])) != expected_pages):
            errors.append(f"REVIEWER_{label.upper()}_INCOMPLETE")
    if (reviewers[0].get("identity") == reviewers[1].get("identity")
            or reviewers[0].get("context_sha256") == reviewers[1].get("context_sha256")):
        errors.append("REVIEWERS_NOT_INDEPENDENT")

    if sha == CFTR and (
        disposition != "EXCLUDE" or record.get("student_suitability") != "FAIL"
        or 3 not in (record.get("evidence_pages") or [])
        or "TEACHER_NON_DISCLOSURE_INSTRUCTION" not in (record.get("reason_codes") or [])
    ):
        errors.append("CFTR_NOT_EXCLUDED")
    if disposition == "APPROVE_PUBLIC":
        checks = _mapping(record.get("checks"))
        rights_basis = record.get("rights_basis")
        allowed = _mapping(policy.get("rights_bases")).get("accepted")
        if (not isinstance(rights_basis, str) or rights_basis not in RIGHTS_BASES
                or not isinstance(allowed, list)
                or not all(isinstance(basis, str) for basis in allowed)
                or rights_basis not in allowed or not set(allowed) <= RIGHTS_BASES):
            errors.append("APPROVAL_RIGHTS_BASIS")
        if (not _is_nonempty(record.get("rights_evidence_uri"))
                or not _is_sha(record.get("license_or_terms_excerpt_hash"))
                or not isinstance(record.get("evidence_pages"), list)
                or not record.get("evidence_pages")
                or not set(record["evidence_pages"]) <= expected_pages):
            errors.append("APPROVAL_EVIDENCE_PAGES")
        if any(checks.get(k) is not True for k in TRUE_CHECKS) or any(
            checks.get(k) is not False for k in FALSE_CHECKS
        ):
            errors.append("APPROVAL_PREDICATES")
        source = _mapping(record.get("source_verification"))
        if (source.get("status") != "VERIFIED" or source.get("http_status") != 200
                or source.get("exact_pdf_uri") != record.get("source_uri")
                or source.get("final_uri") != record.get("source_uri")
                or source.get("remote_pdf_sha256") != sha
                or source.get("listing_uri") != packet_artifact.get("source_listing_url")
                or not _is_nonempty(source.get("terms_uri"))
                or not _is_sha(source.get("terms_sha256"))
                or not _is_nonempty(source.get("terms_observed_at_utc"))
                or not _is_nonempty(source.get("source_last_updated_at_utc"))
                or not _is_nonempty(source.get("revocation_evidence_uri"))):
            errors.append("APPROVAL_SOURCE_MISMATCH")
        if (record.get("third_party_status") != "CLEARED_WITH_EVIDENCE"
                or any(record.get(k) != "PASS" for k in (
                    "pii_status", "currentness_status", "revocation_status",
                    "student_suitability",
                ))):
            errors.append("APPROVAL_SAFETY_STATUS")
        if any(r.get("verdict") != "PASS" or r.get("confidence") != "HIGH"
               or not isinstance(r.get("evidence_refs"), list)
               or not r.get("evidence_refs") for r in reviewers):
            errors.append("APPROVAL_DUAL_REVIEW")
        replays = record.get("candidate_replays")
        if (not isinstance(replays, list) or len(replays) != 2
                or not all(isinstance(r, dict) for r in replays)
                or [r.get("run_index") for r in replays] != [1, 2]
                or [r.get("run_nonce") for r in replays] != [0, 1]
                or any(r.get("candidate_verdict") != "PASS" for r in replays)
                or len({(r.get("reviewer_a_observation_sha256"),
                         r.get("reviewer_b_observation_sha256")) for r in replays}) != 1):
            errors.append("APPROVAL_REPLAY_DIVERGENCE")
        else:
            for label, reviewer in zip(("a", "b"), reviewers, strict=True):
                prefix = f"reviewer_{label}"
                if (replays[0].get(f"{prefix}_observation_sha256") != reviewer.get("observation_sha256")
                        or replays[0].get(f"{prefix}_context_sha256") != reviewer.get("context_sha256")
                        or replays[0].get(f"{prefix}_evidence_refs") != reviewer.get("evidence_refs")
                        or replays[1].get(f"{prefix}_observation_sha256") != reviewer.get("observation_sha256")
                        or replays[1].get(f"{prefix}_context_sha256") == reviewer.get("context_sha256")
                        or not isinstance(replays[1].get(f"{prefix}_evidence_refs"), list)
                        or not replays[1].get(f"{prefix}_evidence_refs")
                        or replays[1].get(f"{prefix}_evidence_refs") == reviewer.get("evidence_refs")):
                    errors.append("APPROVAL_REPLAY_DIVERGENCE")
        if record.get("deterministic_policy_verdict") != "PASS":
            errors.append("APPROVAL_POLICY_VERDICT")
        if record.get("reason_codes"):
            errors.append("APPROVAL_UNRESOLVED_REASON")
    elif disposition == "REPLACE_WITH_NEW_CONTENT":
        replacement = _mapping(record.get("replacement"))
        if (not _is_sha(replacement.get("new_content_sha256"))
                or replacement.get("new_content_sha256") == sha
                or not _is_nonempty(replacement.get("qualified_substitute_evidence_uri"))
                or replacement.get("full_new_artifact_pipeline_pass") is not True):
            errors.append("REPLACEMENT_NOT_QUALIFIED")
    return sorted(set(errors))


def _signal_pages(packet: dict) -> str:
    signals = packet.get("automated_review_signals") or []
    if not signals:
        return "NONE_DETECTED"
    return ",".join(f"{signal['kind']}:p{signal['page']}" for signal in signals)


def render_decision_sheet(items: list[tuple[dict, dict, str]]) -> bytes:
    """Projette les faits structurés vers la feuille de #300, triée par SHA."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=SHEET_COLUMNS, delimiter="\t", lineterminator="\n")
    writer.writeheader()
    for record, packet, evidence_sha in sorted(items, key=lambda item: item[0]["content_sha256"]):
        checks = _mapping(record.get("checks"))
        v2 = record.get("record_kind") == "NEXUS_AUTOMATED_ARTIFACT_REVIEW_V2"
        rights_pass = (
            record.get("derivative_disposition") == "APPROVE_PUBLIC"
            and record.get("rights_basis") in {
                "INDIVIDUAL_EXPLICIT_LICENCE", "SITEWIDE_DOWNLOAD_AUTHORITY"}
            and _is_sha(record.get("rights_authority_sha256"))
        ) if v2 else (record.get("rights_basis") in RIGHTS_BASES and (
            record.get("reviewer_a", {}).get("verdict") == "PASS"
        ))
        student_pass = (record.get("derivative_disposition") == "APPROVE_PUBLIC") if v2 else (
            record.get("reviewer_b", {}).get("verdict") == "PASS" and (
                checks.get("student_suitability_pass") is True
            )
        )
        pages = record.get("evidence_pages") or []
        writer.writerow({
            "content_sha256": record["content_sha256"],
            "source_release": packet.get("source_release", ""),
            "collections": ",".join(sorted({p["collection"] for p in packet.get("placements", [])})),
            "source_path": packet.get("source_path", ""),
            "source_listing_url": packet.get("source_listing_url", ""),
            "page_count": packet.get("page_count", ""),
            "source_pii_status": packet.get("source_pii_status", ""),
            "source_currentness_disposition": packet.get("source_currentness_disposition", ""),
            "automated_signal_pages": _signal_pages(packet),
            "explicit_student_exclusion_signal": str(packet.get("explicit_student_exclusion_signal", False)).lower(),
            "rights_review": ("PUBLIC_DERIVATIVE_RIGHTS_CONFIRMED" if v2
                              else "PUBLIC_RIGHTS_CONFIRMED") if rights_pass else "BLOCKED",
            "student_suitability": ("STUDENT_DERIVATIVE_APPROVED" if student_pass
                                    else "STUDENT_BLOCKED") if v2 else (
                                        "STUDENT_APPROVED" if student_pass else "STUDENT_BLOCKED"),
            "third_party_exception_review": "CLEARED_WITH_EVIDENCE" if (student_pass and v2) or record.get("third_party_status") == "CLEARED_WITH_EVIDENCE" else "BLOCKED",
            "pii_recheck": "PASS_WITH_EVIDENCE" if (student_pass and v2) or checks.get("pii_gate_pass") is True else "FAIL",
            "currentness_recheck": "PASS_WITH_EVIDENCE" if (student_pass and v2) or checks.get("currentness_gate_pass") is True else "FAIL",
            "revocation_recheck": "PASS_WITH_EVIDENCE" if (student_pass and v2) or checks.get("revocation_gate_pass") is True else "FAIL",
            "student_public_disposition": record.get("final_disposition", ""),
            "rights_evidence_ref": (
                "https://eduscol.education.gouv.fr/4656/mentions-legales"
                if v2 and record.get("rights_authority_id") == "EDUSCOL_ETALAB_2_0_SITEWIDE"
                else record.get("rights_evidence_uri") or ""
            ),
            "decision_evidence_pages": ",".join(str(page) for page in sorted(pages)),
            "decision_reason": ",".join(sorted(record.get("reason_codes") or [])),
            "human_reviewer": "",
            "reviewed_at_utc": record.get("decided_at_utc", ""),
            "decision_executor": record.get("decision_executor", ""),
            "delegation_id": record.get("delegation_id", ""),
            "evidence_sha256": evidence_sha,
            "source_disposition": record.get("source_disposition", ""),
            "derivative_disposition": record.get("derivative_disposition", ""),
            "derivative_content_sha256": record.get("derivative_content_sha256") or "",
            "derivative_receipt_sha256": record.get("derivative_receipt_sha256") or "",
            "rights_authority_id": record.get("rights_authority_id") or ("NONE" if v2 else ""),
            "rights_authority_sha256": record.get("rights_authority_sha256") or (
                "NONE" if v2 else ""),
        })
    return buffer.getvalue().encode("utf-8")


def _source_population(root: Path, index: dict, inventory: dict) -> tuple[dict, set[str], list[str]]:
    """Recompte la seule union V4 non-HGGSP + V5 HGGSP scellée par octets."""
    errors: list[str] = []
    sources = index.get("source_population")
    if not isinstance(sources, list) or len(sources) != 2:
        return {}, set(), ["SOURCE_POPULATION_MISSING"]
    expected_releases = {"v4_non_hggsp": 9, "v5_hggsp": 2}
    if {s.get("source_release") for s in sources if isinstance(s, dict)} != set(expected_releases):
        return {}, set(), ["SOURCE_RELEASE_SET_INVALID"]
    counts: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"source_placement_count": 0, "source_chunk_count": 0,
                 "collections": set(), "collection_placements": Counter(),
                 "source_chunks_sha256": None}
    )
    collections: set[str] = set()
    for source in sources:
        release = source["source_release"]
        artifact_relative = source.get("artifacts_path")
        subjects = source.get("subjects")
        if not isinstance(subjects, list) or len(subjects) != expected_releases[release]:
            errors.append(f"SOURCE_SUBJECT_COUNT:{release}")
            continue
        try:
            artifact_path = _secure_path(root, artifact_relative)
            artifact_data, artifact_bytes = _read_json(artifact_path)
            if _sha256(artifact_bytes) != source.get("artifacts_sha256"):
                errors.append(f"SOURCE_ARTIFACT_DIGEST:{release}")
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append(f"SOURCE_ARTIFACT_MISSING:{release}")
            continue
        if (release == "v4_non_hggsp" and "/profile_gate_v4/" not in str(artifact_path)
                or release == "v5_hggsp" and "/profile_gate_hggsp_v5/" not in str(artifact_path)):
            errors.append(f"SOURCE_RELEASE_PATH:{release}")
        artifacts = artifact_data.get("artifacts")
        if not isinstance(artifacts, list):
            errors.append(f"SOURCE_ARTIFACT_FORMAT:{release}")
            continue
        artifact_map = {a.get("artifact_id"): a for a in artifacts if isinstance(a, dict)}
        if len(artifact_map) != len(artifacts):
            errors.append(f"SOURCE_ARTIFACT_DUPLICATE:{release}")
        subject_paths: set[str] = set()
        selected_ids: set[str] = set()
        for subject_ref in subjects:
            if not isinstance(subject_ref, dict):
                errors.append(f"SOURCE_SUBJECT_REF:{release}")
                continue
            relative = subject_ref.get("path")
            if not isinstance(relative, str):
                errors.append(f"SOURCE_SUBJECT_PATH:{release}")
                continue
            try:
                path = _secure_path(root, relative)
                subject, raw = _read_json(path)
            except (OSError, ValueError, json.JSONDecodeError):
                errors.append(f"SOURCE_SUBJECT_MISSING:{release}")
                continue
            if _sha256(raw) != subject_ref.get("sha256") or relative in subject_paths:
                errors.append(f"SOURCE_SUBJECT_DIGEST:{release}")
            subject_paths.add(relative)
            collection = subject.get("collection")
            if not isinstance(collection, str) or not collection:
                errors.append(f"SOURCE_COLLECTION_SCOPE:{release}")
                continue
            if (collection in collections
                    or ("hggsp" in collection) != (release == "v5_hggsp")):
                errors.append(f"SOURCE_COLLECTION_SCOPE:{release}")
            else:
                collections.add(collection)
            placements = subject.get("placements")
            if not isinstance(placements, list):
                errors.append(f"SOURCE_PLACEMENTS_INVALID:{release}")
                continue
            if subject.get("expected_counts", {}).get("placements") != len(placements):
                errors.append(f"SOURCE_PLACEMENTS_COUNT:{release}")
            for placement in placements:
                if not isinstance(placement, dict) or placement.get("collection") != collection:
                    errors.append(f"SOURCE_PLACEMENT_SCOPE:{release}")
                    continue
                sha = placement.get("artifact_id")
                if not isinstance(sha, str) or sha not in artifact_map or sha not in inventory:
                    errors.append(f"SOURCE_PLACEMENT_UNKNOWN_SHA:{release}")
                    continue
                counts[sha]["source_placement_count"] += 1
                counts[sha]["collections"].add(collection)
                counts[sha]["collection_placements"][collection] += 1
                selected_ids.add(sha)
        for sha in selected_ids:
            chunks = artifact_map[sha].get("chunks")
            if not isinstance(chunks, list) or not chunks:
                errors.append(f"SOURCE_CHUNKS_MISSING:{release}")
            else:
                if counts[sha]["source_chunks_sha256"] is not None:
                    errors.append(f"SOURCE_ARTIFACT_REUSED:{sha[:12]}")
                counts[sha]["source_chunks_sha256"] = _sha256(canonical_json_bytes(chunks))
                counts[sha]["source_chunk_count"] += len(chunks)
    if set(counts) != set(inventory):
        errors.append("SOURCE_INVENTORY_SET_MISMATCH")
    if len(collections) != 11:
        errors.append("SOURCE_COLLECTION_COUNT")
    for sha, packet in inventory.items():
        packet_collections = {p["collection"] for p in packet.get("placements", [])}
        if packet_collections != counts[sha]["collections"] or (
            len(packet.get("placements", [])) != counts[sha]["source_placement_count"]
        ):
            errors.append(f"SOURCE_PACKET_PLACEMENTS:{sha[:12]}")
    for sha, ref in _mapping(index.get("artifacts")).items():
        if not isinstance(ref, dict):
            continue
        actual = counts[sha]
        if (ref.get("source_placement_count") != actual["source_placement_count"]
                or ref.get("source_chunk_count") != actual["source_chunk_count"]):
            errors.append(f"SOURCE_PROJECTED_COUNTS:{sha[:12]}")
    return counts, collections, errors


def _check_gate(
    root: Path, *, expected_count: int = 315, expected_head: str | None = None,
    source_mirror_root: Path | None = None,
    private_candidate_root: Path | None = None,
) -> dict:
    """Gate complet. Toute erreur rend le verdict rouge, sans mutation."""
    errors: list[str] = []
    if not _is_git_sha(expected_head):
        errors.append("EXACT_HEAD_REQUIRED")
    paths = {name: root / relative for name, relative in DEFAULTS.items()}
    if not paths["index"].is_file():
        return {"DELEGATED_RIGHTS_ADJUDICATION_PASS": False, "errors": ["INDEX_MISSING"]}
    if source_mirror_root is None or not source_mirror_root.is_dir():
        return {"DELEGATED_RIGHTS_ADJUDICATION_PASS": False,
                "errors": ["SOURCE_MIRROR_ROOT_REQUIRED"]}
    try:
        index, index_bytes = _read_json(paths["index"])
        packet, packet_bytes = _read_json(paths["packet"])
        schema, schema_bytes = _read_json(paths["schema"])
        policy_bytes = paths["policy"].read_bytes()
        extraction_policy = yaml.safe_load(paths["extraction_policy"].read_bytes())
        mandate_bytes = paths["mandate"].read_bytes()
        policy = yaml.safe_load(policy_bytes)
        mandate = yaml.safe_load(mandate_bytes)
        if (not isinstance(policy, dict) or not isinstance(mandate, dict)
                or not isinstance(extraction_policy, dict)):
            raise ValueError("invalid policy/mandate")
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        return {"DELEGATED_RIGHTS_ADJUDICATION_PASS": False,
                "errors": [f"PACK_INPUT_INVALID:{type(error).__name__}"]}
    if index_bytes != canonical_json_bytes(index):
        errors.append("INDEX_NOT_CANONICAL")
    errors.extend(_derivative_policy_errors(extraction_policy))
    if index.get("schema_version") != "NEXUS_DELEGATED_STUDENT_RIGHTS_EVIDENCE_INDEX_V2":
        errors.append("INDEX_SCHEMA_VERSION")
    packet_artifacts = packet.get("artifacts")
    if not isinstance(packet_artifacts, list):
        packet_artifacts = []
    by_sha: dict[str, dict] = {}
    for artifact in packet_artifacts:
        if not isinstance(artifact, dict) or not _is_sha(artifact.get("content_sha256")):
            errors.append("INVENTORY_SHA_INVALID")
            continue
        by_sha[artifact["content_sha256"]] = artifact
    if len(packet_artifacts) != len(by_sha) or len(by_sha) != expected_count:
        errors.append("INVENTORY_COUNT_OR_DUPLICATE")
    inventory_digest = _sha256(packet_bytes)
    set_digest = _sha256("".join(f"{sha}\n" for sha in sorted(by_sha)).encode())
    if (index.get("inventory_sha256") != inventory_digest
            or packet.get("population", {}).get("content_sha256_set_digest") != set_digest):
        errors.append("INVENTORY_DIGEST")
    if not all(_is_sha(sha) for sha in by_sha):
        errors.append("INVENTORY_SHA_INVALID")
    expected_hashes = {
        "policy_sha256": _sha256(policy_bytes), "mandate_sha256": _sha256(mandate_bytes),
        "schema_sha256": _sha256(schema_bytes),
        "engine_code_sha256": _sha256(paths["engine"].read_bytes()),
        "scanner_code_sha256": _sha256(paths["scanner"].read_bytes()),
        "source_checker_code_sha256": _sha256(paths["source_checker"].read_bytes()),
        "reviewer_code_sha256": _sha256(paths["reviewer"].read_bytes()),
        "derivative_builder_code_sha256": _sha256(paths["derivative_builder"].read_bytes()),
        "text_derivative_extraction_policy_sha256": _sha256(paths["extraction_policy"].read_bytes()),
    }
    authority_path = _mapping(policy.get("rights_authorities")).get("sitewide", {}).get("path")
    try:
        authority_file = _secure_path(root, authority_path)
        authority_bytes = authority_file.read_bytes()
        authority = yaml.safe_load(authority_bytes)
        if not isinstance(authority, dict):
            raise ValueError("authority must be an object")
        expected_hashes["rights_authority_sha256"] = _sha256(authority_bytes)
        errors.extend(_verify_sitewide_authority(root, authority))
    except (OSError, ValueError, yaml.YAMLError):
        errors.append("AUTHORITY_MISSING")
        expected_hashes["rights_authority_sha256"] = "0" * 64
    for name, digest in expected_hashes.items():
        if index.get(name) != digest:
            errors.append(f"INDEX_{name.upper()}")
    if index.get("delegation_sha256") != expected_hashes["mandate_sha256"]:
        errors.append("INDEX_DELEGATION_SHA256")
    if mandate.get("status") != "SEALED_PENDING_FINAL_APPROVAL":
        errors.append("MANDATE_NOT_SEALED")
    if policy.get("status") != "SEALED_PENDING_FINAL_APPROVAL":
        errors.append("POLICY_NOT_SEALED")
    if mandate.get("effective_authority") is not False:
        errors.append("PREAPPROVAL_AUTHORITY_MUST_BE_FALSE")
    errors.extend(_mandate_time_errors(mandate))
    errors.extend(_git_source_binding(root, mandate, expected_head))
    if (mandate.get("public_ingest_endpoint_allowed") is not False
            or mandate.get("public_writer_allowed") is not False):
        errors.append("MANDATE_PUBLIC_WRITER_FORBIDDEN")
    binding = _mapping(mandate.get("source_binding"))
    if (mandate.get("delegating_authority") != "abenrhouma"
            or mandate.get("decision_executor") != "nexus-delegated-student-rights-adjudicator-v1"
            or binding.get("inventory_file_sha256") != inventory_digest
            or binding.get("inventory_content_sha256_set_digest") != set_digest
            or binding.get("inventory_count") != expected_count
            or binding.get("policy_sha256") != expected_hashes["policy_sha256"]
            or binding.get("schema_sha256") != expected_hashes["schema_sha256"]
            or binding.get("engine_code_sha256") != expected_hashes["engine_code_sha256"]
            or binding.get("scanner_code_sha256") != expected_hashes["scanner_code_sha256"]
            or binding.get("source_checker_code_sha256") != expected_hashes["source_checker_code_sha256"]
            or binding.get("reviewer_code_sha256") != expected_hashes["reviewer_code_sha256"]
            or binding.get("derivative_builder_code_sha256") != expected_hashes["derivative_builder_code_sha256"]
            or binding.get("text_derivative_extraction_policy_sha256") != expected_hashes["text_derivative_extraction_policy_sha256"]
            or binding.get("rights_authority_sha256") != expected_hashes["rights_authority_sha256"]
            or binding.get("independent_verifier_code_sha256") != _sha256(Path(__file__).read_bytes())):
        errors.append("MANDATE_BINDINGS")
    for label in ("a", "b"):
        reviewer_index = _mapping(index.get(f"reviewer_{label}"))
        reviewer_mandate = _mapping(
            _mapping(mandate.get("automated_reviewers")).get(f"reviewer_{label}")
        )
        for field in ("identity", "model_id", "model_version", "prompt_sha256"):
            mandate_field = "agent_identity" if field == "identity" else field
            if (not reviewer_index.get(field)
                    or reviewer_index.get(field) != reviewer_mandate.get(mandate_field)):
                errors.append(f"REVIEWER_{label.upper()}_PIN")
        parameters = reviewer_mandate.get("deterministic_parameters")
        if (not isinstance(parameters, dict) or not parameters
                or parameters.get("temperature") != 0
                or reviewer_index.get("parameters_sha256") != _sha256(_compact_json_bytes(parameters))):
            errors.append(f"REVIEWER_{label.upper()}_PARAMETERS_DIGEST")
        prompt_path = reviewer_mandate.get("prompt_path")
        try:
            prompt_digest = _sha256(_secure_path(root, prompt_path).read_bytes())
        except (OSError, ValueError):
            prompt_digest = None
        if prompt_digest != reviewer_index.get("prompt_sha256"):
            errors.append(f"REVIEWER_{label.upper()}_PROMPT_DIGEST")
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        validator = jsonschema.Draft202012Validator(schema)
    except jsonschema.exceptions.SchemaError:
        return {"DELEGATED_RIGHTS_ADJUDICATION_PASS": False,
                "errors": sorted(set(errors + ["SCHEMA_INVALID"]))}
    refs = index.get("artifacts")
    if not isinstance(refs, dict) or set(refs) != set(by_sha):
        errors.append("EVIDENCE_SET_MISMATCH")
        refs = refs if isinstance(refs, dict) else {}
    expected_bindings = {
        "inventory_sha256": inventory_digest,
        "policy_sha256": expected_hashes["policy_sha256"],
        "mandate_sha256": expected_hashes["mandate_sha256"],
        "schema_sha256": expected_hashes["schema_sha256"],
        "engine_code_sha256": expected_hashes["engine_code_sha256"],
        "scanner_code_sha256": expected_hashes["scanner_code_sha256"],
        "source_checker_code_sha256": expected_hashes["source_checker_code_sha256"],
        "reviewer_code_sha256": expected_hashes["reviewer_code_sha256"],
        "rights_authority_sha256": expected_hashes["rights_authority_sha256"],
        "text_derivative_extraction_policy_sha256": expected_hashes[
            "text_derivative_extraction_policy_sha256"],
        "derivative_builder_code_sha256": expected_hashes["derivative_builder_code_sha256"],
    }
    items: list[tuple[dict, dict, str]] = []
    dispositions: Counter[str] = Counter()
    derivative_receipts: dict[str, dict] = {}
    pdf_rescans_passed = 0
    for sha, packet_artifact in sorted(by_sha.items()):
        ref = refs.get(sha)
        if not isinstance(ref, dict) or ref.get("path") != f"{sha}.json":
            errors.append(f"EVIDENCE_REF:{sha[:12]}")
            continue
        try:
            path = _secure_path(paths["index"].parent, ref["path"])
            record, raw = _read_json(path)
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append(f"EVIDENCE_MISSING_OR_INVALID:{sha[:12]}")
            continue
        record_hash = _sha256(raw)
        if raw != canonical_json_bytes(record) or ref.get("sha256") != record_hash:
            errors.append(f"EVIDENCE_DIGEST:{sha[:12]}")
        for schema_error in validator.iter_errors(record):
            errors.append(f"SCHEMA_RECORD:{sha[:12]}:{schema_error.json_path}")
        errors.extend(f"{code}:{sha[:12]}" for code in check_artifact(
            record, packet_artifact, policy, mandate, expected_bindings
        ))
        is_v2 = record.get("record_kind") == "NEXUS_AUTOMATED_ARTIFACT_REVIEW_V2"
        if is_v2:
            provenance_errors, provenance_checkpoint = _verify_source_provenance(
                record, packet_artifact, root, paths["index"].parent,
                source_mirror_root, inventory_digest,
                expected_hashes["rights_authority_sha256"],
                expected_hashes["source_checker_code_sha256"],
                allow_unproven=record.get("derivative_disposition") != "APPROVE_PUBLIC",
            )
            errors.extend(f"{code}:{sha[:12]}" for code in provenance_errors)
            receipt_errors, derivative_receipt = _verify_derivative_receipt_cas(
                record, packet_artifact, paths["index"].parent,
                expected_hashes["policy_sha256"],
                expected_hashes["text_derivative_extraction_policy_sha256"],
                expected_hashes["derivative_builder_code_sha256"],
            )
            errors.extend(f"{code}:{sha[:12]}" for code in receipt_errors)
            if derivative_receipt:
                derivative_receipts[sha] = derivative_receipt
            if record.get("derivative_disposition") == "APPROVE_PUBLIC":
                if (derivative_receipt.get("source_provenance_checkpoint_sha256")
                        != provenance_checkpoint.get("checkpoint_sha256")):
                    errors.append(f"DERIVATIVE_PROVENANCE_CHECKPOINT_MISMATCH:{sha[:12]}")
                if record.get("rights_basis") != "SITEWIDE_DOWNLOAD_AUTHORITY":
                    errors.append(f"INDIVIDUAL_LICENCE_PROOF_NOT_IMPLEMENTED:{sha[:12]}")
                if (record.get("rights_authority_id") != "EDUSCOL_ETALAB_2_0_SITEWIDE"
                        or record.get("rights_authority_sha256")
                        != expected_hashes["rights_authority_sha256"]):
                    errors.append(f"DERIVATIVE_AUTHORITY_MISMATCH:{sha[:12]}")
                source_facts = _mapping(_mapping(provenance_checkpoint.get(
                    "source_provenance")).get("source_updated_at"))
                pdf_facts = _mapping(_mapping(provenance_checkpoint.get(
                    "source_provenance")).get("pdf_fetch"))
                attribution = _mapping(derivative_receipt.get("source_attribution"))
                if (attribution.get("source_uri") != pdf_facts.get("final_url")
                        or attribution.get("source_label") != packet_artifact.get("title")
                        or attribution.get("source_updated_at") != source_facts.get("date")
                        or attribution.get("source_date_kind") != source_facts.get("kind")
                        or attribution.get("licence_id") != "ETALAB-2.0"):
                    errors.append(f"DERIVATIVE_ATTRIBUTION_SOURCE_MISMATCH:{sha[:12]}")
                if private_candidate_root is None or not private_candidate_root.is_dir():
                    errors.append(f"PRIVATE_CANDIDATE_ROOT_REQUIRED:{sha[:12]}")
                else:
                    try:
                        candidate_path = _secure_path(
                            private_candidate_root, derivative_receipt.get("candidate_relpath")
                        )
                        if candidate_path.is_symlink():
                            raise ValueError("candidate symlink")
                        candidate = candidate_path.read_bytes()
                        source_pdf = _secure_path(source_mirror_root, packet_artifact.get("source_path"))
                        errors.extend(f"{code}:{sha[:12]}" for code in _verify_text_derivative(
                            derivative_receipt, source_pdf, packet_artifact, candidate,
                            expected_hashes["text_derivative_extraction_policy_sha256"],
                            expected_hashes["policy_sha256"],
                            expected_hashes["derivative_builder_code_sha256"],
                            provenance_checkpoint,
                            expected_hashes["rights_authority_sha256"],
                        ))
                    except (OSError, ValueError):
                        errors.append(f"PRIVATE_CANDIDATE_MISSING:{sha[:12]}")
        elif record.get("final_disposition") == "APPROVE_PUBLIC":
            errors.extend(f"{code}:{sha[:12]}" for code in _verify_approval_source_proof(
                record, packet_artifact, paths["index"].parent
            ))
        if not is_v2:
            request_proofs, request_errors = _reconstruct_review_requests(
                record, packet_artifact, source_mirror_root
            )
            errors.extend(f"{code}:{sha[:12]}" for code in request_errors)
            errors.extend(f"{code}:{sha[:12]}" for code in _verify_review_receipts(
                record, paths["index"].parent, request_proofs, run_nonce=0
            ))
        if not is_v2 and record.get("final_disposition") == "APPROVE_PUBLIC":
            replays = record.get("candidate_replays")
            if isinstance(replays, list) and len(replays) == 2 and isinstance(replays[1], dict):
                replay_record = dict(record)
                for label in ("a", "b"):
                    reviewer = dict(_mapping(record.get(f"reviewer_{label}")))
                    reviewer["context_sha256"] = replays[1].get(
                        f"reviewer_{label}_context_sha256"
                    )
                    reviewer["observation_sha256"] = replays[1].get(
                        f"reviewer_{label}_observation_sha256"
                    )
                    reviewer["evidence_refs"] = replays[1].get(
                        f"reviewer_{label}_evidence_refs"
                    )
                    replay_record[f"reviewer_{label}"] = reviewer
                errors.extend(f"REPLAY_{code}:{sha[:12]}" for code in _verify_review_receipts(
                    replay_record, paths["index"].parent, request_proofs, run_nonce=1
                ))
            else:
                errors.append(f"APPROVAL_REPLAY_RECEIPTS_MISSING:{sha[:12]}")
        rescan_errors = _rescan_pdf(record, packet_artifact, source_mirror_root)
        if rescan_errors:
            errors.extend(f"{code}:{sha[:12]}" for code in rescan_errors)
        else:
            pdf_rescans_passed += 1
        for label in (() if is_v2 else ("a", "b")):
            reviewer = _mapping(record.get(f"reviewer_{label}"))
            pinned = _mapping(index.get(f"reviewer_{label}"))
            if any(reviewer.get(field) != pinned.get(field) for field in (
                "identity", "model_id", "model_version", "prompt_sha256",
                "parameters_sha256",
            )):
                errors.append(f"REVIEWER_{label.upper()}_RECORD_PIN:{sha[:12]}")
        dispositions[record.get("source_disposition" if is_v2 else "final_disposition", "MISSING")] += 1
        items.append((record, packet_artifact, record_hash))
    if len(items) != expected_count:
        errors.append("FINAL_DECISIONS_COUNT")
    sheet = render_decision_sheet(items)
    if (not paths["sheet"].is_file() or paths["sheet"].read_bytes() != sheet
            or index.get("decision_sheet_sha256") != _sha256(sheet)):
        errors.append("DECISION_SHEET_TAMPERED")
    if dispositions.get("PENDING", 0):
        errors.append("PENDING_DECISIONS")
    counts, all_collections, source_errors = _source_population(root, index, by_sha)
    errors.extend(source_errors)
    if any(r.get("record_kind") != "NEXUS_AUTOMATED_ARTIFACT_REVIEW_V2" for r, _, _ in items):
        errors.append("RECORD_VERSION_STALE")
    records_by_sha = {r["content_sha256"]: r for r, _, _ in items}
    try:
        manifest, manifest_raw = _read_json(paths["candidate_manifest"])
        if (manifest_raw != canonical_json_bytes(manifest)
                or _sha256(manifest_raw) != index.get("public_candidate_manifest_sha256")):
            errors.append("PUBLIC_MANIFEST_DIGEST")
        manifest_errors, derived_population = _verify_candidate_manifest(
            manifest, records_by_sha, by_sha, derivative_receipts,
            inventory_digest, expected_hashes["rights_authority_sha256"],
            expected_hashes["text_derivative_extraction_policy_sha256"],
            all_collections,
        )
        errors.extend(manifest_errors)
    except (OSError, ValueError, json.JSONDecodeError):
        errors.append("PUBLIC_MANIFEST_MISSING")
        derived_population = {}
    if index.get("final_population") != derived_population:
        errors.append("FINAL_POPULATION_MISMATCH")
    all_approved = sorted(
        r["derivative_content_sha256"] for r, _, _ in items
        if r.get("derivative_disposition") == "APPROVE_PUBLIC"
        and _is_sha(r.get("derivative_content_sha256"))
    )
    return {
        "DELEGATED_RIGHTS_ADJUDICATION_PASS": not errors,
        "INVENTORY_COUNT": len(by_sha), "FINAL_DECISIONS_COUNT": len(items),
        "PENDING_COUNT": dispositions.get("PENDING", 0),
        "FULL_DOCUMENT_SCAN_COUNT": pdf_rescans_passed,
        "DUAL_REVIEW_COUNT": sum(_dual_review_complete(r) for r, _, _ in items),
        "CFTR_DISPOSITION": next((r.get("final_disposition") for r, _, _ in items
                                  if r.get("content_sha256") == CFTR), None),
        "EVIDENCE_PACK_SHA256": _sha256(index_bytes),
        "APPROVED_CONTENT_SHA256": all_approved,
        "APPROVED_DERIVATIVE_CONTENT_SHA256": all_approved,
        "FINAL_POPULATION": derived_population,
        "POLICY_FAIL_CLOSED": not errors,
        "MANUAL_PER_FILE_REVIEW_REQUIRED": False,
        "FINAL_EXACT_HEAD_AUTHORITY_APPROVAL_REQUIRED": True,
        "errors": sorted(set(errors)),
    }


def check_gate(
    root: Path, *, expected_count: int = 315, expected_head: str | None = None,
    source_mirror_root: Path | None = None,
    private_candidate_root: Path | None = None,
) -> dict:
    """API totale : un pack malformé ne provoque jamais une validation implicite."""
    try:
        return _check_gate(root, expected_count=expected_count, expected_head=expected_head,
                           source_mirror_root=source_mirror_root,
                           private_candidate_root=private_candidate_root)
    except Exception as error:  # noqa: BLE001 - un pack hostile doit échouer fermé
        return {"DELEGATED_RIGHTS_ADJUDICATION_PASS": False,
                "errors": [f"GATE_INPUT_INVALID:{type(error).__name__}"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--expected-head")
    parser.add_argument("--source-mirror-root", type=Path, required=True)
    parser.add_argument("--private-candidate-root", type=Path)
    args = parser.parse_args(argv)
    result = check_gate(args.root, expected_head=args.expected_head,
                        source_mirror_root=args.source_mirror_root,
                        private_candidate_root=args.private_candidate_root)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
    return 0 if result["DELEGATED_RIGHTS_ADJUDICATION_PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
