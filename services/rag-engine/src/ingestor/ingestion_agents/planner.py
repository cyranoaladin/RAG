"""Planner — génère un ``SearchPlan`` déterministe à partir d'un profil (LOT44d).

Se situe en amont de la machine d'état (``NORMAL_SEQUENCE``) : un
``SearchPlan`` précède toute ressource ``DISCOVERED``, aucune transition de
``resource_state`` n'est portée par ce stage.

Le cœur (``plan_search_core``) est pur : aucune horloge, aucun réseau, aucun
générateur d'identifiant caché — ``search_plan_id``/``run_id``/
``generated_at`` sont des paramètres explicites fournis par l'appelant.
``run_planner`` est la seule couche qui touche le réseau (validation des
``seed_urls`` déclarés dans le profil via ``ssrf_guard.validate_destination``
injecté) — jamais le cœur.
"""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from nexus_contracts.ingestion import CollectionProfile, SearchPlan

from ingestor.ingestion_agents.dependencies import (
    DestinationValidator,
    default_validate_destination,
)


def plan_search_core(
    *,
    profile: CollectionProfile,
    run_id: UUID,
    search_plan_id: UUID,
    generated_at: datetime,
    reason: str,
    gap_targets: tuple[str, ...] = (),
) -> SearchPlan:
    """Construit un ``SearchPlan`` déterministe — aucune E/S, aucun défaut caché.

    Les requêtes sont dérivées des cibles de couverture (``gap_targets``,
    typiquement produites par ``CoverageAgent``) en priorité, complétées par
    les sujets attendus du profil (``expected_topics``) non déjà couverts —
    ordre stable, sans doublon, jamais une requête générique inventée.
    """
    ordered_queries: list[str] = []
    for target in (*gap_targets, *profile.expected_topics):
        if target not in ordered_queries:
            ordered_queries.append(target)

    return SearchPlan(
        search_plan_id=search_plan_id,
        run_id=run_id,
        scope=profile.scope,
        generated_at=generated_at,
        profile_version=profile.profile_version,
        gap_targets=list(gap_targets),
        queries=ordered_queries,
        allowed_domains=list(profile.allowed_domains),
        required_resource_types=list(profile.expected_resource_types),
        required_topics=list(profile.expected_topics),
        excluded_topics=list(profile.excluded_topics),
        max_results=profile.max_documents_per_run,
        reason=reason,
    )


def run_planner(
    *,
    profile: CollectionProfile,
    run_id: UUID,
    search_plan_id: UUID,
    generated_at: datetime,
    reason: str,
    gap_targets: tuple[str, ...] = (),
    validate_destination: DestinationValidator = default_validate_destination,
) -> SearchPlan:
    """Valide les ``seed_urls`` déclarés par le profil puis délègue au cœur pur.

    Échec explicite (propagation de ``SSRFValidationError``) si un
    ``seed_url`` du profil est rejeté par la garde SSRF — jamais un retrait
    silencieux de l'URL fautive, jamais un plan partiel non signalé.
    """
    for seed_url in profile.seed_urls:
        validate_destination(seed_url)

    return plan_search_core(
        profile=profile,
        run_id=run_id,
        search_plan_id=search_plan_id,
        generated_at=generated_at,
        reason=reason,
        gap_targets=gap_targets,
    )


__all__ = ["plan_search_core", "run_planner"]
