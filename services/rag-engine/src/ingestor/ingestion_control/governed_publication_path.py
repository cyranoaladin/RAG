"""Chemin interne LOT42 préparé pour répétition, jamais câblé au runtime.

Ce module matérialise les pas manquants de la machine d'état sans créer de
second chemin vers ``RETRIEVAL_ELIGIBLE`` : seul
``attempt_retrieval_eligible_transition`` effectue toujours ce dernier pas.
Il n'est importé ni par le worker vivant, ni par une API, ni par un cron.
L'activation production reste donc explicitement hors de ce module.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg
from nexus_contracts.resource_state import ResourceState

from .publication_attestation import (
    VerifiedAttestation,
    attempt_retrieval_eligible_transition,
    verify_publication_attestation,
)
from .transitions import TransitionResult, cas_transition


@dataclass(frozen=True)
class PublicationReviewStaging:
    staged: TransitionResult
    needs_review: TransitionResult


@dataclass(frozen=True)
class GovernedEligibilityPromotion:
    attestation: VerifiedAttestation
    reviewed: TransitionResult
    retrieval_eligible: TransitionResult


def stage_publication_for_review(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    run_id: UUID,
    expected_version: int,
    actor: str,
    job_id: UUID | None = None,
) -> PublicationReviewStaging:
    """Appliquer atomiquement ``ROUTED -> STAGED -> NEEDS_REVIEW``.

    L'appel exige l'état et la version exacts ; aucun état n'est déduit et
    aucun saut n'est possible. Le contexte de transaction devient un
    savepoint si l'appelant possède déjà une transaction.
    """
    with conn.transaction():
        staged = cas_transition(
            conn,
            resource_id=resource_id,
            expected_state=ResourceState.ROUTED,
            expected_version=expected_version,
            new_state=ResourceState.STAGED,
            actor=actor,
            run_id=run_id,
            job_id=job_id,
            payload={"publication_gate": "LOT42_STAGED"},
        )
        needs_review = cas_transition(
            conn,
            resource_id=resource_id,
            expected_state=ResourceState.STAGED,
            expected_version=staged.state_version,
            new_state=ResourceState.NEEDS_REVIEW,
            actor=actor,
            run_id=run_id,
            job_id=job_id,
            payload={"publication_gate": "LOT42_HUMAN_REVIEW_REQUIRED"},
        )
    return PublicationReviewStaging(staged=staged, needs_review=needs_review)


def promote_reviewed_publication(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    run_id: UUID,
    expected_version: int,
    actor: str,
    current_content_sha256: str,
    current_profile_fingerprint: str,
    current_manifest_digest: str,
    job_id: UUID | None = None,
) -> GovernedEligibilityPromotion:
    """Valider la revue humaine puis emprunter l'unique ancre LOT42.

    La chaîne live est vérifiée avant ``NEEDS_REVIEW -> REVIEWED``. L'ancre
    la vérifie de nouveau immédiatement avant le dernier CAS. Toute erreur
    annule les transitions de cet appel ; aucune valeur d'environnement ou
    option booléenne ne peut remplacer l'attestation.
    """
    with conn.transaction():
        attestation = verify_publication_attestation(
            conn,
            resource_id=resource_id,
            current_content_sha256=current_content_sha256,
            current_profile_fingerprint=current_profile_fingerprint,
            current_manifest_digest=current_manifest_digest,
            require_content_bound_authority=True,
        )
        reviewed = cas_transition(
            conn,
            resource_id=resource_id,
            expected_state=ResourceState.NEEDS_REVIEW,
            expected_version=expected_version,
            new_state=ResourceState.REVIEWED,
            actor=actor,
            run_id=run_id,
            job_id=job_id,
            payload={
                "publication_attestation_id": str(attestation.attestation_id),
                "publication_review_id": attestation.review_id,
                "publication_attestation_digest": attestation.attestation_digest,
            },
        )
        retrieval_eligible = attempt_retrieval_eligible_transition(
            conn,
            resource_id=resource_id,
            run_id=run_id,
            expected_version=reviewed.state_version,
            actor=actor,
            current_content_sha256=current_content_sha256,
            current_profile_fingerprint=current_profile_fingerprint,
            current_manifest_digest=current_manifest_digest,
            job_id=job_id,
        )
    return GovernedEligibilityPromotion(
        attestation=attestation,
        reviewed=reviewed,
        retrieval_eligible=retrieval_eligible,
    )


__all__ = [
    "GovernedEligibilityPromotion",
    "PublicationReviewStaging",
    "promote_reviewed_publication",
    "stage_publication_for_review",
]
