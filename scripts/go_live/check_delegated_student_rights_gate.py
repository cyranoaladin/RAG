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
    "source_checker": "scripts/go_live/student_rights_source_check.py",
    "reviewer": "scripts/go_live/student_rights_reviewers.py",
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
        rights_pass = record.get("rights_basis") in RIGHTS_BASES and (
            record.get("reviewer_a", {}).get("verdict") == "PASS"
        )
        student_pass = record.get("reviewer_b", {}).get("verdict") == "PASS" and (
            checks.get("student_suitability_pass") is True
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
            "rights_review": "PUBLIC_RIGHTS_CONFIRMED" if rights_pass else "BLOCKED",
            "student_suitability": "STUDENT_APPROVED" if student_pass else "STUDENT_BLOCKED",
            "third_party_exception_review": "CLEARED_WITH_EVIDENCE" if record.get("third_party_status") == "CLEARED_WITH_EVIDENCE" else "BLOCKED",
            "pii_recheck": "PASS_WITH_EVIDENCE" if checks.get("pii_gate_pass") is True else "FAIL",
            "currentness_recheck": "PASS_WITH_EVIDENCE" if checks.get("currentness_gate_pass") is True else "FAIL",
            "revocation_recheck": "PASS_WITH_EVIDENCE" if checks.get("revocation_gate_pass") is True else "FAIL",
            "student_public_disposition": record.get("final_disposition", ""),
            "rights_evidence_ref": record.get("rights_evidence_uri") or "",
            "decision_evidence_pages": ",".join(str(page) for page in sorted(pages)),
            "decision_reason": ",".join(sorted(record.get("reason_codes") or [])),
            "human_reviewer": "",
            "reviewed_at_utc": record.get("decided_at_utc", ""),
            "decision_executor": record.get("decision_executor", ""),
            "delegation_id": record.get("delegation_id", ""),
            "evidence_sha256": evidence_sha,
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
        mandate_bytes = paths["mandate"].read_bytes()
        policy = yaml.safe_load(policy_bytes)
        mandate = yaml.safe_load(mandate_bytes)
        if not isinstance(policy, dict) or not isinstance(mandate, dict):
            raise ValueError("invalid policy/mandate")
    except (OSError, ValueError, json.JSONDecodeError, yaml.YAMLError) as error:
        return {"DELEGATED_RIGHTS_ADJUDICATION_PASS": False,
                "errors": [f"PACK_INPUT_INVALID:{type(error).__name__}"]}
    if index_bytes != canonical_json_bytes(index):
        errors.append("INDEX_NOT_CANONICAL")
    if index.get("schema_version") != "NEXUS_DELEGATED_STUDENT_RIGHTS_EVIDENCE_INDEX_V1":
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
    }
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
    }
    items: list[tuple[dict, dict, str]] = []
    dispositions: Counter[str] = Counter()
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
        if record.get("final_disposition") == "APPROVE_PUBLIC":
            errors.extend(f"{code}:{sha[:12]}" for code in _verify_approval_source_proof(
                record, packet_artifact, paths["index"].parent
            ))
        request_proofs, request_errors = _reconstruct_review_requests(
            record, packet_artifact, source_mirror_root
        )
        errors.extend(f"{code}:{sha[:12]}" for code in request_errors)
        errors.extend(f"{code}:{sha[:12]}" for code in _verify_review_receipts(
            record, paths["index"].parent, request_proofs, run_nonce=0
        ))
        if record.get("final_disposition") == "APPROVE_PUBLIC":
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
        for label in ("a", "b"):
            reviewer = _mapping(record.get(f"reviewer_{label}"))
            pinned = _mapping(index.get(f"reviewer_{label}"))
            if any(reviewer.get(field) != pinned.get(field) for field in (
                "identity", "model_id", "model_version", "prompt_sha256",
                "parameters_sha256",
            )):
                errors.append(f"REVIEWER_{label.upper()}_RECORD_PIN:{sha[:12]}")
        dispositions[record.get("final_disposition", "MISSING")] += 1
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
    approved = {r["content_sha256"] for r, _, _ in items
                if r.get("final_disposition") == "APPROVE_PUBLIC"}
    all_approved = sorted(approved)
    if not approved <= set(counts):
        errors.append("APPROVED_SHA_NOT_IN_SOURCE")
        approved &= set(counts)
        all_approved = sorted(approved)
    replacements = {r["content_sha256"] for r, _, _ in items
                    if r.get("final_disposition") == "REPLACE_WITH_NEW_CONTENT"}
    if replacements:
        # Un substitut exige son propre artefact et manifeste ; aucun report
        # des anciens chunks/placements n'est admissible dans cette release.
        errors.append("REPLACEMENT_RELEASE_MANIFEST_REQUIRED")
    derived_population = {
        "collections": len({collection for sha in approved for collection in counts[sha]["collections"]}),
        "artifacts": len(approved),
        "placements": sum(counts[sha]["source_placement_count"] for sha in approved),
        "chunks": sum(counts[sha]["source_chunk_count"] for sha in approved),
        "approve_public": dispositions.get("APPROVE_PUBLIC", 0),
        "exclude": dispositions.get("EXCLUDE", 0),
        "replace_with_new_content": dispositions.get("REPLACE_WITH_NEW_CONTENT", 0),
    }
    if index.get("final_population") != derived_population:
        errors.append("FINAL_POPULATION_MISMATCH")
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
        "APPROVED_SOURCE_PLACEMENTS": {
            sha: dict(sorted(counts[sha]["collection_placements"].items()))
            for sha in all_approved
        },
        "APPROVED_SOURCE_CHUNKS_SHA256": {
            sha: counts[sha]["source_chunks_sha256"] for sha in all_approved
        },
        "FINAL_POPULATION": derived_population,
        "POLICY_FAIL_CLOSED": not errors,
        "MANUAL_PER_FILE_REVIEW_REQUIRED": False,
        "FINAL_EXACT_HEAD_AUTHORITY_APPROVAL_REQUIRED": True,
        "errors": sorted(set(errors)),
    }


def check_gate(
    root: Path, *, expected_count: int = 315, expected_head: str | None = None,
    source_mirror_root: Path | None = None,
) -> dict:
    """API totale : un pack malformé ne provoque jamais une validation implicite."""
    try:
        return _check_gate(root, expected_count=expected_count, expected_head=expected_head,
                           source_mirror_root=source_mirror_root)
    except Exception as error:  # noqa: BLE001 - un pack hostile doit échouer fermé
        return {"DELEGATED_RIGHTS_ADJUDICATION_PASS": False,
                "errors": [f"GATE_INPUT_INVALID:{type(error).__name__}"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--expected-head")
    parser.add_argument("--source-mirror-root", type=Path, required=True)
    args = parser.parse_args(argv)
    result = check_gate(args.root, expected_head=args.expected_head,
                        source_mirror_root=args.source_mirror_root)
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, indent=2))
    return 0 if result["DELEGATED_RIGHTS_ADJUDICATION_PASS"] else 1


if __name__ == "__main__":
    sys.exit(main())
