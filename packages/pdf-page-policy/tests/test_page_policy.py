"""Épreuves du foyer unique : le critère réussit ET échoue sur des PDF réellement
construits, jamais sur des octets simulés — un octet simulé ne peut pas porter
un /Form XObject.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import nexus_pdf_page_policy as politique
from nexus_pdf_page_policy import (
    MOTIFS_DE_REFUS,
    PAGE_REFUS_IMAGE,
    PAGE_REFUS_TEXTE,
    PAGE_REFUS_TRACE,
    POLICY_ID,
    PageInspectionError,
    classer_pages_sans_texte,
    motif_de_refus_page,
    policy_source_sha256,
)

# Une image 1×1 en niveaux de gris, non compressée : deux octets de données.
_IMAGE_1x1 = (
    b"<</Type/XObject/Subtype/Image/Width 1/Height 1/ColorSpace/DeviceGray"
    b"/BitsPerComponent 8/Length 1>>\nstream\n\x00\nendstream"
)


def _pdf(flux_des_pages: list[bytes], *, formulaire: bytes | None = None) -> bytes:
    """Assemble un PDF minimal mais valide, une page par flux de contenu.

    `formulaire` : flux d'un /Form XObject déclaré `/Fm1` dans les ressources de
    chaque page, avec accès à l'image `/Im1`. C'est la forme exacte du cas réel
    `8848f073…` (page 2 : un /Form de 0 octet).
    """
    objets: list[bytes] = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"",  # 2 : /Pages, rempli plus bas
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
        _IMAGE_1x1,
        (
            b"<</Type/XObject/Subtype/Form/BBox[0 0 10 10]"
            b"/Resources<</XObject<</Im1 4 0 R>>/Font<</F1 3 0 R>>>>"
            b"/Length " + str(len(formulaire or b"")).encode() + b">>\nstream\n"
            + (formulaire or b"") + b"\nendstream"
        ),
    ]
    premier_objet_page = len(objets) + 1
    numeros_pages = []
    for decalage, flux in enumerate(flux_des_pages):
        numero_page = premier_objet_page + 2 * decalage
        numero_flux = numero_page + 1
        numeros_pages.append(numero_page)
        objets.append(
            b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 595 842]"
            b"/Resources<</Font<</F1 3 0 R>>/XObject<</Im1 4 0 R/Fm1 5 0 R>>>>"
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


_TEXTE = b"BT /F1 12 Tf 72 720 Td (Contenu pedagogique inspecte) Tj ET"
_IMAGE = b"q 595 0 0 842 0 0 cm /Im1 Do Q"
_IMAGE_EN_LIGNE = b"q 10 0 0 10 0 0 cm BI /W 1 /H 1 /CS /G /BPC 8 ID \x00 EI Q"
_TEXTE_SANS_GLYPHE = b"BT /F1 12 Tf 72 720 Td () Tj ET"
_COURBE = b"100 100 m 150 200 200 200 250 100 c f"
_SEGMENT = b"100 100 m 200 200 l S"
_RECTANGLE_SEUL = b"0 0 1 rg 0 0 595 842 re f"


class TestVerdictCanonique:
    """Le critère à quatre conditions, page par page."""

    def test_une_page_vide_est_ignorable(self) -> None:
        assert classer_pages_sans_texte(_pdf([_TEXTE, b""]), [2]) == {}

    def test_un_rectangle_seul_n_est_pas_une_lettre(self) -> None:
        """Quatrième de couverture : un aplat de couleur, aucun glyphe possible."""
        assert classer_pages_sans_texte(_pdf([_TEXTE, _RECTANGLE_SEUL]), [2]) == {}

    def test_une_page_image_est_refusee(self) -> None:
        assert classer_pages_sans_texte(_pdf([_TEXTE, _IMAGE]), [2]) == {2: PAGE_REFUS_IMAGE}

    def test_une_image_en_ligne_est_une_image(self) -> None:
        assert classer_pages_sans_texte(_pdf([_IMAGE_EN_LIGNE]), [1]) == {1: PAGE_REFUS_IMAGE}

    def test_des_operateurs_de_texte_sans_texte_sont_refuses(self) -> None:
        assert classer_pages_sans_texte(_pdf([_TEXTE_SANS_GLYPHE]), [1]) == {
            1: PAGE_REFUS_TEXTE
        }

    def test_une_courbe_est_un_trace_pouvant_porter_un_glyphe(self) -> None:
        assert classer_pages_sans_texte(_pdf([_COURBE]), [1]) == {1: PAGE_REFUS_TRACE}

    def test_un_segment_libre_est_un_trace_pouvant_porter_un_glyphe(self) -> None:
        assert classer_pages_sans_texte(_pdf([_SEGMENT]), [1]) == {1: PAGE_REFUS_TRACE}

    def test_l_image_prime_sur_le_texte_qui_prime_sur_le_trace(self) -> None:
        assert classer_pages_sans_texte(
            _pdf([_IMAGE + b" " + _TEXTE_SANS_GLYPHE + b" " + _COURBE]), [1]
        ) == {1: PAGE_REFUS_IMAGE}
        assert classer_pages_sans_texte(
            _pdf([_TEXTE_SANS_GLYPHE + b" " + _COURBE]), [1]
        ) == {1: PAGE_REFUS_TEXTE}

    def test_seules_les_pages_demandees_sont_classees(self) -> None:
        """Le prédicat qualifie l'absence de texte ; il ne re-décide pas l'extraction."""
        refus = classer_pages_sans_texte(_pdf([_IMAGE, _TEXTE, b"", _COURBE]), [1, 3, 4])
        assert refus == {1: PAGE_REFUS_IMAGE, 4: PAGE_REFUS_TRACE}

    def test_une_image_declaree_mais_jamais_peinte_ne_compte_pas(self) -> None:
        """Le flux fait foi, pas l'inventaire des ressources : `/Im1` est déclaré
        sur chaque page du générateur, seule la page qui l'invoque est refusée."""
        assert classer_pages_sans_texte(_pdf([b"", _IMAGE]), [1, 2]) == {2: PAGE_REFUS_IMAGE}


class TestFormXObjects:
    """Le critère descend dans les /Form effectivement invoqués — le cas réel
    de `8848f073…`, dont la page 2 invoque un /Form de 0 octet."""

    def test_un_form_vide_est_ignorable(self) -> None:
        assert classer_pages_sans_texte(_pdf([b"q /Fm1 Do Q"], formulaire=b""), [1]) == {}

    def test_un_form_qui_peint_une_image_est_une_page_image(self) -> None:
        assert classer_pages_sans_texte(
            _pdf([b"q /Fm1 Do Q"], formulaire=_IMAGE), [1]
        ) == {1: PAGE_REFUS_IMAGE}

    def test_un_form_qui_porte_des_operateurs_de_texte_est_refuse(self) -> None:
        assert classer_pages_sans_texte(
            _pdf([b"q /Fm1 Do Q"], formulaire=_TEXTE_SANS_GLYPHE), [1]
        ) == {1: PAGE_REFUS_TEXTE}

    def test_un_form_declare_mais_non_invoque_ne_compte_pas(self) -> None:
        assert classer_pages_sans_texte(_pdf([b""], formulaire=_IMAGE), [1]) == {}


class TestPanneDInstrument:
    """Une panne n'est jamais un verdict (R32)."""

    def test_un_xobject_introuvable_refuse_au_lieu_de_conclure(self) -> None:
        with pytest.raises(PageInspectionError, match="Im9"):
            classer_pages_sans_texte(_pdf([b"q /Im9 Do Q"]), [1])

    def test_un_document_illisible_refuse(self) -> None:
        with pytest.raises(PageInspectionError, match="lecture impossible"):
            classer_pages_sans_texte(b"%PDF-1.4 ceci n'est pas un document", [1])

    def test_une_page_hors_bornes_refuse(self) -> None:
        with pytest.raises(PageInspectionError, match="page 7"):
            classer_pages_sans_texte(_pdf([_TEXTE]), [7])

    def test_motif_de_refus_page_leve_sur_panne(self) -> None:
        from io import BytesIO

        from pypdf import PdfReader

        reader = PdfReader(BytesIO(_pdf([b"q /Im9 Do Q"])))
        with pytest.raises(PageInspectionError):
            motif_de_refus_page(reader.pages[0], reader)


class TestProvenance:
    def test_les_motifs_sont_fermes_et_versionnes(self) -> None:
        assert MOTIFS_DE_REFUS == (PAGE_REFUS_IMAGE, PAGE_REFUS_TEXTE, PAGE_REFUS_TRACE)
        assert POLICY_ID == "NEXUS-PDF-PAGE-POLICY-V1"
        assert set(politique.SENS_DES_MOTIFS) == set(MOTIFS_DE_REFUS)

    def test_l_empreinte_designe_exactement_ce_module(self) -> None:
        digest = policy_source_sha256()
        assert len(digest) == 64
        assert digest == hashlib.sha256(Path(politique.__file__).read_bytes()).hexdigest()


class TestRuntimeCanonique:
    def test_le_runtime_canonique_est_une_seule_autorite(self) -> None:
        assert politique.CANONICAL_PYPDF_VERSION == "6.14.2"

    def test_le_bon_runtime_est_accepte(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pypdf

        monkeypatch.setattr(pypdf, "__version__", politique.CANONICAL_PYPDF_VERSION)
        assert politique.require_canonical_pypdf() == politique.CANONICAL_PYPDF_VERSION

    def test_un_autre_runtime_est_refuse(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import pypdf

        monkeypatch.setattr(pypdf, "__version__", "4.2.0")
        with pytest.raises(politique.CanonicalRuntimeError, match="4.2.0"):
            politique.require_canonical_pypdf()
