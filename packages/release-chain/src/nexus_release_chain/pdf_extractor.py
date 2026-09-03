"""Extraction déterministe de pages PDF basée sur pypdf et nexus_pdf_page_policy."""

from __future__ import annotations

import io
import re
from typing import Final

from nexus_pdf_page_policy import (
    PAGE_INSPECTION_ECHOUEE,
    SENS_DES_MOTIFS,
    PageInspectionError,
    motif_de_refus_page,
)

PDF_MIME_TYPE: Final[str] = "application/pdf"
MAX_PDF_PAGES: Final[int] = 2_000
_WHITESPACE_PATTERN = re.compile(r"\s+")


class PdfExtractionError(ValueError):
    """Le PDF n'a pas rendu de texte exploitable — refus explicite."""


def extract_pdf_pages(raw_bytes: bytes) -> list[str]:
    """Rend le texte de chaque page, dans l'ordre, ou refuse."""
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except (PdfReadError, ValueError, OSError) as exc:
        raise PdfExtractionError(
            f"the artifact does not parse as a PDF: {type(exc).__name__}"
        ) from exc

    if reader.is_encrypted:
        raise PdfExtractionError(
            "the PDF is encrypted; its bytes cannot be read reproducibly without "
            "a secret this pipeline must never hold"
        )

    page_count = len(reader.pages)
    if page_count == 0:
        raise PdfExtractionError("the PDF declares no page")
    if page_count > MAX_PDF_PAGES:
        raise PdfExtractionError(
            f"the PDF declares {page_count} pages, above the {MAX_PDF_PAGES} bound"
        )

    pages: list[str] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            raw = page.extract_text() or ""
        except (PdfReadError, ValueError, KeyError, TypeError) as exc:
            raise PdfExtractionError(
                f"page {number}/{page_count} could not be extracted: "
                f"{type(exc).__name__}"
            ) from exc

        text = _WHITESPACE_PATTERN.sub(" ", raw).strip()
        if not text:
            try:
                motif = motif_de_refus_page(page, reader)
            except PageInspectionError as exc:
                raise PdfExtractionError(
                    f"page {number}/{page_count} sans texte extractible et non "
                    f"inspectable — {PAGE_INSPECTION_ECHOUEE} ({exc}). Une panne "
                    "d'instrument n'est pas un verdict : le document est refusé."
                ) from exc
            if motif is not None:
                raise PdfExtractionError(
                    f"page {number}/{page_count} sans texte extractible et "
                    f"susceptible d'en porter — {motif} : {SENS_DES_MOTIFS[motif]}. "
                    "Le document est refusé plutôt qu'indexé comme complet alors "
                    "qu'une page n'a jamais été lue ; l'OCR reste hors de ce périmètre."
                )
            pages.append("")
            continue

        pages.append(text)

    return pages


__all__ = [
    "MAX_PDF_PAGES",
    "PDF_MIME_TYPE",
    "PdfExtractionError",
    "extract_pdf_pages",
]
