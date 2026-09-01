"""Critère de traitement d'une page sans texte extractible.

Le critère est fixé dans docs/reports/lot_1_2_critere_page_sans_texte.md, avant
toute mesure de distribution, et n'emploie aucun seuil. Ces épreuves le voient
réussir ET échouer sur des PDF réellement construits, jamais sur des octets
simulés : un octet simulé ne peut pas porter un /Form XObject.
"""

from __future__ import annotations

import pytest

from rag_pedago.imports import pii_scanner
from rag_pedago.imports.pii_scanner import (
    PAGE_INSPECTION_ECHOUEE,
    PAGE_REFUS_IMAGE,
    PAGE_REFUS_TEXTE,
    PAGE_REFUS_TRACE,
    scan_pdf_bytes,
)

# Une image 1×1 en niveaux de gris, non compressée : deux octets de données.
_IMAGE_1x1 = (
    b"<</Type/XObject/Subtype/Image/Width 1/Height 1/ColorSpace/DeviceGray"
    b"/BitsPerComponent 8/Length 1>>\nstream\n\x00\nendstream"
)


def _pdf(flux_des_pages: list[bytes]) -> bytes:
    """Assemble un PDF minimal mais valide, une page par flux de contenu."""
    objets: list[bytes] = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"",  # 2 : /Pages, rempli plus bas
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        _IMAGE_1x1,
    ]
    premier_objet_page = len(objets) + 1
    numeros_pages = []
    for decalage, flux in enumerate(flux_des_pages):
        numero_page = premier_objet_page + 2 * decalage
        numero_flux = numero_page + 1
        numeros_pages.append(numero_page)
        objets.append(
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
            b"/Resources<</Font<</F1 3 0 R>>/XObject<</Im1 4 0 R>>>>"
            b"/Contents " + str(numero_flux).encode() + b" 0 R>>"
        )
        objets.append(
            b"<</Length " + str(len(flux)).encode() + b">>\nstream\n" + flux
            + b"\nendstream"
        )
    kids = b"[" + b" ".join(f"{n} 0 R".encode() for n in numeros_pages) + b"]"
    objets[1] = (
        b"<</Type/Pages/Kids" + kids + b"/Count "
        + str(len(numeros_pages)).encode() + b">>"
    )

    sortie = bytearray(b"%PDF-1.4\n")
    positions = []
    for index, corps in enumerate(objets, start=1):
        positions.append(len(sortie))
        sortie += str(index).encode() + b" 0 obj\n" + corps + b"\nendobj\n"
    depart_xref = len(sortie)
    sortie += b"xref\n0 " + str(len(objets) + 1).encode() + b"\n"
    sortie += b"0000000000 65535 f \n"
    for position in positions:
        sortie += f"{position:010d} 00000 n \n".encode()
    sortie += (
        b"trailer\n<</Size " + str(len(objets) + 1).encode() + b"/Root 1 0 R>>\n"
        b"startxref\n" + str(depart_xref).encode() + b"\n%%EOF\n"
    )
    return bytes(sortie)


_PAGE_AVEC_TEXTE = b"BT /F1 12 Tf 72 720 Td (Contenu pedagogique inspecte) Tj ET"


def _scan(flux_des_pages: list[bytes]):
    return scan_pdf_bytes(_pdf(flux_des_pages), source_path="epreuve.pdf")


class TestPageSansTexte:
    def test_le_pdf_de_reference_est_lisible(self) -> None:
        """Sans ce garde-fou, une épreuve pourrait passer sur un PDF cassé."""
        resultat = _scan([_PAGE_AVEC_TEXTE])
        assert resultat.extraction_error is None
        assert resultat.pages_scanned == 1
        assert "Contenu pedagogique" in _PAGE_AVEC_TEXTE.decode()

    def test_page_vraiment_blanche_est_ignoree(self) -> None:
        """Flux vide : ni texte, ni image, ni tracé. Elle ne peut porter aucun glyphe."""
        resultat = _scan([_PAGE_AVEC_TEXTE, b""])
        assert resultat.extraction_error is None
        assert resultat.pages_scanned == 1
        assert resultat.characters_scanned > 0

    def test_page_de_couleur_pleine_est_ignoree(self) -> None:
        """Un rectangle n'est pas une lettre : `re f` seul reste ignorable."""
        resultat = _scan([_PAGE_AVEC_TEXTE, b"0.275 0.373 0.616 rg 0 48 549 682 re f"])
        assert resultat.extraction_error is None
        assert resultat.pages_scanned == 1

    def test_page_image_est_refusee(self) -> None:
        """Une page-image peut porter du texte photographié : refus, candidat OCR."""
        resultat = _scan([_PAGE_AVEC_TEXTE, b"q 595 0 0 842 0 0 cm /Im1 Do Q"])
        assert resultat.extraction_error is not None
        assert resultat.extraction_error.startswith(PAGE_REFUS_IMAGE)
        assert "pages 2" in resultat.extraction_error
        assert resultat.pages_scanned == 0

    def test_page_a_tracé_courbe_est_refusee(self) -> None:
        """Un glyphe vectorisé en courbes est du texte que le balayage ne lit pas."""
        resultat = _scan([_PAGE_AVEC_TEXTE, b"100 100 m 150 200 200 200 250 100 c f"])
        assert resultat.extraction_error is not None
        assert resultat.extraction_error.startswith(PAGE_REFUS_TRACE)
        assert resultat.pages_scanned == 0

    def test_page_a_operateur_de_texte_illisible_est_refusee(self) -> None:
        """Opérateur de texte présent, aucun texte extractible : le scanner ne lit pas."""
        resultat = _scan([_PAGE_AVEC_TEXTE, b"BT /F1 12 Tf 72 720 Td () Tj ET"])
        assert resultat.extraction_error is not None
        assert resultat.extraction_error.startswith(PAGE_REFUS_TEXTE)
        assert resultat.pages_scanned == 0

    def test_toutes_les_pages_sans_texte_reste_un_refus_global(self) -> None:
        resultat = _scan([b"", b""])
        assert resultat.extraction_error == "PDF_TEXT_EXTRACTION_EMPTY"

    def test_panne_d_instrument_refuse_et_ne_conclut_pas(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R32 : une panne d'instrument n'est jamais convertie en « aucune image »."""
        monkeypatch.setattr(pii_scanner, "ContentStream", None)
        resultat = _scan([_PAGE_AVEC_TEXTE, b""])
        assert resultat.extraction_error is not None
        assert resultat.extraction_error.startswith(PAGE_INSPECTION_ECHOUEE)
        assert resultat.pages_scanned == 0
        assert resultat.pii_detected is False

    def test_panne_pendant_la_traversee_refuse_aussi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def tombe_en_panne(*_args, **_kwargs):
            raise RuntimeError("moteur indisponible")

        monkeypatch.setattr(pii_scanner, "ContentStream", tombe_en_panne)
        resultat = _scan([_PAGE_AVEC_TEXTE, b""])
        assert resultat.extraction_error is not None
        assert resultat.extraction_error.startswith(PAGE_INSPECTION_ECHOUEE)
        assert "moteur indisponible" in resultat.extraction_error
