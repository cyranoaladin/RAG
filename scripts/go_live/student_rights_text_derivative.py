"""Prépare des dérivés textuels privés, distincts des PDF sources.

Ce module ne prononce aucun droit de publication. Ses octets restent privés
jusqu'à la double revue du texte et au contrôle indépendant des sources.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

import fitz
import yaml

CFTR_SHA256 = "3f1ab328a0c11f40a0abf85dccdf29dc17d80159dc01bee189a10017d0fbd3e6"
KIND = "NEXUS-STUDENT-NATIVE-TEXT-DERIVATIVE-V1"
SERIALIZATION_PROTOCOL = "NEXUS-STUDENT-TEXT-DERIVATIVE-SERIALIZATION-V2"
POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "governance/student_public_rights/text_derivative_extraction_policy_v1.yml"
)
ADJUDICATION_POLICY_PATH = (
    Path(__file__).resolve().parents[2]
    / "governance/student_public_rights/delegated_review_policy_v1.yml"
)
MAX_GROUP_CHARS = 4000
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_EMAIL = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE = re.compile(r"(?<!\d)(?:\+33|\+216|0)(?:[\s.()\-]*\d){8,}(?!\d)")
_TEACHER = re.compile(
    r"\b(?:corrig[ée]|bar[èe]me|enseignant(?:s|es)?|professeur(?:s)?|"
    r"r[ée]serv[ée] aux (?:enseignants|professeurs)|r[ée]ponses? attendues?|"
    r"solutions?|ne pas communiquer|non.divulgation)\b",
    re.I,
)
_THIRD_PARTY = re.compile(
    r"(?:©|\bcopyright\b|\btous droits r[ée]serv[ée]s\b|"
    r"\breproduit avec l.autorisation\b|\bextrait de\b|\badapt[ée] de\b|"
    r"\bcr[ée]dits?\b|\b[ée]diteur\b|\b[ée]ditions?\b|"
    r"\blicen[cs]e\b|\bcreative commons\b|\bCC[- ]?BY\b|"
    r"\bISBN\b|\bDOI\b|\bbibliographie\b|\bsitographie\b|"
    r"\ben partenariat avec\b|\bavec le concours de\b|"
    r"\b(?:Nathan|Hachette|Belin|Hatier|Bordas|Magnard|Flammarion|"
    r"Gallimard|Larousse|Pearson|Dunod)\b)",
    re.I,
)
_THIRD_PARTY_PAGE = re.compile(
    r"(?:\bcr[ée]dits?\s+(?:photo|photographique|illustration|image|auteur)\b|"
    r"\breproduit avec l.autorisation\b|\btous droits r[ée]serv[ée]s\b|"
    r"\bbibliographie\b|\bsitographie\b|\ben partenariat avec\b|"
    r"\bavec le concours de\b|\bISBN\b|"
    r"\b(?:[ée]ditions?\s+)?(?:Nathan|Hachette|Belin|Hatier|Bordas|"
    r"Magnard|Flammarion|Gallimard|Larousse|Pearson|Dunod)\b)",
    re.I,
)
_LONG_QUOTE = re.compile(r"[«“][\s\S]{120,}?[»”]")
_OFFICIAL_PUBLISHER = re.compile(
    r"(?:\bDGESCO\b|direction\s+g[ée]n[ée]rale\s+de\s+l.enseignement\s+scolaire|"
    r"minist[èe]re\s+de\s+l.[ée]ducation\s+nationale|\bMENJS?\b)",
    re.I,
)
_PUBLISHER_IMPRINT = re.compile(
    r"(?:©|\bcopyright\b|\b[ée]diteur\s*:?|\b[ée]dit[ée]\s+par\b|"
    r"\bpubli[ée]\s+par\b|\br[ée]alis[ée]\s+par\b|\bcon[çc]u\s+par\b)"
    r"\s*[:\-]?\s*[^\n]{0,80}?"
    r"(?:\bDGESCO\b|direction\s+g[ée]n[ée]rale\s+de\s+l.enseignement\s+scolaire|"
    r"minist[èe]re\s+de\s+l.[ée]ducation\s+nationale|\bMENJS?\b)",
    re.I,
)
_FIRST_PARTY_COPYRIGHT = re.compile(
    r"(?:©|\bcopyright\b)\s*(?:\bDGESCO\b|"
    r"direction\s+g[ée]n[ée]rale\s+de\s+l.enseignement\s+scolaire|"
    r"minist[èe]re\s+de\s+l.[ée]ducation\s+nationale|\bMENJS?\b)",
    re.I,
)


class DerivativeError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


@dataclass(frozen=True)
class ReviewGroup:
    page_number: int
    group_index: int
    group_count: int
    block_indices: tuple[int, ...]
    text_sha256: str
    text: str = field(repr=False)


@dataclass(frozen=True)
class TextCandidate:
    content: bytes | None = field(repr=False)
    evidence: dict
    review_groups: tuple[ReviewGroup, ...] = field(repr=False)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _file_hash(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        raise DerivativeError("SOURCE_UNREADABLE") from None
    return digest.hexdigest(), size


def _normalized(text: str) -> str:
    return unicodedata.normalize("NFC", text).replace("\r\n", "\n").replace("\r", "\n").strip()


def _bbox_hash(box: tuple | list) -> str:
    values = [format(float(value), ".6f") for value in box[:4]]
    return _sha(json.dumps(values, separators=(",", ":")).encode("ascii"))


def _overlap(left: tuple | list, right: tuple | list) -> bool:
    return (
        max(float(left[0]), float(right[0])) < min(float(left[2]), float(right[2]))
        and max(float(left[1]), float(right[1])) < min(float(left[3]), float(right[3]))
    )


def _risk_reason(text: str) -> str | None:
    if _EMAIL.search(text) or _PHONE.search(text):
        return "PII_PATTERN"
    if _TEACHER.search(text):
        return "TEACHER_OR_NONDISCLOSURE_SIGNAL"
    third_party_text = _FIRST_PARTY_COPYRIGHT.sub("", text)
    if _THIRD_PARTY.search(third_party_text) or _LONG_QUOTE.search(text):
        return "THIRD_PARTY_SIGNAL"
    return None


def _block_class(reason: str | None) -> str:
    if reason is None:
        return "SAFE_TEXT_CANDIDATE"
    if reason in {"THIRD_PARTY_SIGNAL", "THIRD_PARTY_PAGE_SIGNAL"}:
        return "THIRD_PARTY_TEXT_SUSPECT"
    if reason == "TEACHER_OR_NONDISCLOSURE_SIGNAL":
        return "TEACHER_ONLY"
    if reason in {"PII_PATTERN", "PACKET_AUTOMATED_REVIEW_SIGNAL",
                  "PACKET_PII_NOT_CLEARED",
                  "PUBLISHER_NOT_PROVEN",
                  "NATIVE_BLOCK_EXCEEDS_REVIEW_BUDGET"}:
        return "PII_OR_UNCERTAIN"
    return "EXCLUDED_NON_TEXT"


def _validate_attribution(value: dict) -> None:
    if not isinstance(value, dict) or set(value) != {
        "source_uri", "source_label", "source_updated_at", "source_date_kind", "licensor",
        "licence_id", "derivative_notice",
    }:
        raise DerivativeError("ATTRIBUTION_INCOMPLETE")
    uri = value["source_uri"]
    updated = value["source_updated_at"]
    if not isinstance(uri, str) or any(
        not isinstance(value[field], str) or not value[field].strip()
        for field in ("source_label", "licensor", "licence_id", "derivative_notice")
    ):
        raise DerivativeError("ATTRIBUTION_INCOMPLETE")
    url = urlsplit(uri)
    if url.scheme != "https" or not url.netloc or url.username or url.password:
        raise DerivativeError("ATTRIBUTION_INCOMPLETE")
    if not isinstance(updated, str) or not updated.endswith("Z"):
        raise DerivativeError("ATTRIBUTION_INCOMPLETE")
    if value["source_date_kind"] not in {
        "DATED_OFFICIAL_SNAPSHOT", "PDF_EXPLICIT_UPDATE_DATE", "PDF_EXPLICIT_PUBLICATION_DATE",
    }:
        raise DerivativeError("ATTRIBUTION_INCOMPLETE")
    if value["source_date_kind"] == "DATED_OFFICIAL_SNAPSHOT" and (
        "snapshot" not in value["derivative_notice"].lower()
        or updated not in value["derivative_notice"]
    ):
        raise DerivativeError("ATTRIBUTION_INCOMPLETE")
    try:
        datetime.fromisoformat(updated.replace("Z", "+00:00"))
    except ValueError:
        raise DerivativeError("ATTRIBUTION_INCOMPLETE") from None


def _packet_signals(packet: dict, expected_sha: str,
                    expected_pages: int) -> tuple[str, dict[int, list[str]], bool]:
    if not isinstance(packet, dict) or (
        packet.get("content_sha256") != expected_sha
        or packet.get("page_count") != expected_pages
        or type(packet.get("explicit_student_exclusion_signal")) is not bool
        or not isinstance(packet.get("source_pii_status"), str)
    ):
        raise DerivativeError("SOURCE_PACKET_ARTIFACT_INVALID")
    signals = packet.get("automated_review_signals")
    if not isinstance(signals, list):
        raise DerivativeError("SOURCE_PACKET_ARTIFACT_INVALID")
    by_page: dict[int, list[str]] = {}
    for signal in signals:
        if (not isinstance(signal, dict) or set(signal) != {"kind", "page"}
            or not isinstance(signal["kind"], str) or not signal["kind"]
            or type(signal["page"]) is not int
            or signal["page"] < 1 or signal["page"] > expected_pages):
            raise DerivativeError("SOURCE_PACKET_ARTIFACT_INVALID")
        by_page.setdefault(signal["page"], []).append(signal["kind"])
    raw = json.dumps(packet, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=False).encode("utf-8")
    return _sha(raw), by_page, packet["explicit_student_exclusion_signal"]


def _groups(page_number: int, selected: list[tuple[int, str]]) -> list[ReviewGroup]:
    batches: list[tuple[list[int], str]] = []
    indices: list[int] = []
    text = ""
    for index, block_text in selected:
        proposed = text + ("\n\n" if text else "") + block_text
        if text and len(proposed) > MAX_GROUP_CHARS:
            batches.append((indices, text))
            indices, text = [index], block_text
        else:
            indices.append(index)
            text = proposed
    if indices:
        batches.append((indices, text))
    return [
        ReviewGroup(page_number, position, len(batches), tuple(ids),
                    _sha(group_text.encode("utf-8")), group_text)
        for position, (ids, group_text) in enumerate(batches, 1)
    ]


def _publisher_proof(
    document: fitz.Document,
    captured_publisher_binding: dict | None,
    expected_sha256: str,
    source_uri: str,
) -> dict:
    author = _normalized(str((document.metadata or {}).get("author") or ""))
    if author and _OFFICIAL_PUBLISHER.search(author):
        return {
            "status": "PASS",
            "kind": "OFFICIAL_PDF_AUTHOR_METADATA",
            "metadata_field": "author",
            "normalized_value_sha256": _sha(author.encode("utf-8")),
        }
    relevant_pages = sorted({0, len(document) - 1})
    for page_index in relevant_pages:
        for block_index, block in enumerate(
            document.load_page(page_index).get_text("blocks", sort=True)
        ):
            if block[6] != 0:
                continue
            block_text = _normalized(str(block[4]))
            if _PUBLISHER_IMPRINT.search(block_text):
                return {
                    "status": "PASS",
                    "kind": "EXPLICIT_DOCUMENT_IMPRINT",
                    "page_number": page_index + 1,
                    "block_index": block_index,
                    "normalized_text_sha256": _sha(block_text.encode("utf-8")),
                }
    binding = captured_publisher_binding
    if isinstance(binding, dict) and (
        binding.get("kind") == "OFFICIAL_CAPTURED_DOWNLOAD_PUBLISHER"
        and binding.get("source_content_sha256") == expected_sha256
        and binding.get("source_pdf_url") == source_uri
        and _official_pdf_url(binding.get("matched_anchor_href"))
        and all(
            isinstance(binding.get(key), str)
            and _SHA256.fullmatch(binding[key]) is not None
            for key in (
                "listing_capture_receipt_sha256",
                "source_provenance_checkpoint_sha256",
                "rights_authority_sha256",
            )
        )
    ):
        return {"status": "PASS", **binding}
    return {"status": "UNPROVEN", "kind": None}


def build_text_candidate(
    pdf_path: Path,
    expected_sha256: str,
    expected_page_count: int,
    source_attribution: dict,
    packet_artifact: dict,
    *, captured_publisher_binding: dict | None = None,
) -> TextCandidate:
    """Extrait le texte natif admissible structurellement, sans l'approuver.

    Les signaux de l'artefact dans le paquet scellé bloquent leurs pages ; le
    gate devra reconstruire cette provenance indépendamment.
    """
    try:
        extraction_policy_sha256 = _sha(POLICY_PATH.read_bytes())
        adjudication_policy_sha256 = _sha(ADJUDICATION_POLICY_PATH.read_bytes())
        generator_code_sha256 = _sha(Path(__file__).read_bytes())
    except OSError:
        raise DerivativeError("EXTRACTION_POLICY_UNAVAILABLE") from None
    packet_sha, packet_signals, explicit_exclusion = _packet_signals(
        packet_artifact, expected_sha256, expected_page_count
    )
    if expected_sha256 == CFTR_SHA256:
        return TextCandidate(None, {
            "kind": KIND, "source_content_sha256": expected_sha256,
            "status": "EXCLUDE", "reason_codes": ["CFTR_FORCED_EXCLUDE"],
            "derivative_content_sha256": None, "publication_authorized": False,
            "extraction_policy_sha256": extraction_policy_sha256,
            "adjudication_policy_sha256": adjudication_policy_sha256,
            "generator_code_sha256": generator_code_sha256,
            "source_packet_artifact_sha256": packet_sha,
        }, ())
    if explicit_exclusion:
        return TextCandidate(None, {
            "kind": KIND, "source_content_sha256": expected_sha256,
            "status": "EXCLUDE", "reason_codes": ["PACKET_EXPLICIT_STUDENT_EXCLUSION"],
            "derivative_content_sha256": None, "publication_authorized": False,
            "extraction_policy_sha256": extraction_policy_sha256,
            "adjudication_policy_sha256": adjudication_policy_sha256,
            "generator_code_sha256": generator_code_sha256,
            "source_packet_artifact_sha256": packet_sha,
        }, ())
    if _SHA256.fullmatch(expected_sha256) is None:
        raise DerivativeError("SOURCE_SHA256_INVALID")
    if type(expected_page_count) is not int or expected_page_count < 1:
        raise DerivativeError("SOURCE_PAGE_COUNT_INVALID")
    _validate_attribution(source_attribution)
    actual_sha, size = _file_hash(pdf_path)
    if actual_sha != expected_sha256:
        raise DerivativeError("SOURCE_SHA256_MISMATCH")
    try:
        document = fitz.open(pdf_path)
    except (OSError, RuntimeError, ValueError):
        raise DerivativeError("SOURCE_PDF_UNREADABLE") from None
    if document.is_encrypted or document.embfile_count():
        document.close()
        raise DerivativeError("SOURCE_PDF_UNSUPPORTED")
    if len(document) != expected_page_count:
        document.close()
        raise DerivativeError("SOURCE_PAGE_COUNT_MISMATCH")
    publisher_proof = _publisher_proof(
        document, captured_publisher_binding, expected_sha256,
        source_attribution["source_uri"],
    )
    header = {"source_pdf_sha256": expected_sha256, **source_attribution}
    content = bytearray(
        b"NEXUS-STUDENT-TEXT-DERIVATIVE-V2\n" + _canonical_json(header) + b"\n"
    )
    page_evidence: list[dict] = []
    groups: list[ReviewGroup] = []
    selected_count = 0
    try:
        for page_index in range(expected_page_count):
            page = document.load_page(page_index)
            page_number = page_index + 1
            citation = {
                "source_pdf_sha256": expected_sha256,
                "source_page": page_number,
                **source_attribution,
            }
            blocks = page.get_text("blocks", sort=True)
            image_boxes = [entry["bbox"] for entry in page.get_image_info()]
            vector_boxes = [entry["rect"] for entry in page.get_drawings()]
            page_third_party_signal = any(
                _THIRD_PARTY_PAGE.search(_normalized(str(block[4])))
                for block in blocks if block[6] == 0
            )
            blocked_reason = (
                "PACKET_PII_NOT_CLEARED"
                if packet_artifact["source_pii_status"] != "CLEARED"
                else "PACKET_AUTOMATED_REVIEW_SIGNAL"
                if page_number in packet_signals else None
            )
            selected: list[tuple[int, str]] = []
            excluded: list[dict] = []
            native_hashes: list[str] = []
            all_blocks: list[dict] = []
            for block_index, block in enumerate(blocks):
                block_text = _normalized(str(block[4]))
                block_sha = _sha(block_text.encode("utf-8"))
                block_facts = {
                    "block_index": block_index,
                    "block_type": block[6],
                    "normalized_text_sha256": block_sha,
                    "bbox_sha256": _bbox_hash(block),
                }
                all_blocks.append(block_facts)
                if block[6] != 0:
                    reason = "NON_TEXT_BLOCK"
                else:
                    native_hashes.append(block_sha)
                    if blocked_reason is not None:
                        reason = blocked_reason
                    elif publisher_proof["status"] != "PASS":
                        reason = "PUBLISHER_NOT_PROVEN"
                    elif page_third_party_signal:
                        reason = "THIRD_PARTY_PAGE_SIGNAL"
                    elif not block_text:
                        reason = "EMPTY_NATIVE_BLOCK"
                    elif any(_overlap(block, image_box) for image_box in image_boxes):
                        reason = "RASTER_OVERLAP"
                    elif any(_overlap(block, vector_box) for vector_box in vector_boxes):
                        reason = "VECTOR_OVERLAP"
                    elif len(block_text) > MAX_GROUP_CHARS:
                        reason = "NATIVE_BLOCK_EXCEEDS_REVIEW_BUDGET"
                    else:
                        reason = _risk_reason(block_text)
                block_facts["block_class"] = _block_class(reason)
                if reason is None:
                    block_facts["citation"] = citation
                    selected.append((block_index, block_text))
                else:
                    excluded.append({**block_facts, "reason_code": reason})
            page_groups = _groups(page_number, selected)
            groups.extend(page_groups)
            start = len(content)
            if selected:
                selected_map: dict[int, tuple[int, int]] = {}
                for block_index, block_text in selected:
                    content.extend(f"\n[PAGE {page_number} BLOCK {block_index}]\n".encode("ascii"))
                    content.extend(_canonical_json(citation))
                    content.extend(b"\n")
                    block_start = len(content)
                    content.extend(block_text.encode("utf-8"))
                    selected_map[block_index] = (block_start, len(content))
                    all_blocks[block_index]["byte_start"] = block_start
                    all_blocks[block_index]["byte_end"] = len(content)
                    content.extend(b"\n")
                selected_count += len(selected)
            else:
                selected_map = {}
            page_evidence.append({
                "page_number": page_number,
                "native_text_blocks_sha256": _sha("\n".join(native_hashes).encode("ascii")),
                "all_blocks": all_blocks,
                "selected_block_indices": [index for index, _ in selected],
                "excluded_blocks": excluded,
                "raster_image_count": len(image_boxes),
                "vector_drawing_count": len(vector_boxes),
                "third_party_page_signal": page_third_party_signal,
                "packet_signal_kinds": sorted(packet_signals.get(page_number, [])),
                "packet_pii_status": packet_artifact["source_pii_status"],
                "review_groups": [{
                    "group_index": group.group_index,
                    "group_count": group.group_count,
                    "block_indices": list(group.block_indices),
                    "group_text_sha256": group.text_sha256,
                    "citation": citation,
                    "byte_start": selected_map[group.block_indices[0]][0],
                    "byte_end": selected_map[group.block_indices[-1]][1],
                } for group in page_groups],
                "byte_start": start,
                "byte_end": len(content),
                "derived_page_text_sha256": _sha(bytes(content[start:])),
            })
    finally:
        document.close()
    if _file_hash(pdf_path)[0] != expected_sha256:
        raise DerivativeError("SOURCE_CHANGED_DURING_EXTRACTION")
    if _sha(POLICY_PATH.read_bytes()) != extraction_policy_sha256:
        raise DerivativeError("EXTRACTION_POLICY_CHANGED")
    if _sha(ADJUDICATION_POLICY_PATH.read_bytes()) != adjudication_policy_sha256:
        raise DerivativeError("ADJUDICATION_POLICY_CHANGED")
    if _sha(Path(__file__).read_bytes()) != generator_code_sha256:
        raise DerivativeError("GENERATOR_CODE_CHANGED")
    final_content = bytes(content) if selected_count else None
    derivative_sha = _sha(final_content) if final_content is not None else None
    if derivative_sha == expected_sha256:
        raise DerivativeError("DERIVATIVE_IDENTITY_COLLISION")
    evidence = {
        "kind": KIND,
        "source_content_sha256": expected_sha256,
        "source_file_size_bytes": size,
        "source_page_count": expected_page_count,
        "source_attribution": source_attribution,
        "publisher_proof": publisher_proof,
        "publisher_status": publisher_proof["status"],
        "source_packet_artifact_sha256": packet_sha,
        "extraction_policy_sha256": extraction_policy_sha256,
        "adjudication_policy_sha256": adjudication_policy_sha256,
        "generator_code_sha256": generator_code_sha256,
        "extractor_pymupdf_version": fitz.VersionBind,
        "normalization": "NFC_CRLF_TO_LF_STRIP_V1",
        "serialization_protocol": SERIALIZATION_PROTOCOL,
        "block_extraction": "page.get_text('blocks', sort=True)",
        "group_max_chars": MAX_GROUP_CHARS,
        "status": "PREPARED_PRIVATE" if final_content is not None else "EXCLUDE",
        "reason_codes": [] if final_content is not None else ["NO_ELIGIBLE_NATIVE_TEXT"],
        "derivative_content_sha256": derivative_sha,
        "derivative_media_type": "text/plain",
        "derivative_encoding": "utf-8",
        "derivative_byte_count": len(final_content) if final_content is not None else 0,
        "publication_authorized": False,
        "ocr_used": False,
        "images_copied": False,
        "graphic_renders_copied": False,
        "all_source_pages_inspected": True,
        "pages": page_evidence,
    }
    return TextCandidate(final_content, evidence, tuple(groups))


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def _write_exact(path: Path, raw: bytes, conflict: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise DerivativeError(conflict)
    if path.exists():
        if path.read_bytes() != raw:
            raise DerivativeError(conflict)
        return
    descriptor, temporary = tempfile.mkstemp(prefix=".student-rights-", dir=path.parent)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if path.exists() or path.is_symlink():
            if path.is_symlink() or path.read_bytes() != raw:
                raise DerivativeError(conflict)
        else:
            os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_private_candidate(
    candidate: TextCandidate,
    private_root: Path,
    evidence_root: Path,
) -> dict:
    """Écrit un candidat privé et son reçu CAS sans publier ses octets.

    Les chemins versionnables sont relatifs. La racine privée reste externe au
    dépôt et doit être fournie de nouveau au vérificateur indépendant.
    """
    repository_root = Path(__file__).resolve().parents[2]
    resolved_private = private_root.resolve()
    if resolved_private.is_relative_to(repository_root):
        raise DerivativeError("PRIVATE_ROOT_INSIDE_REPOSITORY")
    evidence = candidate.evidence
    source_sha = evidence.get("source_content_sha256")
    derivative_sha = evidence.get("derivative_content_sha256")
    if not isinstance(source_sha, str) or _SHA256.fullmatch(source_sha) is None:
        raise DerivativeError("DERIVATIVE_EVIDENCE_INVALID")
    if evidence.get("kind") != KIND or evidence.get("publication_authorized") is not False:
        raise DerivativeError("DERIVATIVE_EVIDENCE_INVALID")
    if _sha(Path(__file__).read_bytes()) != evidence.get("generator_code_sha256"):
        raise DerivativeError("GENERATOR_CODE_CHANGED")
    if _sha(POLICY_PATH.read_bytes()) != evidence.get("extraction_policy_sha256"):
        raise DerivativeError("EXTRACTION_POLICY_CHANGED")
    if _sha(ADJUDICATION_POLICY_PATH.read_bytes()) != evidence.get(
        "adjudication_policy_sha256"
    ):
        raise DerivativeError("ADJUDICATION_POLICY_CHANGED")
    if candidate.content is None:
        if evidence.get("status") != "EXCLUDE" or derivative_sha is not None:
            raise DerivativeError("DERIVATIVE_EVIDENCE_INVALID")
        relative_path = None
    else:
        if (evidence.get("status") != "PREPARED_PRIVATE"
            or not isinstance(derivative_sha, str)
            or _SHA256.fullmatch(derivative_sha) is None
            or _sha(candidate.content) != derivative_sha
            or len(candidate.content) != evidence.get("derivative_byte_count")
            or derivative_sha == source_sha):
            raise DerivativeError("DERIVATIVE_EVIDENCE_INVALID")
        relative_path = f"candidates/{derivative_sha}.txt"
        target = resolved_private / relative_path
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not target.parent.resolve().is_relative_to(resolved_private):
            raise DerivativeError("PRIVATE_CANDIDATE_PATH_ESCAPE")
        _write_exact(target, candidate.content, "PRIVATE_CANDIDATE_CONFLICT")
    receipt = {**evidence, "candidate_relpath": relative_path}
    receipt_bytes = _canonical_json(receipt)
    receipt_sha = _sha(receipt_bytes)
    receipt_path = evidence_root / "derivative_receipts" / receipt_sha[:2] / (
        f"{receipt_sha}.json"
    )
    _write_exact(receipt_path, receipt_bytes, "DERIVATIVE_RECEIPT_CONFLICT")
    checkpoint = {
        "kind": "NEXUS-STUDENT-DERIVATIVE-CHECKPOINT-V1",
        "source_content_sha256": source_sha,
        "derivative_content_sha256": derivative_sha,
        "derivative_receipt_sha256": receipt_sha,
        "status": evidence["status"],
        "candidate_relpath": relative_path,
    }
    checkpoint_path = evidence_root / "derivatives" / f"{source_sha}.json"
    _write_exact(checkpoint_path, _canonical_json(checkpoint),
                 "DERIVATIVE_CHECKPOINT_CONFLICT")
    return checkpoint


def _official_pdf_url(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and parsed.hostname == "eduscol.education.gouv.fr"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and parsed.path.lower().endswith(".pdf")
        )
    except ValueError:
        return False


def _provenance_checkpoint_sha256(checkpoint: dict) -> str | None:
    if checkpoint.get("kind") != "NEXUS-STUDENT-SOURCE-PROVENANCE-CHECKPOINT-V1":
        return None
    claimed = checkpoint.get("checkpoint_sha256")
    if not isinstance(claimed, str) or _SHA256.fullmatch(claimed) is None:
        return None
    without_digest = {key: value for key, value in checkpoint.items()
                      if key != "checkpoint_sha256"}
    computed = _sha(_canonical_json(without_digest) + b"\n")
    return claimed if computed == claimed else None


def _attribution_from_provenance(
    artifact: dict, checkpoint: dict, authority: dict, authority_sha256: str,
) -> dict | None:
    source_sha = artifact["content_sha256"]
    checkpoint_sha = _provenance_checkpoint_sha256(checkpoint)
    if checkpoint_sha is None or any((
        checkpoint.get("content_sha256") != source_sha,
        checkpoint.get("source_listing_url") != artifact.get("source_listing_url"),
        checkpoint.get("authority_yaml_sha256") != authority_sha256,
        checkpoint.get("rights_basis_kind") != "SITEWIDE_DOWNLOAD_AUTHORITY",
        checkpoint.get("rights_basis_status") != "CANDIDATE_PENDING_FINAL_APPROVAL",
        authority.get("status") != "SEALED_PENDING_FINAL_EXACT_HEAD_APPROVAL",
        authority.get("authority_kind") != "SITEWIDE_DOWNLOAD_AUTHORITY",
    )):
        return None
    source = checkpoint.get("source_provenance")
    if not isinstance(source, dict) or source.get("status") != "EXACT_CURRENT_SOURCE":
        return None
    current_ref = source.get("currentness_evidence_ref")
    revocation_ref = source.get("revocation_evidence_ref")
    listing_sha = source.get("listing_capture_receipt_sha256")
    if any((
        source.get("currentness_status") != "PASS",
        source.get("revocation_status") != "PASS_CURRENT_OFFICIAL_PUBLICATION",
        source.get("retraction_notice_associated") is not False,
        not isinstance(current_ref, dict),
        not isinstance(revocation_ref, dict),
        not isinstance(listing_sha, str),
        _SHA256.fullmatch(str(listing_sha)) is None,
        not isinstance(source.get("currentness_observed_at_utc"), str),
        not str(source.get("currentness_observed_at_utc")).endswith("Z"),
        not isinstance(source.get("revocation_observed_at_utc"), str),
        not str(source.get("revocation_observed_at_utc")).endswith("Z"),
    )):
        return None
    fetch = source.get("pdf_fetch")
    updated = source.get("source_updated_at")
    if not isinstance(fetch, dict) or not isinstance(updated, dict):
        return None
    pdf_url = fetch.get("final_url")
    request_url = fetch.get("requested_url")
    if any((
        not _official_pdf_url(pdf_url),
        not _official_pdf_url(request_url),
        fetch.get("content_sha256") != source_sha,
        fetch.get("http_status") != 200,
        type(fetch.get("byte_count")) is not int,
        not isinstance(fetch.get("byte_count"), int)
        or fetch["byte_count"] <= 0,
    )):
        return None
    anchor = source.get("matched_anchor")
    if not isinstance(anchor, dict) or anchor.get("href") != request_url:
        return None
    for reference in (current_ref, revocation_ref):
        if (reference.get("listing_capture_receipt_sha256") != listing_sha
            or reference.get("pdf_sha256") != source_sha
            or reference.get("pdf_url") != pdf_url):
            return None
    if not isinstance(revocation_ref.get("notice_scan"), str) or not revocation_ref[
        "notice_scan"
    ]:
        return None
    date = updated.get("date")
    date_kind = updated.get("kind")
    ref = updated.get("evidence_ref")
    if (not isinstance(date, str) or not date.endswith("Z")
        or not isinstance(ref, dict)
        or date_kind not in {
            "DATED_OFFICIAL_SNAPSHOT", "PDF_EXPLICIT_UPDATE_DATE",
            "PDF_EXPLICIT_PUBLICATION_DATE",
        }):
        return None
    try:
        datetime.fromisoformat(date.replace("Z", "+00:00"))
    except ValueError:
        return None
    if date_kind == "DATED_OFFICIAL_SNAPSHOT":
        if any((
            date != fetch.get("observed_at_utc"),
            ref.get("pdf_url") != pdf_url,
            ref.get("downloaded_sha256") != source_sha,
            ref.get("http_status") != 200,
            ref.get("listing_capture_receipt_sha256")
            != source.get("listing_capture_receipt_sha256"),
        )):
            return None
        notice = (
            "Source : Ministère de l’Éducation nationale – Dgesco / Éduscol. "
            f"Dérivé textuel de {pdf_url}, sous Licence Ouverte 2.0 ; "
            f"snapshot du {date}. PDF, images et OCR graphique non redistribués."
        )
    else:
        if any((
            ref.get("content_sha256") != source_sha,
            type(ref.get("page_number")) is not int,
            not isinstance(ref.get("block_id"), int),
            not isinstance(ref.get("block_sha256"), str),
            _SHA256.fullmatch(str(ref.get("block_sha256"))) is None,
            not isinstance(ref.get("extraction_protocol"), str),
        )):
            return None
        notice = (
            "Source : Ministère de l’Éducation nationale – Dgesco / Éduscol. "
            f"Dérivé textuel de {pdf_url}, sous Licence Ouverte 2.0 ; "
            f"date éditoriale vérifiée : {date}. "
            "PDF, images et OCR graphique non redistribués."
        )
    licensor = authority.get("licensor")
    licence_id = authority.get("licence_id")
    label = artifact.get("title")
    if any(not isinstance(value, str) or not value.strip()
           for value in (label, licensor, licence_id)):
        return None
    return {
        "source_uri": pdf_url,
        "source_label": label.strip(),
        "source_updated_at": date,
        "source_date_kind": date_kind,
        "licensor": licensor.strip(),
        "licence_id": licence_id.strip(),
        "derivative_notice": notice,
    }


def _excluded_without_attribution(
    artifact: dict, reason_code: str, packet_sha256: str,
    source_provenance_checkpoint_sha256: str | None,
    rights_authority_sha256: str,
) -> TextCandidate:
    try:
        extraction_policy_sha256 = _sha(POLICY_PATH.read_bytes())
        adjudication_policy_sha256 = _sha(ADJUDICATION_POLICY_PATH.read_bytes())
        generator_code_sha256 = _sha(Path(__file__).read_bytes())
    except OSError:
        raise DerivativeError("EXTRACTION_POLICY_UNAVAILABLE") from None
    return TextCandidate(None, {
        "kind": KIND,
        "source_content_sha256": artifact["content_sha256"],
        "source_page_count": artifact["page_count"],
        "source_packet_artifact_sha256": packet_sha256,
        "source_provenance_checkpoint_sha256": source_provenance_checkpoint_sha256,
        "rights_authority_sha256": rights_authority_sha256,
        "extraction_policy_sha256": extraction_policy_sha256,
        "adjudication_policy_sha256": adjudication_policy_sha256,
        "generator_code_sha256": generator_code_sha256,
        "status": "EXCLUDE",
        "publisher_status": "UNPROVEN",
        "reason_codes": [reason_code],
        "derivative_content_sha256": None,
        "publication_authorized": False,
    }, ())


def run_derivative_batch(
    packet_path: Path,
    source_mirror_root: Path,
    source_checkpoints_dir: Path,
    authority_yaml_path: Path,
    private_root: Path,
    evidence_root: Path,
    *, expected_count: int = 315,
) -> dict:
    """Checkpoint 315 décisions structurelles, sans autoriser leur publication."""
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    artifacts = packet.get("artifacts") if isinstance(packet, dict) else None
    if not isinstance(artifacts, list) or len(artifacts) != expected_count:
        raise DerivativeError("SOURCE_PACKET_POPULATION_MISMATCH")
    authority_raw = authority_yaml_path.read_bytes()
    authority = yaml.safe_load(authority_raw)
    if not isinstance(authority, dict):
        raise DerivativeError("AUTHORITY_INVALID")
    authority_sha = _sha(authority_raw)
    mirror = source_mirror_root.resolve()
    checkpoints_root = source_checkpoints_dir.resolve()
    seen: set[str] = set()
    counts = {"inventory_count": len(artifacts), "private_candidates": 0, "excluded": 0}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise DerivativeError("SOURCE_PACKET_ARTIFACT_INVALID")
        source_sha = artifact.get("content_sha256")
        if (not isinstance(source_sha, str) or _SHA256.fullmatch(source_sha) is None
            or source_sha in seen):
            raise DerivativeError("SOURCE_PACKET_ARTIFACT_INVALID")
        seen.add(source_sha)
        relative = artifact.get("source_path")
        if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
            raise DerivativeError("SOURCE_PATH_ESCAPE")
        pdf_path = (mirror / relative).resolve()
        if not pdf_path.is_relative_to(mirror):
            raise DerivativeError("SOURCE_PATH_ESCAPE")
        packet_sha = _sha(_canonical_json(artifact))
        provenance_path = checkpoints_root / f"{source_sha}.json"
        checkpoint: dict = {}
        if provenance_path.is_file() and provenance_path.resolve().is_relative_to(
            checkpoints_root
        ):
            try:
                parsed = json.loads(provenance_path.read_text(encoding="utf-8"))
                checkpoint = parsed if isinstance(parsed, dict) else {}
            except (OSError, ValueError):
                checkpoint = {}
        provenance_sha = _provenance_checkpoint_sha256(checkpoint)
        attribution = _attribution_from_provenance(
            artifact, checkpoint, authority, authority_sha
        )
        if attribution is None:
            candidate = _excluded_without_attribution(
                artifact, "SOURCE_PROVENANCE_INSUFFICIENT", packet_sha, provenance_sha,
                authority_sha,
            )
        else:
            candidate = build_text_candidate(
                pdf_path, source_sha, artifact["page_count"], attribution, artifact,
                captured_publisher_binding={
                    "kind": "OFFICIAL_CAPTURED_DOWNLOAD_PUBLISHER",
                    "listing_capture_receipt_sha256": checkpoint[
                        "source_provenance"
                    ]["listing_capture_receipt_sha256"],
                    "source_provenance_checkpoint_sha256": provenance_sha,
                    "rights_authority_sha256": authority_sha,
                    "source_content_sha256": source_sha,
                    "matched_anchor_href": checkpoint["source_provenance"][
                        "matched_anchor"
                    ]["href"],
                    "source_pdf_url": attribution["source_uri"],
                },
            )
            candidate = TextCandidate(candidate.content, {
                **candidate.evidence,
                "source_provenance_checkpoint_sha256": provenance_sha,
                "rights_authority_sha256": authority_sha,
            }, candidate.review_groups)
        sealed = write_private_candidate(candidate, private_root, evidence_root)
        counts["private_candidates" if sealed["status"] == "PREPARED_PRIVATE"
               else "excluded"] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packet", required=True, type=Path)
    parser.add_argument("--source-mirror-root", required=True, type=Path)
    parser.add_argument("--source-checkpoints-dir", required=True, type=Path)
    parser.add_argument("--authority-yaml", required=True, type=Path)
    parser.add_argument("--private-root", required=True, type=Path)
    parser.add_argument("--evidence-root", required=True, type=Path)
    args = parser.parse_args()
    result = run_derivative_batch(
        args.packet, args.source_mirror_root, args.source_checkpoints_dir,
        args.authority_yaml, args.private_root, args.evidence_root,
    )
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
