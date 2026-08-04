"""Fetcher — télécharge et persiste un ``ArtifactRecord`` (LOT44d).

Porte deux transitions distinctes, jamais fusionnées en un saut :
``CANDIDATE -> FETCHED`` (téléchargement réussi) puis ``FETCHED -> STORED``
(persistance réussie) — ``NORMAL_SEQUENCE`` n'autorise aucun saut direct
``CANDIDATE -> STORED``.

``rights_status`` de l'``ArtifactRecord`` est toujours ``Rights.unknown`` à
ce stade : le contrat LOT44a exige ce champ dès la création de l'artefact,
mais la détermination réelle des droits est la responsabilité de
``RightsAgent`` (transition ultérieure ``CLASSIFIED -> RIGHTS_CHECKED``,
hors mutation de cet enregistrement — cf. ADR-0027, tension de contrat
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

from ingestor.ingestion_agents.dependencies import (
    ArtifactStore,
    SafeFetcher,
    default_safe_fetch,
)
from ingestor.ingestion_agents.transitions import TransitionResult, apply_resource_transition


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
    mime_declared: str = "application/octet-stream",
    safe_fetch: SafeFetcher = default_safe_fetch,
) -> tuple[ArtifactRecord, TransitionResult, TransitionResult]:
    """Télécharge (garde SSRF), transitionne vers ``FETCHED``, persiste
    (``store_artifact`` injecté, aucun défaut réel), transitionne vers
    ``STORED``. Deux transitions CAS distinctes, chacune journalisée
    séparément — jamais une seule écriture combinée.
    """
    response = safe_fetch(candidate.source_url, max_bytes=max_bytes)
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
    )

    return artifact, fetched_transition, stored_transition


__all__ = ["build_artifact_core", "run_fetcher"]
