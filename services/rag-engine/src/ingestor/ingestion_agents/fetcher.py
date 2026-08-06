"""Fetcher — télécharge et persiste un ``ArtifactRecord`` (LOT44d).

Porte deux transitions distinctes, jamais fusionnées en un saut :
``CANDIDATE -> FETCHED`` (téléchargement réussi) puis ``FETCHED -> STORED``
(persistance réussie) — ``NORMAL_SEQUENCE`` n'autorise aucun saut direct
``CANDIDATE -> STORED``.

``rights_status`` de l'``ArtifactRecord`` est toujours ``Rights.unknown`` à
ce stade : le contrat LOT44a exige ce champ dès la création de l'artefact,
mais la détermination réelle des droits est la responsabilité de
``RightsAgent`` (transition ultérieure ``CLASSIFIED -> RIGHTS_CHECKED``,
hors mutation de cet enregistrement — cf. ADR-0029, tension de contrat
documentée explicitement plutôt que contournée silencieusement).
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

import psycopg
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ArtifactRecord, ResourceCandidate
from nexus_contracts.resource_state import ResourceState

from .dependencies import (
    ArtifactStore,
    SafeFetcher,
    default_safe_fetch,
)
from .transitions import TransitionResult, apply_resource_transition

#: Codes HTTP jamais transitoires — une nouvelle tentative identique
#: échouerait de la même façon (ressource absente, accès refusé,
#: redirection interdite déjà résolue par ssrf_guard, etc.). Tout le reste
#: (429, 5xx) est traité comme potentiellement transitoire.
_NON_RETRYABLE_STATUS_CODES = frozenset({400, 401, 403, 404, 405, 410, 451})


class FetchHTTPError(RuntimeError):
    """``safe_fetch`` a renvoyé un statut HTTP d'erreur (4xx/5xx) —
    remédiation revue PR#90 : avant ce correctif, ce cas n'était jamais
    distingué d'un téléchargement réussi, et le corps de la réponse
    d'erreur (page 404, message d'accès refusé, etc.) pouvait être haché,
    stocké et transitionné comme un artefact pédagogique valide.

    ``retryable`` distingue une erreur probablement transitoire (429, 5xx —
    une nouvelle tentative a une chance raisonnable de réussir) d'une
    erreur définitive (4xx hors 429 — même contenu, même échec à coup
    sûr) ; cette classification est portée par l'exception pour un futur
    appelant qui voudrait l'exploiter, sans elle-même modifier ici le
    comportement de retry/backoff déjà existant de
    ``ingestion_worker.runner`` (qui reste, pour cette passe, uniforme
    quel que soit le type d'échec — cf. rapport de lot)."""

    def __init__(self, *, status_code: int, url: str) -> None:
        self.status_code = status_code
        self.url = url
        self.retryable = status_code not in _NON_RETRYABLE_STATUS_CODES
        super().__init__(
            f"fetch failed with HTTP {status_code} for {url!r} "
            f"({'retryable' if self.retryable else 'non-retryable'})"
        )


def build_artifact_core(
    *,
    candidate: ResourceCandidate,
    artifact_id: UUID,
    sha256: str,
    size_bytes: int,
    mime_declared: str,
    mime_detected: str,
    final_url: str,
    collected_at: datetime,
    publisher: str | None = None,
    title: str | None = None,
    license: str | None = None,
    pages_count: int | None = None,
    version: str | None = None,
    extracted_text_ref: str | None = None,
) -> ArtifactRecord:
    """Construit un ``ArtifactRecord`` déterministe à partir d'octets déjà
    téléchargés et déjà persistés — aucune E/S dans cette fonction."""
    return ArtifactRecord(
        artifact_id=artifact_id,
        resource_id=candidate.resource_id,
        run_id=candidate.run_id,
        scope=candidate.scope,
        sha256=sha256,
        size_bytes=size_bytes,
        mime_declared=mime_declared,
        mime_detected=mime_detected,
        original_url=candidate.source_url,
        final_url=final_url,
        collected_at=collected_at,
        domain=candidate.domain,
        publisher=publisher if publisher is not None else candidate.publisher,
        title=title if title is not None else candidate.title,
        license=license,
        rights_status=Rights.unknown,
        pages_count=pages_count,
        version=version,
        extracted_text_ref=extracted_text_ref,
    )


def run_fetcher(
    conn: psycopg.Connection,
    *,
    candidate: ResourceCandidate,
    artifact_id: UUID,
    collected_at: datetime,
    expected_version: int,
    actor: str,
    max_bytes: int,
    store_artifact: ArtifactStore,
    job_id: UUID | None = None,
    mime_declared: str = "application/octet-stream",
    license: str | None = None,
    safe_fetch: SafeFetcher = default_safe_fetch,
) -> tuple[ArtifactRecord, TransitionResult, TransitionResult]:
    """Télécharge (garde SSRF), transitionne vers ``FETCHED``, persiste
    (``store_artifact`` injecté, aucun défaut réel), transitionne vers
    ``STORED``. Deux transitions CAS distinctes, chacune journalisée
    séparément — jamais une seule écriture combinée.

    ``license`` (remédiation revue PR#90) : propagée à l'``ArtifactRecord``
    construit ici, **avant** que l'appelant ne le persiste — avant ce
    correctif, l'appelant (``ingestion_worker.runner``) reconstruisait un
    ``ArtifactRecord`` avec la licence *après* la persistance, sur une
    copie en mémoire jamais écrite en base : une reprise après crash
    relisait alors un artefact durablement sans licence, faisant échouer
    ``RightsAgent`` (``Rights.unknown`` forcé) même quand une licence avait
    bien été déclarée par l'opérateur.
    """
    response = safe_fetch(candidate.source_url, max_bytes=max_bytes)
    if response.status_code >= 400:
        raise FetchHTTPError(status_code=response.status_code, url=candidate.source_url)
    content = response.content
    sha256 = hashlib.sha256(content).hexdigest()
    mime_detected = response.headers.get("content-type", mime_declared).split(";")[0].strip()
    final_url = str(response.request.url) if response.request is not None else candidate.source_url

    fetched_transition = apply_resource_transition(
        conn,
        resource_id=candidate.resource_id,
        expected_state=ResourceState.CANDIDATE,
        expected_version=expected_version,
        new_state=ResourceState.FETCHED,
        actor=actor,
        run_id=candidate.run_id,
        job_id=job_id,
        payload={"artifact_id": str(artifact_id), "sha256": sha256, "size_bytes": len(content)},
    )

    extracted_text_ref = store_artifact(artifact_id=artifact_id, content=content)

    stored_transition = apply_resource_transition(
        conn,
        resource_id=candidate.resource_id,
        expected_state=ResourceState.FETCHED,
        expected_version=fetched_transition.state_version,
        new_state=ResourceState.STORED,
        actor=actor,
        run_id=candidate.run_id,
        job_id=job_id,
        payload={"artifact_id": str(artifact_id), "extracted_text_ref": extracted_text_ref},
    )

    artifact = build_artifact_core(
        candidate=candidate,
        artifact_id=artifact_id,
        sha256=sha256,
        size_bytes=len(content),
        mime_declared=mime_declared,
        mime_detected=mime_detected,
        final_url=final_url,
        collected_at=collected_at,
        extracted_text_ref=extracted_text_ref,
        license=license,
    )

    return artifact, fetched_transition, stored_transition


__all__ = ["FetchHTTPError", "build_artifact_core", "run_fetcher"]
