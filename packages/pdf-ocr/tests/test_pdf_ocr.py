"""Ce que la capacité OCR refuse de laisser passer.

Un chemin d'extraction qui retombe silencieusement quand sa dépendance manque
produit des documents vides « traités » — indiscernables d'un document
réellement vide, et bien plus dangereux puisque rien ne signale la perte.
C'est le comportement que ces épreuves interdisent.
"""

from __future__ import annotations

import shutil

import pytest
from nexus_pdf_ocr import (
    DEFAULT_DPI,
    DEFAULT_LANGUAGES,
    OCR_CAPABILITY_ID,
    OcrRuntime,
    OcrRuntimeUnavailable,
    describe_runtime,
    ocr_pdf_pages,
    require_runtime,
)

TESSERACT = shutil.which("tesseract")
PDFTOPPM = shutil.which("pdftoppm")
RUNTIME_PRESENT = TESSERACT is not None and PDFTOPPM is not None
besoin_runtime = pytest.mark.skipif(
    not RUNTIME_PRESENT, reason="tesseract/pdftoppm absents de cette machine"
)


def _runtime_fictif(**surcharges: object) -> OcrRuntime:
    base = {
        "capability_id": OCR_CAPABILITY_ID,
        "engine": "tesseract",
        "engine_version": "5.3.4",
        "leptonica_version": "1.82.0",
        "rasterizer": "pdftoppm",
        "rasterizer_version": "24.02.0",
        "languages": DEFAULT_LANGUAGES,
        "traineddata_sha256": (("fra", "a" * 64), ("eng", "b" * 64)),
        "dpi": DEFAULT_DPI,
    }
    base.update(surcharges)
    return OcrRuntime(**base)  # type: ignore[arg-type]


# --- l'identité du runtime fait partie de la preuve --------------------


def test_l_identite_change_avec_chaque_composant_du_runtime() -> None:
    """Le texte rendu dépend du moteur, de ses données linguistiques et de la
    résolution. Deux corpus océrisés sous des runtimes différents ne sont pas
    comparables : chaque composant doit donc entrer dans l'empreinte."""
    reference = _runtime_fictif().identity_sha256()
    for champ, valeur in (
        ("engine_version", "5.4.0"),
        ("leptonica_version", "1.83.0"),
        ("rasterizer_version", "25.01.0"),
        ("languages", "eng"),
        ("dpi", 150),
        ("traineddata_sha256", (("fra", "c" * 64), ("eng", "b" * 64))),
    ):
        autre = _runtime_fictif(**{champ: valeur}).identity_sha256()
        assert autre != reference, champ


def test_l_identite_est_stable_pour_un_meme_runtime() -> None:
    assert _runtime_fictif().identity_sha256() == _runtime_fictif().identity_sha256()


@besoin_runtime
def test_le_runtime_mesure_nomme_chacun_de_ses_composants() -> None:
    """Rien n'est supposé : les versions et les empreintes sont RELEVÉES."""
    runtime = describe_runtime()
    assert runtime.capability_id == OCR_CAPABILITY_ID
    assert runtime.engine == "tesseract"
    assert runtime.engine_version and runtime.engine_version != "inconnue"
    assert runtime.leptonica_version != "inconnue"
    assert runtime.rasterizer_version != "inconnue"
    assert {langue for langue, _ in runtime.traineddata_sha256} == {"fra", "eng"}
    for _, empreinte in runtime.traineddata_sha256:
        assert len(empreinte) == 64


@besoin_runtime
def test_un_runtime_qui_a_derive_est_refuse() -> None:
    """Épingler la seule version Python ne suffirait pas — c'est le binaire et
    les données linguistiques qui décident du texte."""
    with pytest.raises(OcrRuntimeUnavailable, match="OCR_RUNTIME_DRIFT"):
        require_runtime("0" * 64)


@besoin_runtime
def test_un_runtime_conforme_est_accepte() -> None:
    attendu = describe_runtime().identity_sha256()
    assert require_runtime(attendu).identity_sha256() == attendu


# --- fail-closed -------------------------------------------------------


def test_une_langue_sans_donnees_est_un_refus_pas_un_repli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if not RUNTIME_PRESENT:
        pytest.skip("tesseract absent")
    with pytest.raises(OcrRuntimeUnavailable, match="données linguistiques absentes"):
        describe_runtime(languages="fra+klingon")


def test_un_binaire_absent_est_un_refus_pas_un_repli(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Le défaut que cette capacité existe pour supprimer : sans cette garde,
    un document scanné serait rendu « traité » et vide."""
    monkeypatch.setattr("nexus_pdf_ocr.shutil.which", lambda _nom: None)
    with pytest.raises(OcrRuntimeUnavailable, match="OCR_RUNTIME_UNAVAILABLE"):
        describe_runtime()
    with pytest.raises(OcrRuntimeUnavailable, match="OCR_RUNTIME_UNAVAILABLE"):
        ocr_pdf_pages(b"%PDF-1.4", runtime=_runtime_fictif())


@besoin_runtime
def test_un_pdf_illisible_est_un_refus_pas_zero_page() -> None:
    from nexus_pdf_ocr import OcrError

    with pytest.raises(OcrError):
        ocr_pdf_pages(b"ceci n'est pas un PDF", runtime=describe_runtime())


# --- la sélection de pages -------------------------------------------


def _pdf_multipage(textes: list[str]) -> bytes:
    """Un PDF réel de `len(textes)` pages, chacune portant son texte en grand.

    Construit à la main plutôt qu'emprunté à un corpus : une épreuve qui
    dépendrait d'un document de production ne dirait plus rien le jour où ce
    document change.
    """
    objets: list[bytes] = []

    def ajouter(corps: bytes) -> int:
        objets.append(corps)
        return len(objets)

    kids: list[int] = []
    pages_id = len(textes) * 2 + 1  # l'objet /Pages suit les 2N objets de page
    for texte in textes:
        flux = f"BT /F1 48 Tf 72 500 Td ({texte}) Tj ET".encode("ascii")
        contenu = ajouter(
            b"<< /Length " + str(len(flux)).encode() + b" >>\nstream\n" + flux + b"\nendstream"
        )
        kids.append(
            ajouter(
                b"<< /Type /Page /Parent " + str(pages_id).encode() + b" 0 R "
                b"/MediaBox [0 0 612 792] /Resources << /Font << /F1 "
                + str(pages_id + 1).encode()
                + b" 0 R >> >> /Contents "
                + str(contenu).encode()
                + b" 0 R >>"
            )
        )
    ajouter(
        b"<< /Type /Pages /Count " + str(len(kids)).encode() + b" /Kids ["
        + b" ".join(str(k).encode() + b" 0 R" for k in kids)
        + b"] >>"
    )
    ajouter(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    catalogue = ajouter(b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")

    sortie = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = []
    for numero, corps in enumerate(objets, 1):
        offsets.append(len(sortie))
        sortie += str(numero).encode() + b" 0 obj\n" + corps + b"\nendobj\n"
    debut_xref = len(sortie)
    sortie += b"xref\n0 " + str(len(objets) + 1).encode() + b"\n0000000000 65535 f \n"
    for offset in offsets:
        sortie += f"{offset:010d} 00000 n \n".encode()
    sortie += (
        b"trailer\n<< /Size " + str(len(objets) + 1).encode() + b" /Root "
        + str(catalogue).encode() + b" 0 R >>\nstartxref\n"
        + str(debut_xref).encode() + b"\n%%EOF\n"
    )
    return bytes(sortie)


@besoin_runtime
def test_sans_selection_toutes_les_pages_sont_rendues() -> None:
    pages = ocr_pdf_pages(_pdf_multipage(["UN", "DEUX", "TROIS"]), runtime=describe_runtime())
    assert [page.number for page in pages] == [1, 2, 3]


@besoin_runtime
def test_une_selection_ne_rend_que_les_pages_demandees_avec_leurs_numeros_du_document() -> None:
    """Le numéro rendu est celui du DOCUMENT, jamais un rang dans la sélection.

    Renvoyer 1, 2 pour les pages 2 et 4 décalerait chaque citation et chaque
    empreinte de page sans que rien ne le montre.
    """
    pages = ocr_pdf_pages(
        _pdf_multipage(["UN", "DEUX", "TROIS", "QUATRE"]),
        runtime=describe_runtime(),
        pages=[4, 2],
    )
    assert [page.number for page in pages] == [2, 4]


@besoin_runtime
def test_une_selection_eparse_n_ocerise_pas_les_pages_intermediaires() -> None:
    """`pdftoppm` ne borne qu'un intervalle : sans le filtrage, la page 3 serait
    océrisée et rendue alors que personne ne l'a demandée."""
    pages = ocr_pdf_pages(
        _pdf_multipage(["UN", "DEUX", "TROIS", "QUATRE", "CINQ"]),
        runtime=describe_runtime(),
        pages=[2, 5],
    )
    assert [page.number for page in pages] == [2, 5]


def test_une_selection_vide_est_un_refus_pas_le_document_entier() -> None:
    """Demander RIEN n'est pas ne rien demander.

    Les confondre ferait océriser le document entier en croyant obéir — et
    ferait payer cent cinquante pages pour une sélection que l'appelant avait
    calculée vide.
    """
    from nexus_pdf_ocr import OcrError

    if not RUNTIME_PRESENT:
        pytest.skip("tesseract absent")
    with pytest.raises(OcrError, match="sélection de pages vide"):
        ocr_pdf_pages(_pdf_multipage(["UN"]), runtime=describe_runtime(), pages=[])


@besoin_runtime
def test_une_page_hors_du_document_est_un_refus_pas_un_silence() -> None:
    """Demander la page 9 d'un document de 3 pages est une erreur d'appelant.

    Rendre discrètement moins de pages que demandé laisserait le consommateur
    croire que la page existe et qu'elle est vide."""
    from nexus_pdf_ocr import OcrError

    with pytest.raises(OcrError, match="partition de pages incomplète"):
        ocr_pdf_pages(
            _pdf_multipage(["UN", "DEUX", "TROIS"]),
            runtime=describe_runtime(),
            pages=[2, 9],
        )
