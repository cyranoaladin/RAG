"""CoverageAgent — agrège un ``CoverageSnapshot`` déterministe (LOT44d).

Hors machine d'état (``NORMAL_SEQUENCE``) : ce stage n'appelle jamais
``apply_resource_transition``, il n'observe ni ne modifie
``resource_state``. Son entrée est un historique déjà rassemblé par
l'appelant (évidences de sujets issues de ``Classifier``, scores issus de
``QualityAgent``) — LOT44d ne lit jamais lui-même ``workflow_events`` pour
construire cet historique ; c'est la responsabilité d'un futur appelant
(LOT44e, scheduler) de le fournir.

``recommended_next_queries`` reprend exactement les sujets non couverts
(``insufficient_topics``) — pensé pour alimenter ``Planner.gap_targets``
lors d'un prochain cycle, sans qu'aucun câblage automatique entre les deux
stages n'existe dans ce lot (aucune boucle, cf. ADR-0029).
"""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from nexus_contracts.ingestion import CollectionProfile, CoverageSnapshot


def build_coverage_snapshot_core(
    *,
    profile: CollectionProfile,
    snapshot_id: UUID,
    period_start: datetime,
    period_end: datetime,
    topic_evidence_per_resource: Sequence[tuple[str, ...]],
    quality_scores: Sequence[float],
    stale_resources: int = 0,
) -> CoverageSnapshot:
    """Agrège un instantané de couverture — aucune E/S, aucune horloge.

    ``topic_evidence_per_resource`` : une entrée par ressource déjà traitée
    dans la période (typiquement ``ConformityResult.matiere_evidence`` de
    ``Classifier``) — jamais relu depuis une base par ce cœur.
    """
    resources_per_topic: dict[str, int] = {topic: 0 for topic in profile.expected_topics}
    for evidence in topic_evidence_per_resource:
        for topic in evidence:
            if topic in resources_per_topic:
                resources_per_topic[topic] += 1

    covered_topics = [topic for topic in profile.expected_topics if resources_per_topic[topic] > 0]
    insufficient_topics = [
        topic for topic in profile.expected_topics if resources_per_topic[topic] == 0
    ]

    average_quality = (
        sum(quality_scores) / len(quality_scores) if quality_scores else None
    )

    return CoverageSnapshot(
        snapshot_id=snapshot_id,
        scope=profile.scope,
        period_start=period_start,
        period_end=period_end,
        expected_topics=list(profile.expected_topics),
        covered_topics=covered_topics,
        insufficient_topics=insufficient_topics,
        resources_per_topic=resources_per_topic,
        average_quality=average_quality,
        stale_resources=stale_resources,
        gaps=list(insufficient_topics),
        recommended_next_queries=list(insufficient_topics),
    )


__all__ = ["build_coverage_snapshot_core"]
