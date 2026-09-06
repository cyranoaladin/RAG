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
