"""L'extracteur de production traite le PDF, sans adaptateur de test.

Le corpus institutionnel est fait de PDF. Un extracteur qui les refusait
rendait le worker incapable d'ingérer ce qu'il existe pour ingérer.
"""
from __future__ import annotations

import io

import pytest
from pypdf import PdfWriter

from ingestor.ingestion_agents.extractor import (
    MAX_PDF_PAGES,
    PAGE_SEPARATOR,
    PDF_MIME_TYPE,
    SUPPORTED_MIME_TYPES,
    PdfExtractionError,
    extract_pdf_pages,
)


def blank_pdf(pages: int = 1) -> bytes:
    """Un PDF valide dont les pages n'ont aucun texte natif."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class TestPdfIsAFirstClassMimeType:
    def test_pdf_is_supported_by_the_production_extractor(self) -> None:
        assert PDF_MIME_TYPE in SUPPORTED_MIME_TYPES


class TestFailClosedOnUnreadablePages:
    def test_a_page_without_native_text_is_refused_not_skipped(self) -> None:
        """Sauter la page produirait un document amputé qui *paraît*
        complet : les chunks existent, la citation renvoie un numéro de
        page, et rien n'indique que ce contenu n'a jamais été indexé."""
        with pytest.raises(PdfExtractionError, match="yielded no text"):
            extract_pdf_pages(blank_pdf())

    def test_the_refusal_names_the_page(self) -> None:
        with pytest.raises(PdfExtractionError, match=r"page 1/3"):
            extract_pdf_pages(blank_pdf(3))

    def test_the_refusal_says_ocr_is_not_attempted(self) -> None:
        with pytest.raises(PdfExtractionError, match="OCR"):
            extract_pdf_pages(blank_pdf())

    def test_bytes_that_are_not_a_pdf_are_refused(self) -> None:
        with pytest.raises(PdfExtractionError, match="does not parse as a PDF"):
            extract_pdf_pages(b"%PDF-1.4 truncated garbage")

    def test_an_empty_payload_is_refused(self) -> None:
        with pytest.raises(PdfExtractionError):
            extract_pdf_pages(b"")


class TestBounds:
    def test_the_page_bound_is_declared(self) -> None:
        assert MAX_PDF_PAGES == 2_000

    def test_the_page_separator_is_stable(self) -> None:
        """Les chunks en dérivent leur numéro de page, donc la citation."""
        assert PAGE_SEPARATOR == "\n\n"


class TestNoSpecialCaseForAnyContent:
    def test_the_extractor_holds_no_hardcoded_content_sha(self) -> None:
        """Une preuve qui ne vaudrait que pour un document choisi ne
        prouve rien sur le pipeline."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[1]
            / "src/ingestor/ingestion_agents/extractor.py"
        ).read_text()
        assert "371d0c82" not in source
        import re

        assert re.search(r"[0-9a-f]{64}", source) is None
