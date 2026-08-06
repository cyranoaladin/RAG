"""Extractor — décode le contenu brut d'un artefact en texte (LOT44d).

Porte la transition ``STORED -> EXTRACTED``. Décodage volontairement
minimal (UTF-8 avec repli latin-1, retrait naïf des balises pour le HTML) :
ce n'est **pas** un moteur d'extraction PDF/OCR de production, seulement
l'interface et le contrat déterministe attendus par LOT44d — un futur lot
peut remplacer ``extract_text_core`` sans changer sa signature. Aucun score
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

from .dependencies import ArtifactReader
from .transitions import TransitionResult, apply_resource_transition

#: MIME types explicitement pris en charge par ce décodage minimal — fail
#: closed sur tout autre type (ex. PDF, image) plutôt qu'une tentative
#: optimiste de décodage.
SUPPORTED_MIME_TYPES = frozenset({"text/plain", "text/html"})

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class UnsupportedMimeTypeError(ValueError):
    """``mime_detected`` de l'artefact n'est pas pris en charge par ce
    décodage minimal — rejet explicite, jamais un texte vide silencieux."""


class ArtifactIntegrityError(ValueError):
    """Le contenu relu (``read_artifact``) ne correspond pas à
    ``ArtifactRecord.size_bytes``/``sha256`` — remédiation revue PR#90 :
    avant ce correctif, un objet corrompu ou substitué (stockage altéré,
    reprise sur un mauvais fichier, etc.) était accepté sans vérification
    et la ressource passait ``EXTRACTED`` sur un contenu jamais prouvé
    identique à celui réellement téléchargé par Fetcher."""


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
