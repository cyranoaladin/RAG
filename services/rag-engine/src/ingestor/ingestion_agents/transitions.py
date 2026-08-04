"""Application d'une transition d'état de ressource — LOT44d/LOT44e.

Enchaîne explicitement ``is_valid_resource_transition`` (contrôle structurel
pur, LOT44a) puis ``cas_transition`` (écriture CAS réelle, LOT44b) — jamais
l'un sans l'autre, jamais une écriture directe de ``resource_state`` par un
stage. Aucun stage LOT44d n'appelle ``ingestion_control.cas_transition``
directement : tous passent par ``apply_resource_transition``.

Évolution LOT44e (retrait du hardcodage documenté par LOT44d) : ``job_id``
est désormais un paramètre explicite, optionnel, par défaut ``None``. LOT44d
seul (sans job réel — pas de table ``jobs`` avant LOT44e) laissait toujours
cette valeur à ``None`` ; LOT44e, premier producteur réel de ``job_id``
(``ingestion_control.jobs``, migration 004), le propage désormais depuis le
chemin scheduler/worker. Aucun ``job_id`` n'est jamais généré ici : cette
fonction ne fait que transmettre la valeur reçue de l'appelant à
``cas_transition`` — jamais une valeur devinée ou fabriquée.
"""
from __future__ import annotations

from uuid import UUID

import psycopg
from nexus_contracts.resource_state import ResourceState, is_valid_resource_transition

from ingestor.ingestion_control.transitions import (
    InvalidTransitionError,
    TransitionConflictError,
    TransitionResult,
    cas_transition,
)


def apply_resource_transition(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    expected_state: ResourceState,
    expected_version: int,
    new_state: ResourceState,
    actor: str,
    run_id: UUID,
    job_id: UUID | None = None,
    payload: dict[str, object] | None = None,
) -> TransitionResult:
    """Valide la transition puis l'écrit — jamais l'inverse.

    ``is_valid_resource_transition`` est déjà revérifié à l'intérieur de
    ``cas_transition`` (LOT44b) ; l'appel explicite ici permet à un stage
    LOT44d/44e de rejeter une transition structurellement invalide avant
    tout accès base, distinct d'un ``TransitionConflictError`` (conflit de
    concurrence CAS, constaté après accès base).

    ``job_id`` : transmis tel quel à ``cas_transition``, jamais généré ni
    deviné ici. Reste ``None`` par défaut pour tout appelant qui n'a pas de
    job réel (compatible avec l'usage LOT44d original, sans régression) ;
    un appelant LOT44e (scheduler/worker) le fournit explicitement, obtenu
    par ``ingestion_control.jobs.claim_job``.

    Ne committe pas la transaction : responsabilité de l'appelant, comme
    ``cas_transition`` lui-même.
    """
    if not is_valid_resource_transition(expected_state, new_state):
        raise InvalidTransitionError(
            f"{expected_state.value} -> {new_state.value} is not a valid resource transition"
        )
    return cas_transition(
        conn,
        resource_id=resource_id,
        expected_state=expected_state,
        expected_version=expected_version,
        new_state=new_state,
        actor=actor,
        run_id=run_id,
        job_id=job_id,
        payload=payload,
    )


__all__ = [
    "InvalidTransitionError",
    "TransitionConflictError",
    "TransitionResult",
    "apply_resource_transition",
]
