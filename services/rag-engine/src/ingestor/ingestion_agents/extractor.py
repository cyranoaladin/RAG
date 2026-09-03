"""Extractor — décode le contenu brut d'un artefact en texte (LOT44d).

Porte la transition ``STORED -> EXTRACTED``. Le texte brut est décodé
minimalement (UTF-8 avec repli latin-1, retrait naïf des balises pour le
HTML) ; le PDF est extrait page par page par ``pypdf``.

**Le PDF passe par le même chemin que le reste.** Le corpus institutionnel
est fait de PDF : un extracteur qui les refusait rendait le worker
incapable d'ingérer ce qu'il existe pour ingérer, et obligeait les preuves
de bout en bout à emprunter un adaptateur de test. Il n'y a donc ni
branche particulière dans le worker, ni cas spécial sur un contenu donné —
``run_extractor`` traite un PDF exactement comme un texte.

L'OCR reste hors périmètre : une page sans texte natif est refusée et part
en revue, jamais approximée. Aucun score
de qualité n'est calculé ici (``extraction_quality``/``readability``/
``structure_score`` sont des champs de ``QualityReport``, calculés par
``QualityAgent`` à partir du texte produit ici, pas dupliqués deux fois).
"""
from __future__ import annotations

import hashlib
import re
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import ArtifactRecord
from nexus_contracts.resource_state import ResourceState

# Foyer unique du prédicat structurel « page sans texte » (ADR-0046) : partagé
# avec le scanner PII de rag-pedago, jamais recopié ici.
from nexus_pdf_page_policy import (
    PAGE_INSPECTION_ECHOUEE,
    SENS_DES_MOTIFS,
    PageInspectionError,
    motif_de_refus_page,
)

from .dependencies import ArtifactReader
from .transitions import TransitionResult, apply_resource_transition

#: Type MIME des documents du corpus institutionnel. Traité par le même
#: ``run_extractor`` que le texte : le worker n'a pas de branche
#: particulière, et aucun adaptateur de test ne double ce chemin.
PDF_MIME_TYPE = "application/pdf"

#: MIME types explicitement pris en charge — fail closed sur tout autre
#: type (image, archive) plutôt qu'une tentative optimiste de décodage.
SUPPORTED_MIME_TYPES = frozenset({"text/plain", "text/html", PDF_MIME_TYPE})

#: Bornes du décodage PDF. Un document hostile doit se heurter à un refus
#: nommé, pas à une consommation mémoire non bornée.
MAX_PDF_PAGES = 2_000
MAX_PDF_TEXT_CHARS = 20_000_000

#: Séparateur de page dans le texte agrégé. Explicite et stable : les
#: chunks en dérivent leur numéro de page, donc la citation qui remonte à
#: l'élève. Un séparateur variable rendrait la page non reconstituable.
PAGE_SEPARATOR = "\n\n"

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class UnsupportedMimeTypeError(ValueError):
    """``mime_detected`` de l'artefact n'est pas pris en charge par ce
    décodage minimal — rejet explicite, jamais un texte vide silencieux."""


class PdfExtractionError(ValueError):
    """Le PDF n'a pas rendu de texte exploitable — refus explicite.

    **Pourquoi échouer plutôt que sauter la page.** Une page image-only
    dont on ignore l'échec produit un document amputé qui *paraît*
    complet : les chunks existent, la citation renvoie un numéro de page,
    et rien n'indique que le contenu de cette page n'a jamais été indexé.
    Un élève interrogeant précisément cette notion reçoit alors un silence
    qui ressemble à une absence dans le programme.

    L'OCR n'est pas un prérequis de cette étape : un document qui en aurait
    besoin est refusé et part en revue, il n'est pas approximé."""


class ArtifactIntegrityError(ValueError):
    """Le contenu relu (``read_artifact``) ne correspond pas à
    ``ArtifactRecord.size_bytes``/``sha256`` — remédiation revue PR#90 :
    avant ce correctif, un objet corrompu ou substitué (stockage altéré,
    reprise sur un mauvais fichier, etc.) était accepté sans vérification
    et la ressource passait ``EXTRACTED`` sur un contenu jamais prouvé
    identique à celui réellement téléchargé par Fetcher."""


#: Critère de traitement d'une page sans texte extractible.
#:
#: Une page sans texte n'est PAS refusée par principe : elle l'est si elle peut
#: porter un glyphe que l'indexation ne lira pas. Quatre conditions, sans seuil,
#: fixées dans ``docs/reports/lot_1_2_critere_page_sans_texte.md`` le 31/08/2026.
#:
#: Le refus précédent tombait sur la PREMIÈRE page sans texte, en affirmant dans
#: son message qu'elle était une page-image. Mesuré sur le corpus des 2 451 PDF :
#: 42 documents portent au moins une page sans texte, et 16 d'entre eux n'ont que
#: des pages RÉELLEMENT vides — verso de couverture, quatrième de couverture. Ils
#: étaient refusés en bloc, pour 1 720 120 caractères, soit 2,56 % du corpus.
#:
def extract_pdf_pages(raw_bytes: bytes) -> list[str]:
    """Rend le texte de chaque page, dans l'ordre, ou refuse.

    Déterministe : ``pypdf`` est appelé page par page, sans heuristique
    de mise en page ni réordonnancement. Deux exécutions sur les mêmes
    octets rendent la même liste, ce qui est la condition pour que le
    digest d'un chunk identifie un contenu plutôt qu'une exécution.

    Une page sans texte exploitable est un refus, jamais un saut : voir
    ``PdfExtractionError``.
    """
    import io

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
    total = 0
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
            # Le verdict vient du foyer partagé avec le scanner PII (ADR-0046) :
            # même critère, mêmes codes, sur les mêmes octets. Une panne de
            # l'instrument n'est pas « aucune image » : c'est un refus nommé.
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
            # Page réellement vide — verso de couverture, séparateur, quatrième
            # de couverture. Elle ne peut porter aucun glyphe. On l'IGNORE sans
            # la retirer : la liste reste alignée sur la numérotation réelle du
            # document, car `chunk_publication` en déduit le numéro de page par
            # `enumerate`. Retirer l'entrée décalerait toutes les citations
            # suivantes d'une page.
            pages.append("")
            continue
        total += len(text)
        if total > MAX_PDF_TEXT_CHARS:
            raise PdfExtractionError(
                f"extracted text exceeds the {MAX_PDF_TEXT_CHARS}-character bound"
            )
        pages.append(text)

    if not any(pages):
        # Aucune page ne rend de texte : il n'y a rien à indexer. Le document
        # est refusé, comme avant — c'est le cas que couvrait le refus sur la
        # première page vide, et il reste couvert.
        raise PdfExtractionError(
            f"the PDF yielded no text on any of its {page_count} pages — "
            "refusing rather than indexing an empty document (an image-only "
            "document needs OCR, which this stage deliberately does not attempt)"
        )
    return pages


def extract_text_core(*, artifact: ArtifactRecord, raw_bytes: bytes) -> str:
    """Décode ``raw_bytes`` en texte — aucune E/S, aucune horloge.

    UTF-8 en priorité, repli latin-1 si le décodage UTF-8 échoue (jamais un
    échec silencieux sur un artefact réel dont l'encodage exact est
    inconnu). Pour le HTML, retrait naïf des balises (``re.sub``) — pas un
    analyseur DOM réel.
    """
    if artifact.mime_detected not in SUPPORTED_MIME_TYPES:
        raise UnsupportedMimeTypeError(
            f"Extractor does not support mime_detected={artifact.mime_detected!r} "
            f"in this lot (supported: {sorted(SUPPORTED_MIME_TYPES)})"
        )

    if artifact.mime_detected == PDF_MIME_TYPE:
        return PAGE_SEPARATOR.join(
            page for page in extract_pdf_pages(raw_bytes) if page
        )

    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = raw_bytes.decode("latin-1")

    if artifact.mime_detected == "text/html":
        text = _HTML_TAG_PATTERN.sub(" ", text)

    return _WHITESPACE_PATTERN.sub(" ", text).strip()


def run_extractor(
    conn: psycopg.Connection,
    *,
    artifact: ArtifactRecord,
    expected_version: int,
    actor: str,
    read_artifact: ArtifactReader,
    job_id: UUID | None = None,
) -> tuple[str, TransitionResult]:
    """Relit le contenu persisté (``read_artifact`` injecté, aucun défaut
    réel), décode, puis transitionne ``STORED -> EXTRACTED``."""
    if artifact.extracted_text_ref is None:
        raise ValueError("artifact.extracted_text_ref is required to read back stored content")

    raw_bytes = read_artifact(extracted_text_ref=artifact.extracted_text_ref)

    if len(raw_bytes) != artifact.size_bytes:
        raise ArtifactIntegrityError(
            f"artifact {artifact.artifact_id}: reread {len(raw_bytes)} bytes, "
            f"expected size_bytes={artifact.size_bytes} — refusing to extract "
            "from content that does not match the persisted record"
        )
    actual_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    if actual_sha256 != artifact.sha256:
        raise ArtifactIntegrityError(
            f"artifact {artifact.artifact_id}: reread content sha256={actual_sha256}, "
            f"expected sha256={artifact.sha256} — refusing to extract from "
            "corrupted or substituted content"
        )

    extracted_text = extract_text_core(artifact=artifact, raw_bytes=raw_bytes)

    transition = apply_resource_transition(
        conn,
        resource_id=artifact.resource_id,
        expected_state=ResourceState.STORED,
        expected_version=expected_version,
        new_state=ResourceState.EXTRACTED,
        actor=actor,
        run_id=artifact.run_id,
        job_id=job_id,
        payload={"artifact_id": str(artifact.artifact_id), "extracted_chars": len(extracted_text)},
    )

    return extracted_text, transition


__all__ = [
    "SUPPORTED_MIME_TYPES",
    "ArtifactIntegrityError",
    "UnsupportedMimeTypeError",
    "extract_text_core",
    "run_extractor",
]
