"""Lease reaper — primitive de concurrence #4 (LOT44b).

Détecte et libère les baux expirés. Aucune logique de planification :
cette fonction ne boucle jamais, ne dort jamais, et ne décide jamais quand
elle doit être rappelée — un futur scheduler (hors périmètre LOT44b, cf.
consignes du lot : « ne doit pas devenir un worker ou un scheduler »)
décidera de la cadence d'appel.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import psycopg


@dataclass(frozen=True)
class ReapedLease:
    resource_id: UUID
    previous_owner: str | None
    previous_lease_token: UUID


def reap_expired_leases(conn: psycopg.Connection, *, limit: int = 100) -> list[ReapedLease]:
    """Libère les baux expirés — jamais un bail encore valide.

    - Un bail **encore valide** (``lease_expires_at IS NULL`` ou
      ``lease_expires_at >= now()``) n'est **jamais** touché : il est
      structurellement exclu du prédicat ``WHERE``.
    - Un bail **expiré** peut être récupéré **une seule fois** : la CTE
      capture ``claimed_by``/``lease_token`` *avant* la mise à jour (jamais
      les valeurs déjà nullifiées), et une fois libérée, la ligne ne
      correspond plus au prédicat — un second appel ne la retouche pas.
    - **Idempotent** : rejouer cette fonction après qu'un bail a déjà été
      libéré ne produit aucun changement supplémentaire sur cette ligne
      (elle n'apparaît simplement plus dans le résultat).
    - **Aucune progression silencieuse d'état** : seuls
      ``claimed_by``/``lease_token``/``lease_expires_at`` sont réinitialisés
      — ``resource_state`` n'est **jamais** modifié par cette primitive.
      Toute décision de transition (ex. vers ``FAILED`` après un bail perdu)
      relève de ``cas_transition``, appelée séparément par l'appelant.
    - Verrou : ``FOR UPDATE SKIP LOCKED`` dans la CTE — deux appels
      concurrents ne libèrent jamais deux fois le même bail et ne se
      bloquent jamais l'un l'autre.

    Ne committe pas la transaction : responsabilité de l'appelant.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            WITH expired AS (
                SELECT resource_id, claimed_by, lease_token
                FROM ingestion_control.resources
                WHERE lease_token IS NOT NULL AND lease_expires_at < now()
                ORDER BY lease_expires_at
                LIMIT %s
                FOR UPDATE SKIP LOCKED
            )
            UPDATE ingestion_control.resources AS r
            SET claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL, updated_at = now()
            FROM expired AS e
            WHERE r.resource_id = e.resource_id
            RETURNING r.resource_id, e.claimed_by, e.lease_token
            """,
            (limit,),
        )
        rows = cur.fetchall()

    return [
        ReapedLease(resource_id=resource_id, previous_owner=owner, previous_lease_token=token)
        for resource_id, owner, token in rows
    ]


__all__ = ["ReapedLease", "reap_expired_leases"]
