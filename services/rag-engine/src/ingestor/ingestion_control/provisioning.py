"""Création de run/resource/candidate/artifact — glue nécessaire au
scheduler/worker (LOT44e, étendu LOT44f pour la reprise multi-claims).

Nouveau fichier additif : n'introduit aucune notion absente des migrations
001/002/003 (``ingestion_runs``, ``resources``, ``resource_candidates``,
``artifacts``) — seulement des primitives Python pour insérer/relire des
lignes déjà décrites par le schéma LOT44b, jusqu'ici faites uniquement à la
main par les fixtures de test (candidates/artifacts n'étaient même pas
écrits du tout par le worker avant LOT44f — dette documentée par l'audit
go-live). Aucun fichier existant de LOT44b modifié.

Ne décide jamais du contenu métier (scope, profile_version) : reçoit tout
en paramètre, n'invente rien, ne devine aucune valeur par défaut.
"""
from __future__ import annotations

from uuid import UUID, uuid4

import psycopg
from nexus_contracts.ingestion import ArtifactRecord, ResourceCandidate, ResourceScope
from nexus_contracts.resource_state import ResourceState
from psycopg.types.json import Jsonb

try:
    from ingestor.resource_identity_freeze import (
        RESOURCE_REGISTRY_ISSUANCE_REQUIRED,
        ResourceIdentityFreezeError,
    )
except ImportError:
    from resource_identity_freeze import (
        RESOURCE_REGISTRY_ISSUANCE_REQUIRED,
        ResourceIdentityFreezeError,
    )


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
    resource_id: UUID | None = None,
    resource_registry_issuance_required: bool = False,
) -> UUID:
    """Insère une ligne ``resources`` à l'état initial ``DISCOVERED``
    (défaut de la migration 001, jamais réécrit ici)."""
    if resource_id is None:
        if resource_registry_issuance_required:
            raise ResourceIdentityFreezeError(RESOURCE_REGISTRY_ISSUANCE_REQUIRED)
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


def get_resource_state(conn: psycopg.Connection, *, resource_id: UUID) -> tuple[ResourceState, int] | None:
    """Lit l'état courant et la version d'une ressource — ``None`` si elle
    n'existe pas. Primitive de lecture LOT44f utilisée par le worker pour
    décider, à la reprise d'un job déjà associé à une ressource, quelles
    étapes ont déjà été franchies durablement (cf. ``runner.py``)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT resource_state, state_version FROM ingestion_control.resources "
            "WHERE resource_id = %s",
            (resource_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return ResourceState(row[0]), row[1]


def persist_resource_candidate(conn: psycopg.Connection, *, candidate: ResourceCandidate) -> None:
    """Persiste un ``ResourceCandidate`` (LOT44a) — colonnes typées de la
    migration 002 pour les contraintes/index existants, ``payload`` complet
    (migration 006) pour une reconstruction fidèle à la reprise.

    ``ON CONFLICT (resource_id, run_id) DO NOTHING`` (contrainte
    ``resource_candidates_resource_run_unique``, migration 002) : idempotent
    — un Scout rejoué pour la même ressource/run après reprise n'échoue
    jamais et ne duplique jamais la ligne."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.resource_candidates
                (candidate_id, resource_id, run_id, dedup_key, source_url,
                 canonical_url, domain, proposed_type_doc, discovered_at, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (resource_id, run_id) DO NOTHING
            """,
            (
                candidate.candidate_id, candidate.resource_id, candidate.run_id,
                candidate.dedup_key, candidate.source_url, candidate.canonical_url,
                candidate.domain, candidate.proposed_type_doc, candidate.discovered_at,
                Jsonb(candidate.model_dump(mode="json")),
            ),
        )


def find_resource_candidate(
    conn: psycopg.Connection, *, resource_id: UUID, run_id: UUID
) -> ResourceCandidate | None:
    """Relit le ``ResourceCandidate`` persisté pour ``(resource_id,
    run_id)`` — reconstruction fidèle depuis ``payload`` (migration 006),
    jamais depuis les seules colonnes typées (incomplètes vis-à-vis du
    contrat)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM ingestion_control.resource_candidates "
            "WHERE resource_id = %s AND run_id = %s",
            (resource_id, run_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return ResourceCandidate.model_validate(row[0])


def persist_artifact(conn: psycopg.Connection, *, artifact: ArtifactRecord) -> None:
    """Persiste un ``ArtifactRecord`` (LOT44a) — mêmes principes que
    ``persist_resource_candidate``. ``ON CONFLICT (resource_id, sha256) DO
    NOTHING`` (contrainte ``artifacts_resource_sha256_unique``, migration
    002) : un Fetcher rejoué produisant le même contenu pour la même
    ressource n'échoue jamais et ne duplique jamais la ligne."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.artifacts
                (artifact_id, resource_id, run_id, sha256, size_bytes,
                 mime_declared, mime_detected, original_url, final_url,
                 collected_at, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (resource_id, sha256) DO NOTHING
            """,
            (
                artifact.artifact_id, artifact.resource_id, artifact.run_id,
                artifact.sha256, artifact.size_bytes, artifact.mime_declared,
                artifact.mime_detected, artifact.original_url, artifact.final_url,
                artifact.collected_at, Jsonb(artifact.model_dump(mode="json")),
            ),
        )


def find_latest_artifact(conn: psycopg.Connection, *, resource_id: UUID) -> ArtifactRecord | None:
    """Relit le dernier ``ArtifactRecord`` persisté pour cette ressource
    (``collected_at`` le plus récent) — reconstruction fidèle depuis
    ``payload``. ``None`` si aucun artefact n'a encore été persisté."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT payload FROM ingestion_control.artifacts "
            "WHERE resource_id = %s ORDER BY collected_at DESC LIMIT 1",
            (resource_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    return ArtifactRecord.model_validate(row[0])


__all__ = [
    "create_ingestion_run",
    "create_resource",
    "find_latest_artifact",
    "find_resource_candidate",
    "get_resource_state",
    "persist_artifact",
    "persist_resource_candidate",
]
