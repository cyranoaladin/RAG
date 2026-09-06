"""Extraction de texte PDF sous le runtime canonique.

Le découpage en chunks dépend du texte extrait, et le texte extrait
dépend de la version de ``pypdf`` : mesuré sur les 320 PDF de la
production visée, 4.2.0 et 6.14.2 rendent le même nombre de pages et le
même verdict de pages vides, mais un texte différent sur 319 documents
sur 320. Extraire hors du runtime déclaré produirait donc des chunks
reproductibles… d'une machine à l'autre seulement par hasard.

``nexus_pdf_page_policy`` porte ce verrou et le prédicat canonique qui
qualifie une page sans texte. On l'exige ici plutôt que de le
redécrire : deux définitions de « page vide » divergeraient en silence.
"""
from __future__ import annotations

from io import BytesIO

from rag_pedago.governance.drive_slice import PageText
from rag_pedago.governance.drive_source import DriveSourceError

#: Identité VERSIONNÉE de la normalisation textuelle appliquée après
#: extraction. Elle est nommée pour pouvoir être attestée : deux corpus
#: découpés sous des normalisations différentes ne sont pas comparables, et
#: une normalisation muette rendrait le découpage irreproductible sans que
#: rien ne le dise.
TEXT_NORMALISATION_ID = "NEXUS-DRIVE-TEXT-NORMALISATION-V1"

#: U+0000 n'est pas du texte. `pypdf` l'émet lorsqu'un glyphe n'a aucune
#: correspondance Unicode dans la police du document — mesuré sur le corpus
#: gouverné, il s'agit systématiquement d'un appel de note de bas de page
#: (`\nN\x00<numéro>`). Le caractère ne porte donc aucune information, et
#: PostgreSQL refuse de le stocker en colonne `text`.
#:
#: On le RETIRE plutôt que de le remplacer : un U+FFFD injecterait un
#: artefact visible dans le texte servi et dans l'empreinte des chunks, là
#: où la suppression rend le texte que le document dit réellement.
#:
#: La normalisation ne touche QUE la représentation textuelle. Le fichier
#: source et son `content_sha256` restent intacts — c'est ce qui permet de
#: rejouer l'extraction et d'obtenir le même résultat.
_CARACTERES_RETIRES = ("\x00",)


def normalise_texte_page(texte: str) -> tuple[str, int]:
    """Rend le texte normalisé et le nombre de caractères retirés.

    Déterministe et sans état : deux exécutions sur les mêmes octets rendent
    le même texte. Le compte est rendu pour que l'appelant puisse l'attester
    plutôt que de le deviner."""
    retires = sum(texte.count(caractere) for caractere in _CARACTERES_RETIRES)
    if not retires:
        return texte, 0
    normalise = texte
    for caractere in _CARACTERES_RETIRES:
        normalise = normalise.replace(caractere, "")
    return normalise, retires


class PdfExtractionError(DriveSourceError):
    """Le document ne se lit pas — refus, jamais un texte vide de repli.

    Un PDF illisible rendu comme « zéro page de texte » serait ingéré
    comme un document sans contenu, indiscernable d'un document
    réellement vide."""


def extract_pdf_pages(content: bytes) -> tuple[PageText, ...]:
    """Rend une entrée par page, dans l'ordre du document."""
    from nexus_pdf_page_policy import require_canonical_pypdf
    from pypdf import PdfReader

    require_canonical_pypdf()

    try:
        reader = PdfReader(BytesIO(content))
    except Exception as exc:
        raise PdfExtractionError(
            f"document illisible : {type(exc).__name__}: {exc}"
        ) from exc

    pages: list[PageText] = []
    for number, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:
            raise PdfExtractionError(
                f"page {number} illisible : {type(exc).__name__}: {exc}"
            ) from exc
        text, _retires = normalise_texte_page(text)
        pages.append(PageText(number=number, text=text))
    if not pages:
        raise PdfExtractionError(
            "document illisible : aucune page — un document sans page ne peut "
            "pas être distingué d'une lecture qui a échoué"
        )
    return tuple(pages)


def refused_pages(content: bytes, pages: tuple[PageText, ...]) -> dict[int, str]:
    """Qualifie les pages sans texte avec le prédicat canonique.

    Une page sans texte n'est pas forcément un problème : une page de
    séparation n'a rien à enseigner. Une page-image, elle, porte un
    contenu que l'ingestion perdrait sans le dire. Le prédicat gouverné
    tranche ; ce module ne le rejoue pas."""
    from nexus_pdf_page_policy import classer_pages_sans_texte

    empty = [page.number for page in pages if not page.text.strip()]
    if not empty:
        return {}
    return classer_pages_sans_texte(content, empty)


__all__ = ["PdfExtractionError", "extract_pdf_pages", "refused_pages"]
