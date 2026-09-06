"""Ce que la politique d'extraction V2 refuse de taire.

V1 décidait au niveau du DOCUMENT : elle n'océrisait que si aucune page ne
rendait de texte. Un document qui portait une couche textuelle ET une
page-image voyait cette page comptée vide — le scanner PII y lisait du vide,
le découpage l'omettait, et rien ne le disait. Mesuré sur le corpus gouverné :
25 documents, 61 pages perdues.

Chaque épreuve ici tue une mutation précise. Revenir à la décision par
document, océriser une page déjà lisible, ou rendre une page océrisée vide
comme si elle était blanche font échouer l'une d'elles.
"""

from __future__ import annotations

import hashlib

import pytest

from rag_pedago.governance.drive_extraction import (
    PATH_NATIVE_TEXT,
    PATH_NOT_ASSESSABLE,
    PATH_OCR_FALLBACK,
    PATH_STRUCTURAL_EMPTY,
    PdfExtractionError,
    TextLayerAbsente,
    extraire_document,
)

#: Un flux qui affiche du texte extractible.
FLUX_TEXTE = "BT /F1 24 Tf 72 500 Td (PAGE LISIBLE) Tj ET"
#: Un tracé libre : la politique le refuse — il peut porter un glyphe.
FLUX_TRACE = "72 500 m 300 500 l S"
#: Un rectangle seul : structurellement incapable de porter une lettre.
FLUX_RECTANGLE = "72 500 200 100 re S"


def _pdf(flux: list[str]) -> bytes:
    """Un PDF réel dont chaque page porte le flux de contenu demandé."""
    objets: list[bytes] = []

    def ajouter(corps: bytes) -> int:
        objets.append(corps)
        return len(objets)

    pages_id = len(flux) * 2 + 1
    kids: list[int] = []
    for contenu in flux:
        brut = contenu.encode("ascii")
        flux_id = ajouter(
            b"<< /Length " + str(len(brut)).encode() + b" >>\nstream\n" + brut + b"\nendstream"
        )
        kids.append(
            ajouter(
                b"<< /Type /Page /Parent " + str(pages_id).encode() + b" 0 R "
                b"/MediaBox [0 0 612 792] /Resources << /Font << /F1 "
                + str(pages_id + 1).encode() + b" 0 R >> >> /Contents "
                + str(flux_id).encode() + b" 0 R >>"
            )
        )
    ajouter(
        b"<< /Type /Pages /Count " + str(len(kids)).encode() + b" /Kids ["
        + b" ".join(str(k).encode() + b" 0 R" for k in kids) + b"] >>"
    )
    ajouter(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    catalogue = ajouter(b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")

    sortie = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for numero, corps in enumerate(objets, 1):
        offsets.append(len(sortie))
        sortie += str(numero).encode() + b" 0 obj\n" + corps + b"\nendobj\n"
    debut = len(sortie)
    sortie += b"xref\n0 " + str(len(objets) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        sortie += f"{offset:010d} 00000 n \n".encode()
    sortie += (
        b"trailer\n<< /Size " + str(len(objets) + 1).encode() + b" /Root "
        + str(catalogue).encode() + b" 0 R >>\nstartxref\n" + str(debut).encode() + b"\n%%EOF\n"
    )
    return bytes(sortie)


class _RuntimeFictif:
    """Un runtime OCR d'épreuve : ces tests mesurent la COMPOSITION, pas
    tesseract. Dépendre du moteur réel rendrait le résultat non déterministe
    et masquerait la règle qu'on veut sceller."""

    def identity_sha256(self) -> str:
        return "f" * 64


@pytest.fixture
def ocr_espion(monkeypatch: pytest.MonkeyPatch):
    """Rend (appels, régler) — `régler` fixe le texte que l'OCR rendra."""
    import nexus_pdf_ocr

    appels: list[list[int]] = []
    rendu: dict[int, str] = {}

    def faux(content: bytes, *, runtime: object, pages=None):
        from nexus_pdf_ocr import OcrPage

        demandees = list(pages) if pages is not None else []
        appels.append(demandees)
        return tuple(OcrPage(number=n, text=rendu.get(n, "")) for n in demandees)

    monkeypatch.setattr(nexus_pdf_ocr, "ocr_pdf_pages", faux)
    return appels, rendu


# --- le défaut de V1, scellé ------------------------------------------


def test_une_page_muette_au_milieu_d_un_document_lisible_est_ocerisee(ocr_espion) -> None:
    """LE défaut de V1.

    Le document porte du texte : V1 en concluait qu'il n'avait pas besoin
    d'OCR, et la page 2 — qui affiche un tracé — était rendue vide. Toute
    régression vers la décision par document fait échouer cette épreuve.
    """
    appels, rendu = ocr_espion
    rendu[2] = "CONTENU RETROUVE"
    resultat = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_TRACE, FLUX_TEXTE]), ocr_runtime=_RuntimeFictif()
    )
    assert resultat.pages[1].text == "CONTENU RETROUVE"
    assert [p.extraction_path for p in resultat.provenance] == [
        PATH_NATIVE_TEXT,
        PATH_OCR_FALLBACK,
        PATH_NATIVE_TEXT,
    ]
    assert appels == [[2]], "seule la page non ignorable devait être océrisée"


def test_le_texte_natif_d_une_page_lisible_n_est_jamais_remplace(ocr_espion) -> None:
    """Substituer une reconnaissance approximative à une extraction exacte
    dégraderait le corpus sous couvert de le compléter."""
    _appels, rendu = ocr_espion
    rendu.update({1: "OCR PARASITE", 2: "x", 3: "OCR PARASITE"})
    resultat = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_TRACE, FLUX_TEXTE]), ocr_runtime=_RuntimeFictif()
    )
    assert "PAGE LISIBLE" in resultat.pages[0].text
    assert "PAGE LISIBLE" in resultat.pages[2].text


def test_une_page_ignorable_reste_vide_et_n_appelle_pas_l_ocr(ocr_espion) -> None:
    """Un rectangle n'est pas une lettre. Océriser une page de séparation
    ferait payer un coût pour du bruit — et créerait du texte là où le
    document n'en montre aucun."""
    appels, _rendu = ocr_espion
    resultat = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_RECTANGLE]), ocr_runtime=_RuntimeFictif()
    )
    assert resultat.pages[1].text.strip() == ""
    assert resultat.provenance[1].extraction_path == PATH_STRUCTURAL_EMPTY
    assert resultat.provenance[1].page_policy_verdict is None
    assert appels == [], "aucune océrisation n'était due"
    assert resultat.assessable


# --- l'OCR qui ne rend rien n'est pas une page vide -------------------


def test_un_ocr_sans_resultat_rend_la_page_non_evaluable(ocr_espion) -> None:
    """Le silence de l'instrument n'est pas une mesure.

    Rendre cette page vide ferait dire au scanner PII qu'il l'a lue et
    déclarée saine, alors que personne ne sait ce qu'elle porte. Le document
    est marqué non évaluable et ne peut pas être publié.
    """
    _appels, rendu = ocr_espion
    rendu[2] = "   \n  "
    resultat = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_TRACE]), ocr_runtime=_RuntimeFictif()
    )
    assert resultat.provenance[1].extraction_path == PATH_NOT_ASSESSABLE
    assert resultat.pages_non_evaluables == (2,)
    assert not resultat.assessable


def test_sans_runtime_ocr_une_page_non_ignorable_est_un_refus(ocr_espion) -> None:
    """Sans la capacité nécessaire, le refus est la seule réponse honnête."""
    with pytest.raises(TextLayerAbsente, match="tairait ce qu'elles montrent"):
        extraire_document(_pdf([FLUX_TEXTE, FLUX_TRACE]))


def test_sans_runtime_ocr_un_document_sans_page_muette_passe() -> None:
    """La capacité OCR n'est exigée que lorsqu'elle est nécessaire."""
    resultat = extraire_document(_pdf([FLUX_TEXTE, FLUX_TEXTE]))
    assert resultat.ocr_runtime_identity_sha256 is None
    assert all(p.extraction_path == PATH_NATIVE_TEXT for p in resultat.provenance)


# --- la composition ---------------------------------------------------


def test_la_composition_preserve_le_nombre_et_les_numeros_de_pages(ocr_espion) -> None:
    """Un décalage rendrait chaque citation fausse sans que rien ne le montre."""
    _appels, rendu = ocr_espion
    rendu.update({2: "deux", 4: "quatre"})
    resultat = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_TRACE, FLUX_TEXTE, FLUX_TRACE, FLUX_TEXTE]),
        ocr_runtime=_RuntimeFictif(),
    )
    assert [p.number for p in resultat.pages] == [1, 2, 3, 4, 5]
    assert [p.number for p in resultat.provenance] == [1, 2, 3, 4, 5]


def test_une_ocerisation_qui_rend_d_autres_pages_que_demandees_est_un_refus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le rapprochement se fait sur le numéro de page du DOCUMENT."""
    import nexus_pdf_ocr
    from nexus_pdf_ocr import OcrPage

    monkeypatch.setattr(
        nexus_pdf_ocr,
        "ocr_pdf_pages",
        lambda content, *, runtime, pages=None: (OcrPage(number=99, text="ailleurs"),),
    )
    with pytest.raises(PdfExtractionError, match="décalage"):
        extraire_document(_pdf([FLUX_TEXTE, FLUX_TRACE]), ocr_runtime=_RuntimeFictif())


# --- la provenance doit permettre de rejouer --------------------------


def test_chaque_page_porte_l_empreinte_du_texte_retenu(ocr_espion) -> None:
    """`canonical_page_text_sha256` est ce que le scanner PII lit et ce que le
    découpage utilise. Sans elle, prouver qu'ils ont lu le MÊME texte est
    impossible."""
    _appels, rendu = ocr_espion
    rendu[2] = "CONTENU RETROUVE"
    resultat = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_TRACE]), ocr_runtime=_RuntimeFictif()
    )
    for page, trace in zip(resultat.pages, resultat.provenance, strict=True):
        attendue = hashlib.sha256(page.text.encode("utf-8")).hexdigest()
        assert trace.canonical_page_text_sha256 == attendue


def test_la_page_ocerisee_conserve_l_empreinte_du_texte_natif(ocr_espion) -> None:
    """Le témoin qui permet de rejouer la décision : sans lui, on ne peut plus
    dire ce que l'extracteur natif avait rendu avant l'océrisation."""
    _appels, rendu = ocr_espion
    rendu[2] = "CONTENU RETROUVE"
    resultat = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_TRACE]), ocr_runtime=_RuntimeFictif()
    )
    vide = hashlib.sha256(b"").hexdigest()
    assert resultat.provenance[1].native_text_sha256 == vide
    assert resultat.provenance[1].canonical_page_text_sha256 != vide
    assert resultat.provenance[1].page_policy_verdict == "PAGE_TRACE_VECTORIEL"
    assert resultat.provenance[1].ocr_runtime_identity_sha256 == "f" * 64


def test_l_identite_de_la_politique_nomme_le_runtime_ocr_employe(ocr_espion) -> None:
    """Deux corpus océrisés sous des runtimes différents ne sont pas
    comparables : l'identité doit en changer."""
    _appels, rendu = ocr_espion
    rendu[2] = "texte"
    avec = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_TRACE]), ocr_runtime=_RuntimeFictif()
    )
    sans = extraire_document(_pdf([FLUX_TEXTE, FLUX_TEXTE]))
    assert avec.identity()["ocr_runtime_identity_sha256"] == "f" * 64
    assert avec.identity_sha256() != sans.identity_sha256()
    assert avec.identity()["policy_id"] == "NEXUS-DRIVE-PDF-EXTRACTION-V2"
    assert avec.identity()["page_policy_id"] == "NEXUS-PDF-PAGE-POLICY-V1"
    assert len(str(avec.identity()["page_policy_sha256"])) == 64


def test_le_texte_ocerise_passe_par_la_normalisation(ocr_espion) -> None:
    """U+0000 vient aussi de l'OCR. Le laisser passer ferait échouer
    l'écriture en base APRÈS le scan PII — donc sur un texte déjà déclaré
    sain mais jamais stocké."""
    _appels, rendu = ocr_espion
    rendu[2] = "avant\x00apres"
    resultat = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_TRACE]), ocr_runtime=_RuntimeFictif()
    )
    assert resultat.pages[1].text == "avantapres"


def test_le_texte_canonique_est_la_concatenation_des_pages_retenues(ocr_espion) -> None:
    _appels, rendu = ocr_espion
    rendu[2] = "DEUX"
    resultat = extraire_document(
        _pdf([FLUX_TEXTE, FLUX_TRACE]), ocr_runtime=_RuntimeFictif()
    )
    assert resultat.canonical_text == "\n".join(p.text for p in resultat.pages)
    assert "DEUX" in resultat.canonical_text


# --- une panne d'instrument n'est jamais un verdict -------------------


def test_une_panne_d_inspection_n_est_pas_lue_comme_page_ignorable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sans cette garde, une politique en panne rendrait « aucune page à
    océriser » et le document passerait pour complet."""
    import nexus_pdf_page_policy
    from nexus_pdf_page_policy import PageInspectionError

    def tombe(pdf_content: bytes, numeros):
        raise PageInspectionError("instrument indisponible")

    monkeypatch.setattr(nexus_pdf_page_policy, "classer_pages_sans_texte", tombe)
    with pytest.raises(PageInspectionError):
        extraire_document(_pdf([FLUX_TEXTE, FLUX_TRACE]), ocr_runtime=_RuntimeFictif())
