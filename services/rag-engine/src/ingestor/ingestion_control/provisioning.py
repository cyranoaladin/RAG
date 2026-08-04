"""Création de run/resource — glue nécessaire au scheduler/worker (LOT44e).

Nouveau fichier additif : n'introduit aucune notion absente des migrations
001/003 (``ingestion_runs``, ``resources``) — seulement des primitives
Python pour insérer des lignes déjà décrites par le schéma LOT44b, jusqu'ici
faites uniquement à la main par les fixtures de test. Aucun fichier
existant de LOT44b modifié.

Ne décide jamais du contenu métier (scope, profile_version) : reçoit tout
en paramètre, n'invente rien, ne devine aucune valeur par défaut.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
from nexus_contracts.ingestion import ResourceScope


def create_ingestion_run(
    conn: psycopg.Connection,
    *,
    scope: ResourceScope,
    profile_version: str,
    trigger: str,
) -> UUID:
    """Insère une ligne ``ingestion_runs`` — aucun statut/horodatage deviné
    au-delà des défauts déjà portés par la migration 001 (``status =
    'planned'``, ``mode = 'auto_stage'``)."""
    run_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.ingestion_runs
                (run_id, tenant, collection, niveau, voie, matiere, candidat, audience,
                 visibility, school_year, programme_version, profile_version, trigger)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING run_id
            """,
            (
                run_id, scope.tenant, scope.collection, scope.niveau, scope.voie,
                scope.matiere, scope.candidat, scope.audience, scope.visibility,
                scope.school_year, scope.programme_version, profile_version, trigger,
            ),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - RETURNING garantit une ligne
            raise RuntimeError("INSERT ... RETURNING run_id produced no row")
    return run_id


def create_resource(
    conn: psycopg.Connection,
    *,
    run_id: UUID,
    dedup_key: str,
    scope: ResourceScope,
) -> UUID:
    """Insère une ligne ``resources`` à l'état initial ``DISCOVERED``
    (défaut de la migration 001, jamais réécrit ici)."""
    resource_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.resources
                (resource_id, run_id, dedup_key, tenant, collection, niveau, voie,
                 matiere, candidat, audience, visibility, school_year, programme_version)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING resource_id
            """,
            (
                resource_id, run_id, dedup_key, scope.tenant, scope.collection,
                scope.niveau, scope.voie, scope.matiere, scope.candidat,
                scope.audience, scope.visibility, scope.school_year, scope.programme_version,
            ),
        )
        row = cur.fetchone()
        if row is None:  # pragma: no cover - RETURNING garantit une ligne
            raise RuntimeError("INSERT ... RETURNING resource_id produced no row")
    return resource_id


__all__ = ["create_ingestion_run", "create_resource"]
