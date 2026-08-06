"""Classifier — évalue la conformité du texte extrait au profil (LOT44d).

Porte la transition ``EXTRACTED -> CLASSIFIED``.

Avertissement explicite (non contourné silencieusement) : ce cœur n'est
**pas** un classifieur de contenu pédagogique réel. Seule
``matiere_conformity`` est recalculée à partir du texte, par une
heuristique minimale (présence d'au moins un sujet attendu du profil) — un
signal faible, pas une preuve de pertinence pédagogique. Un futur lot qui
introduirait un vrai modèle de classification devra remplacer
``classify_conformity_core`` sans changer sa signature ; cf. ADR-0029 pour
cette réserve.

Remédiation revue PR#90 (Cubic P1 + Codex P1) : ``niveau_conformity``/
``voie_conformity``/``programme_conformity`` valaient auparavant toujours
``True`` — jamais vérifiées, seulement héritées du scope déclaré par
l'appelant. ``QualityAgent`` pouvait alors laisser router (``ROUTED``)
n'importe quelle page suffisamment longue contenant un seul sujet attendu,
même si elle enseignait le mauvais niveau, la mauvaise filière ou un
programme différent — la couche qualité ne prouvait rien sur ces trois
dimensions, elle affichait une conformité jamais vérifiée. Ces trois champs
valent désormais ``False`` (non vérifié, jamais assimilé à "vérifié
conforme") tant qu'aucun classifieur réel ne les calcule, et
``QualityAgent`` les traite comme des motifs de rejet explicites (cf.
``build_quality_report_core``) — ``ROUTED`` reste donc inatteignable par ce
lot jusqu'à l'introduction d'un vrai modèle, ce qui est le comportement
volontairement recherché par cette remédiation, pas une régression."""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg
from nexus_contracts.ingestion import CollectionProfile
from nexus_contracts.resource_state import ResourceState

from .transitions import TransitionResult, apply_resource_transition


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

    ``niveau_conformity``/``voie_conformity``/``programme_conformity``
    valent ``False`` : aucun classifieur réel de ce lot ne vérifie ces
    trois dimensions à partir du contenu — ``False`` signifie ici "non
    vérifié", jamais "vérifié non-conforme" (cf. docstring du module).
    """
    normalized_text = extracted_text.casefold()
    found_topics = tuple(
        topic for topic in profile.expected_topics if topic.casefold() in normalized_text
    )

    return ConformityResult(
        niveau_conformity=False,
        voie_conformity=False,
        matiere_conformity=len(found_topics) > 0,
        programme_conformity=False,
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
