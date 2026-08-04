"""Transition CAS atomique — primitive de concurrence #2 (LOT44b).

Réutilise intégralement la machine d'état de
``nexus_contracts.resource_state`` (LOT44a, ADR-0024) : aucune seconde
machine d'état concurrente n'est créée dans ce module. ``PUBLISHED`` reste
absent de tout ce qui suit — hérité de l'énumération LOT44a, jamais
redéfini ici.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg
from nexus_contracts.resource_state import ResourceState, is_valid_resource_transition
from psycopg.types.json import Jsonb


class TransitionConflictError(RuntimeError):
    """La ligne a déjà été modifiée par un autre processus (CAS raté).

    Jamais de transition silencieuse : cette exception est le seul moyen
    par lequel un appelant apprend qu'un autre processus a gagné la course.
    """


class InvalidTransitionError(ValueError):
    """La transition demandée n'est pas autorisée par la machine d'état."""


@dataclass(frozen=True)
class TransitionResult:
    resource_id: UUID
    from_state: ResourceState
    to_state: ResourceState
    state_version: int


def cas_transition(
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
    idempotency_key: str | None = None,
) -> TransitionResult:
    """Transition compare-and-swap : état ET version attendus.

    - **État attendu** : ``expected_state``.
    - **Version attendue** : ``expected_version`` (``resources.state_version``,
      incrémentée à chaque transition réussie) — double garde en plus de
      l'état lui-même, pour détecter même une transition vers le même état
      qui aurait eu lieu entre-temps (état identique mais version avancée).
    - **Mise à jour conditionnelle** : ``UPDATE ... WHERE resource_state = %s
      AND state_version = %s`` — jamais un ``UPDATE`` inconditionnel.
    - **Échec explicite** : si aucune ligne ne correspond (état ou version
      périmés), lève ``TransitionConflictError`` — ne met rien à jour,
      n'écrit aucun événement.
    - **Aucune transition silencieuse** : toute transition réussie journalise
      un ``workflow_events`` dans la même transaction.
    - **Aucune clé d'idempotence artificielle** : ``idempotency_key`` reste
      ``None`` par défaut — une transition ordinaire n'en reçoit jamais une ;
      seul un appelant qui sait produire un événement potentiellement
      rejoué (ex. réplique d'un claim) en fournit une explicitement.

    Validité structurelle vérifiée **avant** tout accès base
    (``is_valid_resource_transition``, LOT44a) : ``CANDIDATE -> STAGED``
    reste impossible ici comme dans les contrats Python, et aucune
    transition ne peut jamais viser ``PUBLISHED`` (absent de l'énumération).

    Ne committe pas la transaction : responsabilité de l'appelant.
    """
    if not is_valid_resource_transition(expected_state, new_state):
        raise InvalidTransitionError(
            f"{expected_state.value} -> {new_state.value} is not a valid resource transition"
        )

    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE ingestion_control.resources
            SET resource_state = %s, state_version = state_version + 1, updated_at = now()
            WHERE resource_id = %s AND resource_state = %s AND state_version = %s
            RETURNING state_version
            """,
            (new_state.value, resource_id, expected_state.value, expected_version),
        )
        row = cur.fetchone()
        if row is None:
            raise TransitionConflictError(
                f"resource {resource_id}: expected state={expected_state.value} "
                f"version={expected_version}, but the row did not match "
                "(concurrent modification or stale caller state)"
            )
        new_version = row[0]

        cur.execute(
            """
            INSERT INTO ingestion_control.workflow_events
                (run_id, job_id, resource_id, event_type, from_state, to_state,
                 actor, payload, idempotency_key)
            VALUES (%s, %s, %s, 'transition', %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                job_id,
                resource_id,
                expected_state.value,
                new_state.value,
                actor,
                Jsonb(payload or {}),
                idempotency_key,
            ),
        )

    return TransitionResult(
        resource_id=resource_id,
        from_state=expected_state,
        to_state=new_state,
        state_version=new_version,
    )


__all__ = [
    "InvalidTransitionError",
    "TransitionConflictError",
    "TransitionResult",
    "cas_transition",
]
