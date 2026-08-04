"""Classifier — évalue la conformité du texte extrait au profil (LOT44d).

Porte la transition ``EXTRACTED -> CLASSIFIED``.

Avertissement explicite (non contourné silencieusement) : ce cœur n'est
**pas** un classifieur de contenu pédagogique réel. ``niveau``/``voie``/
``programme_conformity`` restent hérités du scope déjà porté par la
ressource depuis ``Scout`` (jamais reclassés indépendamment du contenu,
faute d'un modèle réel dans ce lot) ; seule ``matiere_conformity`` est
recalculée à partir du texte, par une heuristique minimale (présence d'au
moins un sujet attendu du profil) — un signal faible, pas une preuve de
pertinence pédagogique. Un futur lot qui introduirait un vrai modèle de
classification devra remplacer ``classify_conformity_core`` sans changer sa
signature ; cf. ADR-0027 pour cette réserve.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import CollectionProfile
from nexus_contracts.resource_state import ResourceState

from ingestor.ingestion_agents.transitions import TransitionResult, apply_resource_transition


@dataclass(frozen=True)
class ConformityResult:
    niveau_conformity: bool
    voie_conformity: bool
    matiere_conformity: bool
    programme_conformity: bool
    matiere_evidence: tuple[str, ...]


def classify_conformity_core(
    *,
    extracted_text: str,
    profile: CollectionProfile,
) -> ConformityResult:
    """Heuristique déterministe minimale — aucune E/S, aucun modèle externe.

    ``matiere_conformity`` est vraie si au moins un ``expected_topics`` du
    profil apparaît (recherche insensible à la casse) dans le texte extrait
    — ``matiere_evidence`` porte la liste des sujets effectivement trouvés,
    jamais un booléen nu sans justification.
    """
    normalized_text = extracted_text.casefold()
    found_topics = tuple(
        topic for topic in profile.expected_topics if topic.casefold() in normalized_text
    )

    return ConformityResult(
        niveau_conformity=True,
        voie_conformity=True,
        matiere_conformity=len(found_topics) > 0,
        programme_conformity=True,
        matiere_evidence=found_topics,
    )


def run_classifier(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    run_id: UUID,
    extracted_text: str,
    profile: CollectionProfile,
    expected_version: int,
    actor: str,
    job_id: UUID | None = None,
) -> tuple[ConformityResult, TransitionResult]:
    """Calcule la conformité puis transitionne ``EXTRACTED -> CLASSIFIED``."""
    result = classify_conformity_core(extracted_text=extracted_text, profile=profile)

    transition = apply_resource_transition(
        conn,
        resource_id=resource_id,
        expected_state=ResourceState.EXTRACTED,
        expected_version=expected_version,
        new_state=ResourceState.CLASSIFIED,
        actor=actor,
        run_id=run_id,
        job_id=job_id,
        payload={
            "matiere_conformity": result.matiere_conformity,
            "matiere_evidence": list(result.matiere_evidence),
        },
    )

    return result, transition


__all__ = ["ConformityResult", "classify_conformity_core", "run_classifier"]
