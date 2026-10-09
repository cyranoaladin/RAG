"""Revues A/B indépendantes des PDF, sans autorité décisionnelle directe.

Seules des observations codifiées et leurs empreintes sont retournées. Texte,
OCR, rendu et réponse brute du modèle restent en mémoire pendant l'appel.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import math
import os
import re
import secrets
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from student_rights_pdf_scan import _hash_file, _ocr_text, _render_png

ROOT = Path(__file__).resolve().parents[2]
PROMPT_A = ROOT / "governance/student_public_rights/prompts/reviewer_a_v1.txt"
PROMPT_B = ROOT / "governance/student_public_rights/prompts/reviewer_b_v1.txt"
VISION_MODELS = frozenset({
    "qwen3-vl:2b", "qwen2.5vl:3b", "moondream:latest", "granite3.2-vision:2b",
})
MAX_CHARS_PER_SEGMENT = 4000
VISION_RENDER_SCALE = 0.5
MAX_VISION_PIXELS = 150_000
TEXT_ASSEMBLY_PROTOCOL = "NEXUS_REVIEW_TEXT_ASSEMBLY_V5"
REASON_CODE = re.compile(r"[A-Z][A-Z0-9_]*\Z")
ALLOWED_REASON_CODES = frozenset({
    "RIGHTS_NOTICE_ABSENT", "RESTRICTIVE_NOTICE", "THIRD_PARTY_UNLICENSED",
    "LICENSE_CONFLICT", "SOURCE_STALE", "REVOCATION_SIGNAL", "RIGHTS_UNCLEAR",
    "PII_SIGNAL", "FACE_SIGNAL", "TEACHER_ONLY",
    "TEACHER_NON_DISCLOSURE_INSTRUCTION", "ANSWER_KEY", "CORRECTION",
    "UNSUITABLE_FOR_STUDENT", "VISUAL_UNCLEAR", "ANNEX_UNCHECKED",
})


class ReviewError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _observation_schema(payload: dict, *, image_present: bool) -> dict:
    page = payload["page_number"]
    domain = payload["review_domain"]
    properties = {
        "page_number": {"const": page},
        "segment_index": {"const": payload["segment_index"]},
        "segment_count": {"const": payload["segment_count"]},
        "verdict": {"enum": ["PASS", "FAIL"]},
        "confidence": {"enum": ["HIGH", "LOW", "UNKNOWN"]},
        "reason_codes": {"type": "array", "items": {"enum": sorted(
            {"RIGHTS_NOTICE_ABSENT", "RESTRICTIVE_NOTICE", "THIRD_PARTY_UNLICENSED",
             "LICENSE_CONFLICT", "SOURCE_STALE", "REVOCATION_SIGNAL", "RIGHTS_UNCLEAR",
             "VISUAL_UNCLEAR", "ANNEX_UNCHECKED"}
            if domain == "reviewer_a" else
            {"PII_SIGNAL", "FACE_SIGNAL", "TEACHER_ONLY",
             "TEACHER_NON_DISCLOSURE_INSTRUCTION", "ANSWER_KEY", "CORRECTION",
             "UNSUITABLE_FOR_STUDENT", "VISUAL_UNCLEAR", "ANNEX_UNCHECKED"}
        )}},
        "evidence_pages": {"type": "array", "prefixItems": [{"const": page}],
                           "minItems": 1, "maxItems": 1},
        "visual_examined": {"type": "boolean"} if image_present else {"const": False},
    }
    if domain == "reviewer_a":
        properties["positive_rights_notice_present"] = {"type": "boolean"}
    return {
        "type": "object", "additionalProperties": False,
        "required": list(properties), "properties": properties,
    }


class OllamaTransport:
    """Client stateless vers Ollama local uniquement : un appel = un contexte."""

    supports_vision = True

    def __call__(
        self,
        model_id: str,
        system_prompt: str,
        user_payload: dict,
        parameters: dict,
        image_png: bytes | None,
    ) -> dict:
        if model_id == "granite3.2-vision:2b":
            body: dict = {
                "model": model_id,
                "stream": False,
                "format": _observation_schema(user_payload, image_present=image_png is not None),
                "options": parameters,
                "prompt": system_prompt + "\n\n" + json.dumps(user_payload, ensure_ascii=False),
            }
            if image_png is not None:
                body["images"] = [base64.b64encode(image_png).decode("ascii")]
            endpoint = "generate"
        else:
            user_message: dict = {
                "role": "user", "content": json.dumps(user_payload, ensure_ascii=False)
            }
            if image_png is not None:
                user_message["images"] = [base64.b64encode(image_png).decode("ascii")]
            body = {
                "model": model_id,
                "stream": False,
                "format": "json",
                "options": parameters,
                "messages": [{"role": "system", "content": system_prompt}, user_message],
            }
            endpoint = "chat"
        request_body = _canonical_bytes(body)
        request = urllib.request.Request(
            f"http://127.0.0.1:11434/api/{endpoint}",
            data=request_body,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw_response = response.read(1024 * 1024)
        except urllib.error.HTTPError as exc:
            raise ReviewError(f"MODEL_HTTP_{exc.code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ReviewError("MODEL_TRANSPORT_FAILED") from None
        try:
            envelope = json.loads(raw_response)
            content = (
                envelope["response"] if endpoint == "generate"
                else envelope["message"]["content"]
            )
            return json.loads(content)
        except (ValueError, KeyError, TypeError):
            raise ReviewError("MODEL_INVALID_JSON") from None


def _validate_observation(
    value: object, page: int, segment: int, count: int, reviewer_domain: str,
    *, image_present: bool,
) -> dict:
    expected_keys = {
        "page_number", "segment_index", "segment_count", "verdict", "confidence",
        "reason_codes", "evidence_pages", "visual_examined",
    }
    if reviewer_domain == "reviewer_a":
        expected_keys.add("positive_rights_notice_present")
    if not isinstance(value, dict) or set(value) != expected_keys:
        raise ReviewError("MODEL_INVALID_OUTPUT")
    if (
        value["page_number"] != page
        or value["segment_index"] != segment
        or value["segment_count"] != count
        or value["verdict"] not in ("PASS", "FAIL")
        or value["confidence"] not in ("HIGH", "LOW", "UNKNOWN")
        or value["evidence_pages"] != [page]
        or type(value["visual_examined"]) is not bool
        or (not image_present and value["visual_examined"] is True)
        or (reviewer_domain == "reviewer_a"
            and type(value["positive_rights_notice_present"]) is not bool)
        or not isinstance(value["reason_codes"], list)
        or not all(isinstance(code, str) and REASON_CODE.fullmatch(code)
                   and code in ALLOWED_REASON_CODES
                   for code in value["reason_codes"])
    ):
        raise ReviewError("MODEL_INVALID_OUTPUT")
    return value


def _segments(text: str, max_chars: int) -> list[str]:
    return [text[start:start + max_chars] for start in range(0, len(text), max_chars)] or [""]


def _vision_render_png(page, fitz, max_scale: float) -> bytes:
    """Rendu visuel borné ; OCR et empreinte scanner restent à leur résolution."""
    area = page.rect.width * page.rect.height
    if area <= 0:
        raise ReviewError("VISION_RENDER_SIZE_EXCEEDED")
    scale = min(max_scale, math.sqrt(MAX_VISION_PIXELS / area))
    for _ in range(8):
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        if pixmap.width * pixmap.height <= MAX_VISION_PIXELS:
            return pixmap.tobytes("png")
        scale *= 0.995
    raise ReviewError("VISION_RENDER_SIZE_EXCEEDED")


def _residual_ocr(extracted: str, ocr: str) -> tuple[str, int]:
    """Supprime seulement les lignes OCR identiques après casse/espaces.

    Toute ligne nouvelle ou même légèrement différente reste examinée.
    """
    extracted_lines = {" ".join(line.casefold().split()) for line in extracted.splitlines()}
    retained: list[str] = []
    discarded = 0
    for line in ocr.splitlines(keepends=True):
        normalized = " ".join(line.casefold().split())
        if normalized and normalized in extracted_lines:
            discarded += 1
        else:
            retained.append(line)
    return "".join(retained), discarded


def _project_metadata(document) -> tuple[str, list[bytes], dict]:
    """Expose chaque valeur XMP sémantique unique et isole les images XMP.

    L'empreinte de l'XML complet demeure dans les faits; chaque image extraite
    devient un segment visuel distinct, jamais une chaîne base64 destinée au LLM.
    """
    xml = document.get_xml_metadata()
    if len(xml) > 2_000_000 or "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ReviewError("PDF_XMP_UNSAFE_OR_TOO_LARGE")
    records: list[list[str]] = []
    seen: set[tuple[str, str, str]] = set()
    duplicate_count = 0
    images: list[bytes] = []
    namespace_table: dict[str, str] = {}
    if xml.strip():
        try:
            root = ET.fromstring(xml)
        except ET.ParseError:
            raise ReviewError("PDF_XMP_PARSE_FAILED") from None
        uris = sorted({
            name[1:].split("}", 1)[0]
            for element in root.iter()
            for name in (element.tag, *element.attrib)
            if name.startswith("{") and "}" in name
        })
        namespace_table = {f"n{number}": uri for number, uri in enumerate(uris)}
        by_uri = {uri: prefix for prefix, uri in namespace_table.items()}

        def qname(name: str) -> str:
            if name.startswith("{") and "}" in name:
                uri, local = name[1:].split("}", 1)
                return f"{by_uri[uri]}:{local}"
            return name

        for element in root.iter():
            candidates = [("@" + qname(key), value)
                          for key, value in sorted(element.attrib.items())]
            candidates.extend((("#text", element.text), ("#tail", element.tail)))
            for kind, original in candidates:
                if original is None or not original.strip():
                    continue
                value = original.strip()
                if kind == "#text" and element.tag.rsplit("}", 1)[-1].lower() == "image":
                    try:
                        encoded = "".join(value.split())
                        raw = (
                            base64.b64decode(encoded, validate=True)
                            if len(encoded) >= 16 and len(encoded) % 4 == 0
                            else None
                        )
                    except (ValueError, binascii.Error):
                        raw = None
                    if raw is not None:
                        try:
                            if not (
                                raw.startswith(b"\x89PNG\r\n\x1a\n")
                                or raw.startswith(b"\xff\xd8")
                            ):
                                raise ValueError("unsupported embedded image")
                            import fitz

                            pixmap = fitz.Pixmap(raw)
                            if pixmap.width * pixmap.height > 4_000_000:
                                raise ValueError("embedded image too large")
                        except (ValueError, OSError, OverflowError, RuntimeError):
                            raise ReviewError("PDF_XMP_IMAGE_UNVERIFIED") from None
                        images.append(raw)
                        value = f"[EMBEDDED_IMAGE_SHA256:{hashlib.sha256(raw).hexdigest()}]"
                record = (qname(element.tag), kind, value)
                if record in seen:
                    duplicate_count += 1
                    continue
                seen.add(record)
                records.append(list(record))
    projection = "[PDF_METADATA_V2]\n" + json.dumps(
        {"info": document.metadata, "xmp_namespaces": namespace_table,
         "xmp_entries": records},
        sort_keys=True, ensure_ascii=False,
    ) + "\n"
    facts = {
        "xmp_full_sha256": hashlib.sha256(xml.encode("utf-8")).hexdigest(),
        "xmp_projection_sha256": hashlib.sha256(projection.encode("utf-8")).hexdigest(),
        "xmp_unique_value_count": len(records),
        "xmp_duplicate_value_count": duplicate_count,
        "xmp_embedded_image_count": len(images),
        "xmp_embedded_image_sha256": [hashlib.sha256(raw).hexdigest() for raw in images],
    }
    return projection, images, facts


def _checkpoint_file(root: Path, request_sha256: str) -> Path:
    return root / request_sha256[:2] / f"{request_sha256}.json"


def _read_checkpoint(root: Path | None, request_sha256: str) -> dict | None:
    if root is None:
        return None
    path = _checkpoint_file(root, request_sha256)
    try:
        stat = path.stat()
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            return None
        record = json.loads(path.read_bytes())
        observation = record["observation"]
        if (
            record["kind"] != "NEXUS-REVIEW-SEGMENT-CHECKPOINT-V1"
            or record["request_sha256"] != request_sha256
            or record["observation_sha256"] != hashlib.sha256(
                _canonical_bytes(observation)
            ).hexdigest()
        ):
            return None
        return observation
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _write_checkpoint(root: Path | None, request_sha256: str, observation: dict) -> None:
    if root is None:
        return
    path = _checkpoint_file(root, request_sha256)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_mode & 0o077:
        raise ReviewError("CHECKPOINT_PERMISSIONS_INVALID")
    record = {
        "kind": "NEXUS-REVIEW-SEGMENT-CHECKPOINT-V1",
        "request_sha256": request_sha256,
        "observation_sha256": hashlib.sha256(_canonical_bytes(observation)).hexdigest(),
        "observation": observation,
    }
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(_canonical_bytes(record))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _write_receipt(root: Path, receipt: dict) -> str:
    raw = _canonical_bytes(receipt)
    digest = hashlib.sha256(raw).hexdigest()
    path = root / digest[:2] / f"{digest}.json"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.stat().st_mode & 0o077:
        raise ReviewError("RECEIPT_PERMISSIONS_INVALID")
    if path.exists():
        if path.read_bytes() != raw:
            raise ReviewError("RECEIPT_CAS_COLLISION")
        return digest
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return digest


def _reviewer_state(
    identity: str, prompt_path: Path, model_id: str, model_version: str, parameters: dict
) -> dict:
    prompt_bytes = prompt_path.read_bytes()
    return {
        "identity": identity,
        "prompt": prompt_bytes.decode("utf-8"),
        "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
        "model_id": model_id,
        "model_version": model_version,
        "parameters_sha256": hashlib.sha256(_canonical_bytes(parameters)).hexdigest(),
        "context_hash": hashlib.sha256(),
        "observation_hash": hashlib.sha256(),
        "valid_segments": {},
        "segments_required": {},
        "failed": False,
        "low_confidence": False,
        "model_fail": False,
        "visual_unverified": set(),
        "evidence_refs": [],
        "error_codes": set(),
        "reason_by_page": {},
        "rights_pages": set(),
    }


def review_document(
    path: Path,
    expected_sha256: str,
    *,
    transport: Callable[[str, str, dict, dict, bytes | None], dict] | None = None,
    model_id: str,
    model_version: str,
    parameters: dict,
    rights_evidence_positive: bool = False,
    vision_enabled: bool = False,
    max_chars_per_segment: int = 4000,
    checkpoint_dir: Path | None = None,
    receipt_dir: Path | None = None,
    vision_render_scale: float = 0.5,
    run_nonce: int = 0,
) -> dict:
    """Examine toutes les pages deux fois, avec prompts et appels indépendants.

    `rights_evidence_positive` doit provenir d'un contrôle externe opposable ;
    même vrai, le moteur déterministe indépendant décide seul la disposition.
    """
    if (
        max_chars_per_segment != MAX_CHARS_PER_SEGMENT
        or parameters.get("temperature") != 0
        or vision_render_scale != VISION_RENDER_SCALE
        or type(run_nonce) is not int or run_nonce not in (0, 1)
    ):
        raise ReviewError("REVIEW_PARAMETERS_INVALID")
    try:
        digest, _ = _hash_file(path)
    except OSError:
        raise ReviewError("PDF_UNREADABLE") from None
    if digest != expected_sha256:
        raise ReviewError("PDF_SHA256_MISMATCH")
    try:
        import fitz

        document = fitz.open(path)
    except (ImportError, RuntimeError, ValueError):
        raise ReviewError("PDF_OPEN_FAILED") from None
    if document.is_encrypted:
        document.close()
        raise ReviewError("PDF_ENCRYPTED")
    if document.embfile_count():
        document.close()
        raise ReviewError("PDF_EMBEDDED_FILES_UNSUPPORTED")

    states = {
        "reviewer_a": _reviewer_state(
            "nexus-reviewer-a-automated-v1", PROMPT_A, model_id, model_version, parameters
        ),
        "reviewer_b": _reviewer_state(
            "nexus-reviewer-b-automated-v1", PROMPT_B, model_id, model_version, parameters
        ),
    }
    client = transport or OllamaTransport()
    vision_active = vision_enabled and model_id in VISION_MODELS and getattr(
        client, "supports_vision", False
    ) is True
    page_count = len(document)
    text_assembly: list[dict] = []
    try:
        metadata_projection, xmp_images, metadata_facts = _project_metadata(document)
        for page_index in range(page_count):
            page = document.load_page(page_index)
            page_number = page_index + 1
            extracted = page.get_text("text", sort=True)
            if page.first_widget is not None:
                raise ReviewError("PDF_FORM_WIDGET_UNSUPPORTED")
            annotations = []
            for annotation in page.annots() or ():
                if annotation.type[1] == "FileAttachment":
                    raise ReviewError("PDF_ATTACHMENT_ANNOTATION_UNSUPPORTED")
                annotations.append({"type": annotation.type[1], "info": annotation.info})
            metadata = metadata_projection if page_index == 0 else ""
            page_xmp_images = xmp_images if page_index == 0 else []
            annotations_text = (
                "\n[ANNOTATIONS_AND_LINKS]\n" + json.dumps(
                    {"annotations": annotations, "links": page.get_links()},
                    sort_keys=True, ensure_ascii=False, default=str,
                )
                if annotations or page.get_links() else ""
            )
            graphic = (
                bool(page.get_image_info()) or bool(page.get_drawings())
                or bool(annotations)
            )
            png = None
            vision_png = None
            ocr = ""
            if graphic:
                png, _ = _render_png(page, fitz)
                ocr = _ocr_text(png)
                vision_png = _vision_render_png(page, fitz, vision_render_scale)
            residual_ocr, discarded_ocr_lines = _residual_ocr(extracted, ocr)
            combined = metadata + extracted + annotations_text + (
                "\n[OCR_RESIDUAL]\n" + residual_ocr if residual_ocr else ""
            )
            chunks = _segments(combined, max_chars_per_segment)
            segment_images: dict[int, bytes] = {}
            visual_indices: set[int] = set()
            if graphic:
                page_render_sha = hashlib.sha256(vision_png).hexdigest()
                chunks.insert(0, f"[PDF_PAGE_RENDER_SHA256:{page_render_sha}]\n")
                visual_indices.add(1)
                segment_images[1] = vision_png
            for embedded_image in page_xmp_images:
                image_sha = hashlib.sha256(embedded_image).hexdigest()
                chunks.append(f"[XMP_EMBEDDED_IMAGE_SHA256:{image_sha}]\n")
                visual_indices.add(len(chunks))
                segment_images[len(chunks)] = embedded_image
            page_facts = {
                "page_number": page_number,
                "assembly_protocol": TEXT_ASSEMBLY_PROTOCOL,
                "extracted_text_sha256": hashlib.sha256(extracted.encode("utf-8")).hexdigest(),
                "ocr_full_sha256": hashlib.sha256(ocr.encode("utf-8")).hexdigest(),
                "ocr_residual_sha256": hashlib.sha256(
                    residual_ocr.encode("utf-8")
                ).hexdigest(),
                "ocr_exact_duplicate_lines_removed": discarded_ocr_lines,
                "segment_count": len(chunks),
                "visual_segment_indices": sorted(visual_indices),
            }
            if page_index == 0:
                page_facts.update(metadata_facts)
            text_assembly.append(page_facts)
            for label, state in states.items():
                state["segments_required"][page_number] = len(chunks)
                if visual_indices and not vision_active:
                    state["visual_unverified"].add(page_number)
                for segment_index, chunk in enumerate(chunks, 1):
                    image = segment_images.get(segment_index) if vision_active else None
                    payload = {
                        "page_number": page_number,
                        "segment_index": segment_index,
                        "segment_count": len(chunks),
                        "page_text_segment": chunk,
                        "page_has_graphics": graphic or bool(page_xmp_images),
                        "review_domain": label,
                    }
                    image_sha256 = hashlib.sha256(image).hexdigest() if image else None
                    request_bytes = _canonical_bytes({
                        "content_sha256": expected_sha256,
                        "assembly_protocol": TEXT_ASSEMBLY_PROTOCOL,
                        "run_nonce": run_nonce,
                        "reviewer_identity": state["identity"],
                        "model_id": model_id,
                        "model_version": model_version,
                        "parameters_sha256": state["parameters_sha256"],
                        "prompt_sha256": state["prompt_sha256"],
                        "payload": payload,
                        "image_sha256": image_sha256,
                    })
                    state["context_hash"].update(request_bytes)
                    request_sha256 = hashlib.sha256(request_bytes).hexdigest()
                    try:
                        cached = _read_checkpoint(checkpoint_dir, request_sha256)
                        observation = _validate_observation(
                            cached if cached is not None else client(
                                model_id, state["prompt"], payload, parameters, image
                            ),
                            page_number, segment_index, len(chunks), label,
                            image_present=image is not None,
                        )
                        if cached is None:
                            _write_checkpoint(checkpoint_dir, request_sha256, observation)
                        if receipt_dir is not None:
                            receipt_sha = _write_receipt(receipt_dir, {
                                "kind": "NEXUS-STUDENT-REVIEW-SEGMENT-RECEIPT-V1",
                                "content_sha256": expected_sha256,
                                "assembly_protocol": TEXT_ASSEMBLY_PROTOCOL,
                                "run_nonce": run_nonce,
                                "reviewer_identity": state["identity"],
                                "page_number": page_number,
                                "segment_index": segment_index,
                                "segment_count": len(chunks),
                                "model_id": model_id,
                                "model_version": model_version,
                                "prompt_sha256": state["prompt_sha256"],
                                "parameters_sha256": state["parameters_sha256"],
                                "request_sha256": request_sha256,
                                "image_sha256": image_sha256,
                                "observation_sha256": hashlib.sha256(
                                    _canonical_bytes(observation)
                                ).hexdigest(),
                                "observation": observation,
                            })
                            evidence_ref = f"sha256:{receipt_sha}"
                        else:
                            evidence_ref = f"page:{page_number}:segment:{segment_index}"
                    except ReviewError as exc:
                        state["failed"] = True
                        state["error_codes"].add(exc.reason_code)
                        continue
                    except TimeoutError:
                        state["failed"] = True
                        state["error_codes"].add("MODEL_TIMEOUT")
                        continue
                    except Exception:
                        state["failed"] = True
                        state["error_codes"].add("MODEL_CALL_OR_PARSE_FAILED")
                        continue
                    state["observation_hash"].update(_canonical_bytes(observation))
                    state["valid_segments"].setdefault(page_number, set()).add(segment_index)
                    state["evidence_refs"].append(evidence_ref)
                    if observation["verdict"] != "PASS":
                        state["model_fail"] = True
                    for code in observation["reason_codes"]:
                        state["reason_by_page"].setdefault(page_number, set()).add(code)
                        state["model_fail"] = True
                    if observation["confidence"] != "HIGH":
                        state["low_confidence"] = True
                    if (
                        label == "reviewer_a"
                        and observation["positive_rights_notice_present"] is True
                        and observation["verdict"] == "PASS"
                        and observation["confidence"] == "HIGH"
                        and not observation["reason_codes"]
                    ):
                        state["rights_pages"].add(page_number)
                    if segment_index in visual_indices and not (
                        image is not None and observation["visual_examined"] is True
                    ):
                        state["visual_unverified"].add(page_number)
    except Exception:
        for state in states.values():
            state["failed"] = True
            state["error_codes"].add("PDF_PAGE_REVIEW_FAILED")
    finally:
        document.close()

    try:
        digest_after, _ = _hash_file(path)
    except OSError:
        raise ReviewError("PDF_CHANGED_DURING_REVIEW") from None
    if digest_after != expected_sha256:
        raise ReviewError("PDF_CHANGED_DURING_REVIEW")

    result: dict = {"diagnostics": {}, "text_assembly": text_assembly,
                    "assembly_protocol": TEXT_ASSEMBLY_PROTOCOL}
    restriction_pages: dict[str, set[int]] = {}
    for label, state in states.items():
        pages_covered = sorted(
            page for page, seen in state["valid_segments"].items()
            if len(seen) == state["segments_required"].get(page)
        )
        all_pages = pages_covered == list(range(1, page_count + 1))
        complete = not state["failed"] and not state["visual_unverified"] and all_pages
        text_stage_pass = (
            not state["failed"] and not state["model_fail"]
            and not state["low_confidence"] and all_pages
        )
        verdict = "PASS" if (
            complete and text_stage_pass and (
                label != "reviewer_a" or (
                    rights_evidence_positive and bool(state["rights_pages"])
                )
            )
        ) else "FAIL"
        result[label] = {
            "identity": state["identity"],
            "model_id": state["model_id"],
            "model_version": state["model_version"],
            "prompt_sha256": state["prompt_sha256"],
            "parameters_sha256": state["parameters_sha256"],
            "verdict": verdict,
            "complete": complete,
            "confidence": "HIGH" if text_stage_pass and complete else "LOW",
            "pages_covered": pages_covered,
            "context_sha256": state["context_hash"].hexdigest(),
            "observation_sha256": state["observation_hash"].hexdigest(),
            "evidence_refs": state["evidence_refs"],
        }
        result["diagnostics"][label] = {
            "text_stage_pass": text_stage_pass,
            "visual_pages_unverified": sorted(state["visual_unverified"]),
            "error_codes": sorted(state["error_codes"]),
            "reason_codes_by_page": {
                str(page): sorted(codes)
                for page, codes in sorted(state["reason_by_page"].items())
            },
        }
        for page, codes in state["reason_by_page"].items():
            for code in codes:
                restriction_pages.setdefault(code, set()).add(page)
    result["restriction_signals"] = [
        {"code": code, "pages": sorted(pages)}
        for code, pages in sorted(restriction_pages.items())
    ]
    result["rights_evidence_pages"] = sorted(states["reviewer_a"]["rights_pages"])
    return result


def _write_private_summary(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    raw = _canonical_bytes(value)
    temporary = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _valid_summary(path: Path, sha: str, signature: str, receipt_root: Path) -> bool:
    try:
        stat = path.stat()
        if stat.st_uid != os.getuid() or stat.st_mode & 0o077:
            return False
        summary = json.loads(path.read_bytes())
        if (
            summary.get("content_sha256") != sha
            or summary.get("run_signature_sha256") != signature
            or summary.get("summary_sha256") != hashlib.sha256(_canonical_bytes({
                key: value for key, value in summary.items() if key != "summary_sha256"
            })).hexdigest()
        ):
            return False
        for label in ("reviewer_a", "reviewer_b"):
            if summary[label].get("complete") is not True:
                return False
        replays = summary.get("candidate_replays", [])
        if replays:
            if len(replays) != 2 or [row.get("run_nonce") for row in replays] != [0, 1]:
                return False
            for label in ("reviewer_a", "reviewer_b"):
                if (
                    replays[0].get(f"{label}_evidence_refs")
                    != summary[label]["evidence_refs"]
                    or replays[0].get(f"{label}_observation_sha256")
                    != summary[label]["observation_sha256"]
                    or replays[0].get(f"{label}_context_sha256")
                    != summary[label]["context_sha256"]
                    or set(replays[0].get(f"{label}_evidence_refs", []))
                    & set(replays[1].get(f"{label}_evidence_refs", []))
                ):
                    return False
        ref_sets = [summary[label]["evidence_refs"] for label in ("reviewer_a", "reviewer_b")]
        for replay in replays:
            ref_sets.extend(replay[f"{label}_evidence_refs"] for label in (
                "reviewer_a", "reviewer_b"
            ))
        for refs in ref_sets:
            if not refs or not all(isinstance(ref, str) and ref.startswith("sha256:") for ref in refs):
                return False
            for ref in refs:
                digest = ref.split(":", 1)[1]
                if not re.fullmatch(r"[0-9a-f]{64}", digest):
                    return False
                raw = (receipt_root / digest[:2] / f"{digest}.json").read_bytes()
                if hashlib.sha256(raw).hexdigest() != digest:
                    return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
        return False


def _candidate_replay_row(run_index: int, result: dict) -> dict:
    a = result["reviewer_a"]
    b = result["reviewer_b"]
    return {
        "run_index": run_index,
        "run_nonce": run_index - 1,
        "reviewer_a_observation_sha256": a["observation_sha256"],
        "reviewer_b_observation_sha256": b["observation_sha256"],
        "reviewer_a_context_sha256": a["context_sha256"],
        "reviewer_b_context_sha256": b["context_sha256"],
        "reviewer_a_evidence_refs": a["evidence_refs"],
        "reviewer_b_evidence_refs": b["evidence_refs"],
        "candidate_verdict": "PASS" if (
            a["verdict"] == b["verdict"] == "PASS"
            and a["complete"] is b["complete"] is True
        ) else "FAIL",
    }


def _safety_statuses(result: dict) -> tuple[str, str]:
    signals = {item["code"] for item in result["restriction_signals"]}
    b = result["reviewer_b"]
    if signals & {"PII_SIGNAL", "FACE_SIGNAL"}:
        pii = "FAIL"
    elif b["complete"] is True and b["confidence"] == "HIGH" and b["verdict"] == "PASS":
        pii = "PASS"
    else:
        pii = "UNVERIFIABLE"
    third_party = (
        "RESTRICTED" if signals & {"THIRD_PARTY_UNLICENSED", "LICENSE_CONFLICT"}
        else "UNVERIFIABLE"
    )
    return pii, third_party


def _confined_source_path(mirror_root: Path, relative_path: str) -> Path:
    if (
        not isinstance(relative_path, str) or not relative_path
        or "\x00" in relative_path or "\\" in relative_path
    ):
        raise ReviewError("REVIEW_SOURCE_PATH_INVALID")
    relative = Path(relative_path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ReviewError("REVIEW_SOURCE_PATH_INVALID")
    try:
        root = mirror_root.resolve(strict=True)
        candidate = (root / relative).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise ReviewError("REVIEW_PDF_UNREADABLE") from None
    if not candidate.is_relative_to(root) or not candidate.is_file():
        raise ReviewError("REVIEW_SOURCE_PATH_INVALID")
    return candidate


def _rights_signal_from_source(
    artifact: dict, checkpoint_root: Path | None, receipt_root: Path | None
) -> bool:
    """N'admet qu'un signal de droits externe dont le reçu CAS est relisible.

    Ce signal ne décide pas la publication ni la couverture des éléments tiers.
    """
    if checkpoint_root is None or receipt_root is None:
        return False
    sha = artifact.get("content_sha256")
    if not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None:
        return False
    try:
        checkpoint = json.loads((checkpoint_root / f"{sha}.json").read_bytes())
        identity = checkpoint["source_identity"]
        rights = checkpoint["rights_check"]
        verification = rights["source_verification"]
        receipt_sha = rights["source_receipt_sha256"]
        if not isinstance(receipt_sha, str) or re.fullmatch(r"[0-9a-f]{64}", receipt_sha) is None:
            return False
        receipt_raw = (receipt_root / receipt_sha[:2] / f"{receipt_sha}.json").read_bytes()
        if hashlib.sha256(receipt_raw).hexdigest() != receipt_sha:
            return False
        receipt = json.loads(receipt_raw)
        source_checker_sha = hashlib.sha256(
            (ROOT / "scripts/go_live/student_rights_source_check.py").read_bytes()
        ).hexdigest()
    except (OSError, ValueError, KeyError, TypeError):
        return False
    basis = rights.get("rights_basis")
    if basis not in {
        "NEXUS_FIRST_PARTY_OWNED_WITH_REGISTRY_PROOF",
        "EXPLICIT_OPEN_LICENSE_WITH_EXACT_NOTICE",
        "EXPLICIT_REUSE_TERMS_COVERING_THE_AUTHORIZED_USE",
        "PUBLIC_DOMAIN_OR_EQUIVALENT_WITH_VERIFIABLE_BASIS",
    }:
        return False
    listing_uri = artifact.get("source_listing_url")
    exact_uri = identity.get("exact_pdf_uri")
    if (
        identity.get("status") != "VERIFIED"
        or identity.get("source_identity_verified") is not True
        or identity.get("exact_bytes_match") is not True
        or identity.get("source_uri") != listing_uri
        or identity.get("remote_pdf_sha256") != sha
        or identity.get("downloaded_sha256") != sha
        or not isinstance(exact_uri, str) or not exact_uri.startswith("https://")
        or verification.get("status") != "VERIFIED"
        or verification.get("exact_pdf_uri") != exact_uri
        or verification.get("remote_pdf_sha256") != sha
        or rights.get("currentness_status") != "PASS"
        or rights.get("revocation_status") != "PASS"
        or not isinstance(rights.get("rights_evidence_uri"), str)
        or not rights["rights_evidence_uri"].startswith("https://")
        or not isinstance(rights.get("license_or_terms_excerpt_hash"), str)
        or verification.get("terms_sha256") != rights["license_or_terms_excerpt_hash"]
        or receipt.get("kind") != "NEXUS-STUDENT-SOURCE-RIGHTS-RECEIPT-V1"
        or receipt.get("artifact_content_sha256") != sha
        or receipt.get("listing_uri") != listing_uri
        or receipt.get("pdf", {}).get("content_sha256") != sha
        or receipt.get("pdf", {}).get("final_uri") != exact_uri
        or receipt.get("legal_terms", {}).get("body_sha256")
        != rights["license_or_terms_excerpt_hash"]
        or receipt.get("license", {}).get("body_sha256")
        != rights.get("license_snapshot_sha256")
        or receipt.get("source_checker_code_sha256") != source_checker_sha
        or receipt.get("transport_kind") != "URLLIB_HTTPS_GET_NO_REDIRECT_V1"
    ):
        return False
    return True


def run_review_batch(
    packet_path: Path,
    source_mirror_root: Path,
    pack_dir: Path,
    *,
    artifact_sha256: str | None,
    model_id: str,
    model_version: str,
    parameters: dict,
    transport: Callable[[str, str, dict, dict, bytes | None], dict] | None = None,
    vision_render_scale: float = 0.5,
    rights_evidence_by_sha: dict[str, bool] | None = None,
    source_checkpoint_dir: Path | None = None,
    source_receipt_dir: Path | None = None,
) -> dict:
    """Rejoue une revue par SHA exact, avec reprise privée et reçus CAS.

    `rights_evidence_by_sha` est un signal externe, jamais une preuve de droit ;
    la garde indépendante doit vérifier les termes et leur portée.
    """
    if vision_render_scale != VISION_RENDER_SCALE:
        raise ReviewError("REVIEW_PARAMETERS_INVALID")
    if source_checkpoint_dir is not None and not source_checkpoint_dir.is_dir():
        raise ReviewError("REVIEW_SOURCE_CHECKPOINTS_UNAVAILABLE")
    try:
        packet_bytes = packet_path.read_bytes()
        entries = json.loads(packet_bytes)["artifacts"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ReviewError("REVIEW_INVENTORY_INVALID") from None
    if not isinstance(entries, list) or len(entries) != 315:
        raise ReviewError("REVIEW_INVENTORY_INVALID")
    inventory: dict[str, int] = {}
    source_paths: dict[str, str] = {}
    artifacts: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ReviewError("REVIEW_INVENTORY_INVALID")
        sha = entry.get("content_sha256")
        pages = entry.get("page_count")
        source_path = entry.get("source_path")
        if (
            not isinstance(sha, str) or re.fullmatch(r"[0-9a-f]{64}", sha) is None
            or type(pages) is not int or pages < 1 or sha in inventory
        ):
            raise ReviewError("REVIEW_INVENTORY_INVALID")
        if (
            not isinstance(source_path, str) or not source_path
            or Path(source_path).is_absolute() or ".." in Path(source_path).parts
            or "\x00" in source_path or "\\" in source_path
        ):
            raise ReviewError("REVIEW_SOURCE_PATH_INVALID")
        inventory[sha] = pages
        source_paths[sha] = source_path
        artifacts[sha] = entry
    if artifact_sha256 is not None and artifact_sha256 not in inventory:
        raise ReviewError("REVIEW_SHA_NOT_IN_INVENTORY")
    rights_evidence_by_sha = rights_evidence_by_sha or {}
    if any(sha not in inventory or type(value) is not bool
           for sha, value in rights_evidence_by_sha.items()):
        raise ReviewError("REVIEW_RIGHTS_SIGNAL_INVALID")
    selected = [artifact_sha256] if artifact_sha256 is not None else sorted(inventory)
    inventory_sha256 = hashlib.sha256(packet_bytes).hexdigest()
    receipt_root = pack_dir / "receipts"
    checkpoint_root = pack_dir / "checkpoints"
    summary_root = pack_dir / "reviews"
    code_sha256 = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    prompt_a_sha256 = hashlib.sha256(PROMPT_A.read_bytes()).hexdigest()
    prompt_b_sha256 = hashlib.sha256(PROMPT_B.read_bytes()).hexdigest()
    reviewed: list[str] = []
    reused: list[str] = []
    incomplete: list[str] = []
    for sha in selected:
        if source_checkpoint_dir is not None:
            rights_signal = _rights_signal_from_source(
                artifacts[sha], source_checkpoint_dir, source_receipt_dir
            )
            try:
                source_checkpoint_sha256 = hashlib.sha256(
                    (source_checkpoint_dir / f"{sha}.json").read_bytes()
                ).hexdigest()
            except OSError:
                source_checkpoint_sha256 = None
        else:
            rights_signal = rights_evidence_by_sha.get(sha, False)
            source_checkpoint_sha256 = None
        signature = hashlib.sha256(_canonical_bytes({
            "inventory_sha256": inventory_sha256,
            "content_sha256": sha,
            "page_count": inventory[sha],
            "code_sha256": code_sha256,
            "prompt_a_sha256": prompt_a_sha256,
            "prompt_b_sha256": prompt_b_sha256,
            "model_id": model_id,
            "model_version": model_version,
            "parameters": parameters,
            "vision_render_scale": vision_render_scale,
            "rights_evidence_positive": rights_signal,
            "source_checkpoint_sha256": source_checkpoint_sha256,
        })).hexdigest()
        summary_path = summary_root / f"{sha}.json"
        pdf_path = _confined_source_path(source_mirror_root, source_paths[sha])
        try:
            actual_sha, _ = _hash_file(pdf_path)
        except OSError:
            raise ReviewError("REVIEW_PDF_UNREADABLE") from None
        if actual_sha != sha:
            raise ReviewError("PDF_SHA256_MISMATCH")
        if _valid_summary(summary_path, sha, signature, receipt_root):
            reused.append(sha)
            continue
        try:
            import fitz

            with fitz.open(pdf_path) as document:
                if len(document) != inventory[sha]:
                    raise ReviewError("REVIEW_PDF_PAGE_COUNT_MISMATCH")
        except (OSError, RuntimeError, ValueError):
            raise ReviewError("REVIEW_PDF_UNREADABLE") from None
        result = review_document(
            pdf_path, sha, transport=transport, model_id=model_id,
            model_version=model_version, parameters=parameters,
            rights_evidence_positive=rights_signal, vision_enabled=True,
            checkpoint_dir=checkpoint_root, receipt_dir=receipt_root,
            vision_render_scale=vision_render_scale,
            run_nonce=0,
        )
        candidate_replays: list[dict] = []
        if (
            rights_signal
            and result["reviewer_a"]["verdict"] == "PASS"
            and result["reviewer_b"]["verdict"] == "PASS"
            and not result["restriction_signals"]
        ):
            candidate_replays.append(_candidate_replay_row(1, result))
            independent = review_document(
                pdf_path, sha, transport=transport, model_id=model_id,
                model_version=model_version, parameters=parameters,
                rights_evidence_positive=rights_signal, vision_enabled=True,
                checkpoint_dir=checkpoint_root, receipt_dir=receipt_root,
                vision_render_scale=vision_render_scale,
                run_nonce=1,
            )
            candidate_replays.append(_candidate_replay_row(2, independent))
            if any(
                candidate_replays[0][f"{label}_observation_sha256"]
                != candidate_replays[1][f"{label}_observation_sha256"]
                for label in ("reviewer_a", "reviewer_b")
            ):
                candidate_replays[1]["candidate_verdict"] = "FAIL"
        pii_status, third_party_status = _safety_statuses(result)
        summary = {
            "kind": "NEXUS-STUDENT-REVIEW-SUMMARY-V1",
            "content_sha256": sha,
            "page_count": inventory[sha],
            "inventory_sha256": inventory_sha256,
            "run_signature_sha256": signature,
            "reviewer_code_sha256": code_sha256,
            "model_id": model_id,
            "model_version": model_version,
            "source_checkpoint_sha256": source_checkpoint_sha256,
            "candidate_replays": candidate_replays,
            "pii_status": pii_status,
            "third_party_status": third_party_status,
            **result,
        }
        summary["summary_sha256"] = hashlib.sha256(_canonical_bytes(summary)).hexdigest()
        _write_private_summary(summary_path, summary)
        reviewed.append(sha)
        if any(result[label]["complete"] is not True
               for label in ("reviewer_a", "reviewer_b")):
            incomplete.append(sha)
    return {"reviewed": reviewed, "reused": reused, "incomplete": incomplete,
            "inventory_count": len(inventory)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Double revue PDF checkpointée et fail-closed")
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--source-mirror-root", "--objects", dest="source_mirror_root",
                        type=Path, required=True)
    parser.add_argument("--pack-dir", "--pack", dest="pack", type=Path, required=True)
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--artifact-sha256")
    scope.add_argument("--all", action="store_true")
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--model-version", required=True)
    parser.add_argument("--source-checkpoints-dir", type=Path, required=True)
    parser.add_argument("--source-receipts-dir", type=Path)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--num-predict", type=int, default=320)
    args = parser.parse_args()
    try:
        if re.fullmatch(r"sha256:[0-9a-f]{64}", args.model_version) is None:
            raise ReviewError("REVIEW_MODEL_PIN_INVALID")
        outcome = run_review_batch(
            args.packet, args.source_mirror_root, args.pack,
            artifact_sha256=args.artifact_sha256,
            model_id=args.model_id,
            model_version=args.model_version,
            parameters={"temperature": 0, "seed": args.seed,
                        "num_ctx": args.num_ctx, "num_predict": args.num_predict},
            vision_render_scale=VISION_RENDER_SCALE,
            source_checkpoint_dir=args.source_checkpoints_dir,
            source_receipt_dir=(args.source_receipts_dir
                                or args.source_checkpoints_dir / "receipts"),
        )
    except ReviewError as exc:
        print(json.dumps({"status": "FAIL", "reason_code": exc.reason_code}))
        return 1
    if outcome["incomplete"]:
        print(json.dumps({"status": "FAIL", "reason_code": "REVIEW_INCOMPLETE",
                          **outcome}, sort_keys=True))
        return 1
    print(json.dumps({"status": "COMPLETE", **outcome}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
