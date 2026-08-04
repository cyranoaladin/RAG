"""Application d'une transition d'état de ressource — LOT44d.

Enchaîne explicitement ``is_valid_resource_transition`` (contrôle structurel
pur, LOT44a) puis ``cas_transition`` (écriture CAS réelle, LOT44b) — jamais
l'un sans l'autre, jamais une écriture directe de ``resource_state`` par un
stage. Aucun stage LOT44d n'appelle ``ingestion_control.cas_transition``
directement : tous passent par ``apply_resource_transition``.

``job_id`` reste structurellement ``NULL`` : aucun paramètre ne permet de le
renseigner. LOT44d ne crée ni run, ni job, ni table ``jobs`` — la production
réelle de ``job_id`` reste réservée à LOT44e (ADR-0025 « Suites »,
ADR-0026 « Contrat d'interface pour LOT44d et LOT44e »).
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
    payload: dict[str, object] | None = None,
) -> TransitionResult:
    """Valide la transition puis l'écrit — jamais l'inverse.

    ``is_valid_resource_transition`` est déjà revérifié à l'intérieur de
    ``cas_transition`` (LOT44b) ; l'appel explicite ici permet à un stage
    LOT44d de rejeter une transition structurellement invalide avant tout
    accès base, distinct d'un ``TransitionConflictError`` (conflit de
    concurrence CAS, constaté après accès base).

    ``job_id`` n'est jamais un paramètre de cette fonction : il est transmis
    à ``cas_transition`` en dur à ``None`` — aucun appelant LOT44d ne peut le
    renseigner, structurellement (cf. docstring du module).

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
        job_id=None,
        payload=payload,
    )


__all__ = [
    "InvalidTransitionError",
    "TransitionConflictError",
    "TransitionResult",
    "apply_resource_transition",
]
