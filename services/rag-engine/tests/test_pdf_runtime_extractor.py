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


_IMAGE_1x1 = (
    b"<</Type/XObject/Subtype/Image/Width 1/Height 1/ColorSpace/DeviceGray"
    b"/BitsPerComponent 8/Length 1>>\nstream\n\x00\nendstream"
)

_PAGE_AVEC_TEXTE = b"BT /F1 12 Tf 72 720 Td (Contenu pedagogique inspecte) Tj ET"
_PAGE_AVEC_TEXTE_3 = b"BT /F1 12 Tf 72 720 Td (la troisieme page) Tj ET"


def _pdf(flux_des_pages: list[bytes]) -> bytes:
    """Un PDF minimal mais valide, un flux de contenu par page.

    `PdfWriter` ne sait pas composer une page-image ni un tracé vectoriel :
    ces épreuves assemblent donc les objets à la main. Un octet simulé ne peut
    pas porter un /Form XObject.
    """
    objets: list[bytes] = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"",
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        _IMAGE_1x1,
    ]
    premier = len(objets) + 1
    numeros = []
    for decalage, flux in enumerate(flux_des_pages):
        numero_page = premier + 2 * decalage
        numeros.append(numero_page)
        objets.append(
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
            b"/Resources<</Font<</F1 3 0 R>>/XObject<</Im1 4 0 R>>>>"
            b"/Contents " + str(numero_page + 1).encode() + b" 0 R>>"
        )
        objets.append(
            b"<</Length " + str(len(flux)).encode() + b">>\nstream\n" + flux
            + b"\nendstream"
        )
    objets[1] = (
        b"<</Type/Pages/Kids[" + b" ".join(f"{n} 0 R".encode() for n in numeros)
        + b"]/Count " + str(len(numeros)).encode() + b">>"
    )
    sortie = bytearray(b"%PDF-1.4\n")
    positions = []
    for index, corps in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += str(index).encode() + b" 0 obj\n" + corps + b"\nendobj\n"
    depart = len(sortie)
    sortie += b"xref\n0 " + str(len(objets) + 1).encode() + b"\n"
    sortie += b"0000000000 65535 f \n"
    for position in positions:
        sortie += f"{position:010d} 00000 n \n".encode()
    sortie += (
        b"trailer\n<</Size " + str(len(objets) + 1).encode() + b"/Root 1 0 R>>\n"
        b"startxref\n" + str(depart).encode() + b"\n%%EOF\n"
    )
    return bytes(sortie)


class TestPdfIsAFirstClassMimeType:
    def test_pdf_is_supported_by_the_production_extractor(self) -> None:
        assert PDF_MIME_TYPE in SUPPORTED_MIME_TYPES


class TestFailClosedOnUnreadablePages:
    """Ré-spécifié le 2026-08-31 (LOT 1.2).

    Ces épreuves exigeaient le refus du document dès la PREMIÈRE page sans
    texte. Le critère était trop grossier : mesuré sur les 2 451 PDF du corpus,
    il refusait 42 documents, dont 16 dont les seules pages sans texte sont
    RÉELLEMENT vides — verso de couverture, quatrième de couverture. 1 720 120
    caractères, 2,56 % du corpus, perdus pour une page de séparation.

    Ce qu'elles vérifient désormais : le refus est conservé partout où il
    protège — page-image, texte non décodable, tracé vectoriel — et levé là où
    il ne protégeait rien. Critère à quatre conditions, sans seuil :
    docs/reports/lot_1_2_critere_page_sans_texte.md
    """

    def test_a_document_without_any_text_is_refused(self) -> None:
        """Sauter la page produirait un document amputé qui *paraît*
        complet : les chunks existent, la citation renvoie un numéro de
        page, et rien n'indique que ce contenu n'a jamais été indexé."""
        with pytest.raises(PdfExtractionError, match="yielded no text"):
            extract_pdf_pages(blank_pdf())

    def test_the_refusal_names_the_page_count(self) -> None:
        with pytest.raises(PdfExtractionError, match=r"3 pages"):
            extract_pdf_pages(blank_pdf(3))

    def test_the_refusal_says_ocr_is_not_attempted(self) -> None:
        with pytest.raises(PdfExtractionError, match="OCR"):
            extract_pdf_pages(blank_pdf())

    def test_a_page_image_is_refused_and_named(self) -> None:
        """Une page-image porte du texte photographié : refus, candidat OCR."""
        with pytest.raises(PdfExtractionError, match=r"page 2/2.*page-image"):
            extract_pdf_pages(
                _pdf([_PAGE_AVEC_TEXTE, b"q 595 0 0 842 0 0 cm /Im1 Do Q"])
            )

    def test_a_vector_traced_page_is_refused(self) -> None:
        """Un glyphe vectorisé en courbes est du texte que rien ne lira."""
        with pytest.raises(PdfExtractionError, match="tracé vectoriel"):
            extract_pdf_pages(
                _pdf([_PAGE_AVEC_TEXTE, b"100 100 m 150 200 200 200 250 100 c f"])
            )

    def test_a_page_with_text_operators_but_no_text_is_refused(self) -> None:
        """Opérateur de texte présent, rien d'extractible : encodage illisible."""
        with pytest.raises(PdfExtractionError, match="non décodable"):
            extract_pdf_pages(
                _pdf([_PAGE_AVEC_TEXTE, b"BT /F1 12 Tf 72 720 Td () Tj ET"])
            )

    def test_a_truly_blank_separator_page_is_ignored(self) -> None:
        """Elle ne peut porter aucun glyphe : le document passe."""
        pages = extract_pdf_pages(_pdf([_PAGE_AVEC_TEXTE, b""]))

        assert len(pages) == 2
        assert pages[0]
        assert pages[1] == ""

    def test_a_solid_colour_back_cover_is_ignored(self) -> None:
        """Un rectangle n'est pas une lettre."""
        pages = extract_pdf_pages(
            _pdf([_PAGE_AVEC_TEXTE, b"0.275 0.373 0.616 rg 0 48 549 682 re f"])
        )

        assert [bool(page) for page in pages] == [True, False]

    def test_the_page_numbering_is_never_shifted_by_an_ignored_page(self) -> None:
        """Retirer l'entrée décalerait toutes les citations suivantes d'une page.

        `chunk_publication` déduit le numéro de page par `enumerate` sur cette
        liste : une page ignorée doit y rester, vide.
        """
        pages = extract_pdf_pages(
            _pdf([_PAGE_AVEC_TEXTE, b"", _PAGE_AVEC_TEXTE_3])
        )

        assert len(pages) == 3
        assert pages[1] == ""
        assert "troisieme" in pages[2]

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
