"""Preuve structurelle du scan de PDF pour l'adjudication étudiante déléguée.

Les extraits textuels, métadonnées et sorties OCR ne quittent jamais ce module.
Un scan mécanique complet ne vaut pas une décision de droits ni d'aptitude élève.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path

MAX_RENDER_PIXELS = 4_000_000
RENDER_MAX_SCALE = 1.5
ANNEX_MARKER = re.compile(r"\bannexes?\b", re.IGNORECASE)


class PdfScanError(RuntimeError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


def _hash_file(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return digest.hexdigest(), size


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _ocr_text(png: bytes) -> str:
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "-l", "fra+eng", "--psm", "3"],
            input=png,
            capture_output=True,
            check=False,
            timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise PdfScanError("PDF_OCR_UNAVAILABLE") from None
    if result.returncode:
        raise PdfScanError("PDF_OCR_FAILED")
    return result.stdout.decode("utf-8", errors="replace")


def _render_png(page: object, fitz_module: object) -> tuple[bytes, float]:
    width = float(page.rect.width)
    height = float(page.rect.height)
    if width <= 0 or height <= 0 or not math.isfinite(width * height):
        raise PdfScanError("PDF_PAGE_GEOMETRY_INVALID")
    scale = min(RENDER_MAX_SCALE, math.sqrt(MAX_RENDER_PIXELS / (width * height)))
    if scale <= 0:
        raise PdfScanError("PDF_PAGE_GEOMETRY_INVALID")
    pixmap = page.get_pixmap(matrix=fitz_module.Matrix(scale, scale), alpha=False)
    if pixmap.width * pixmap.height > MAX_RENDER_PIXELS + 10_000:
        raise PdfScanError("PDF_RENDER_SIZE_EXCEEDED")
    return pixmap.tobytes("png"), scale


def scan_pdf(path: Path, expected_sha256: str, expected_page_count: int) -> dict:
    """Vérifie l'identité et inspecte chaque page sans sérialiser de PII brute.

    Les pièces jointes PDF sont refusées : elles ne seraient pas couvertes par
    le nombre de pages attendu. L'appelant traduit tout ``PdfScanError`` en
    exclusion fail-closed, jamais en approbation implicite.
    ``annex_page=False`` signifie seulement qu'aucun marqueur lexical n'a été
    détecté dans le texte/OCR ; cela ne prouve jamais l'absence d'annexe.
    """
    try:
        digest, file_size = _hash_file(path)
    except OSError:
        raise PdfScanError("PDF_UNREADABLE") from None
    if digest != expected_sha256:
        raise PdfScanError("PDF_SHA256_MISMATCH")

    try:
        import fitz

        document = fitz.open(path)
    except (ImportError, RuntimeError, ValueError):
        raise PdfScanError("PDF_OPEN_FAILED") from None

    try:
        if document.is_encrypted:
            raise PdfScanError("PDF_ENCRYPTED")
        page_count = len(document)
        if page_count != expected_page_count:
            raise PdfScanError("PDF_PAGE_COUNT_MISMATCH")
        attachment_count = document.embfile_count()
        if attachment_count:
            raise PdfScanError("PDF_EMBEDDED_FILES_UNSUPPORTED")

        metadata_digest = _sha256_bytes(
            json.dumps(document.metadata, sort_keys=True, ensure_ascii=False).encode("utf-8")
        )
        page_proofs: list[dict] = []
        for page_index in range(page_count):
            page = document.load_page(page_index)
            text = page.get_text("text", sort=True)
            raster_count = len(page.get_image_info())
            drawing_count = len(page.get_drawings())
            if page.first_widget is not None:
                raise PdfScanError("PDF_FORM_WIDGET_UNSUPPORTED")
            annotation_digest = hashlib.sha256()
            annotation_count = 0
            for annotation in page.annots() or ():
                if annotation.type[1] == "FileAttachment":
                    raise PdfScanError("PDF_ATTACHMENT_ANNOTATION_UNSUPPORTED")
                annotation_count += 1
                annotation_digest.update(
                    json.dumps(
                        {"type": annotation.type, "info": annotation.info},
                        sort_keys=True,
                        ensure_ascii=False,
                    ).encode("utf-8")
                )
            links = page.get_links()
            links_sha256 = _sha256_bytes(
                json.dumps(links, sort_keys=True, default=str).encode("utf-8")
            )
            graphic = raster_count > 0 or drawing_count > 0 or annotation_count > 0
            render_sha256 = None
            render_scale = None
            # Un schéma ou une image peut porter une notice malgré le texte
            # extractible alentour : OCR sur toutes les pages graphiques.
            ocr_required = graphic
            ocr_complete = not ocr_required
            ocr_sha256 = None
            ocr_text = ""
            if graphic:
                png, render_scale = _render_png(page, fitz)
                render_sha256 = _sha256_bytes(png)
                if ocr_required:
                    ocr_text = _ocr_text(png)
                    ocr_sha256 = _sha256_bytes(ocr_text.encode("utf-8"))
                    ocr_complete = True
            page_proofs.append(
                {
                    "page_number": page_index + 1,
                    "text_sha256": _sha256_bytes(text.encode("utf-8")),
                    "text_character_count": len(text),
                    "annex_page": bool(ANNEX_MARKER.search(text + "\n" + ocr_text)),
                    "raster_image_count": raster_count,
                    "vector_drawing_count": drawing_count,
                    "annotation_count": annotation_count,
                    "annotations_sha256": annotation_digest.hexdigest(),
                    "link_count": len(links),
                    "links_sha256": links_sha256,
                    "render_sha256": render_sha256,
                    "render_scale": render_scale,
                    "ocr_required": ocr_required,
                    "ocr_complete": ocr_complete,
                    "ocr_sha256": ocr_sha256,
                }
            )
    except PdfScanError:
        raise
    except (RuntimeError, ValueError, OSError):
        raise PdfScanError("PDF_PAGE_SCAN_FAILED") from None
    finally:
        document.close()

    try:
        digest_after, size_after = _hash_file(path)
    except OSError:
        raise PdfScanError("PDF_UNREADABLE") from None
    if digest_after != digest or size_after != file_size:
        raise PdfScanError("PDF_CHANGED_DURING_SCAN")

    return {
        "scanner_kind": "NEXUS-STUDENT-RIGHTS-PDF-SCAN-V1",
        "renderer_version": fitz.VersionBind,
        "content_sha256": digest,
        "exact_bytes_match": True,
        "file_size_bytes": file_size,
        "page_count": page_count,
        "expected_page_count": expected_page_count,
        "full_document_scan_complete": True,
        "annexes_scan_complete": True,
        "images_and_annexes_checked": True,
        "embedded_file_count": attachment_count,
        "metadata_sha256": metadata_digest,
        "pages": page_proofs,
    }
