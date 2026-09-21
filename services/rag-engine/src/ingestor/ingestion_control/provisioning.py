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

from typing import Any, Protocol
from uuid import UUID, uuid4

import psycopg
from nexus_contracts.ingestion import (
    ArtifactRecord,
    ResourceCandidate,
    ResourceScope,
    SealedReleaseArtifactRecord,
)
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


#: Les deux origines déclarées par la migration 014. Une ressource vient
#: soit de la découverte web, soit d'une release scellée — jamais des deux,
#: et jamais d'une troisième origine qu'un appelant inventerait.
RESOURCE_PIPELINE = "resource_pipeline"
SEALED_RELEASE_PIPELINE = "sealed_release_pipeline"


class SealedReleaseRowError(RuntimeError):
    """Une ligne de release scellée a été lue par une primitive qui ne la
    comprend pas — refus explicite plutôt qu'une reconstruction fausse."""


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
    pipeline_kind: str = RESOURCE_PIPELINE,
) -> UUID:
    """Insère une ligne ``resources`` à l'état initial ``DISCOVERED``
    (défaut de la migration 001, jamais réécrit ici).

    ``pipeline_kind`` (migration 014) déclare l'origine de la ressource. Le
    défaut ``resource_pipeline`` est exactement le défaut de la colonne :
    tout appelant existant écrit la même ligne qu'avant ce paramètre."""
    if resource_id is None:
        if resource_registry_issuance_required:
            raise ResourceIdentityFreezeError(RESOURCE_REGISTRY_ISSUANCE_REQUIRED)
        resource_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.resources
                (resource_id, run_id, dedup_key, tenant, collection, niveau, voie,
                 matiere, candidat, audience, visibility, school_year,
                 programme_version, pipeline_kind)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING resource_id
            """,
            (
                resource_id, run_id, dedup_key, scope.tenant, scope.collection,
                scope.niveau, scope.voie, scope.matiere, scope.candidat,
                scope.audience, scope.visibility, scope.school_year,
                scope.programme_version, pipeline_kind,
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
            "SELECT payload, pipeline_kind FROM ingestion_control.resource_candidates "
            "WHERE resource_id = %s AND run_id = %s",
            (resource_id, run_id),
        )
        row = cur.fetchone()
    if row is None:
        return None
    # Une ligne de release scellée ne porte aucun ``canonical_url`` et ne
    # validera jamais comme ``ResourceCandidate`` : le dire est la seule
    # réponse juste — la reconstruire « au mieux » inventerait l'identité
    # documentaire que la release n'a pas.
    if row[1] == SEALED_RELEASE_PIPELINE:
        raise SealedReleaseRowError(
            f"candidate {resource_id}/{run_id} comes from {SEALED_RELEASE_PIPELINE} "
            "and is not a ResourceCandidate — it carries no canonical_url"
        )
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


_SEALED_PAYLOAD_REQUIS = (
    "release_id",
    "release_manifest_sha256",
    "content_sha256",
    "provenance_artifact_url",
    "chunk_count",
)


class SealedRightsResolver(Protocol):
    """Ce que la branche batch exige pour pouvoir lire un artefact scellé.

    Un lecteur de base de données n'a pas autorité pour dire quels droits
    couvrent un contenu : la résolution appartient au registre gouverné. La
    branche batch réclame donc son résolveur, et refuse sans lui."""

    def resolve(self, *, content_sha256: str) -> tuple[str, str, str]:
        """Rend ``(rights, decision_id, registry_sha256)`` ou lève."""


def _read_sealed_release_artifact(
    payload: dict[str, Any],
    *,
    resource_id: UUID,
    artifact_id: UUID,
    run_id: UUID,
    sha256: str,
    size_bytes: int,
    scope: ResourceScope,
    rights_resolver: SealedRightsResolver | None,
) -> SealedReleaseArtifactRecord:
    """Compose le record batch depuis le payload scellé et les colonnes.

    Ce qui manque n'est jamais complété : un payload qui ne porte pas ses
    références de release est refusé, il ne devient pas un record partiel.
    """
    if rights_resolver is None:
        raise SealedReleaseRowError(
            f"sealed artifact {artifact_id} cannot be read without a rights "
            "resolver — rights are resolved by the governed registry, never "
            "inferred from a payload, a domain or a PII status"
        )
    manquants = [cle for cle in _SEALED_PAYLOAD_REQUIS if not payload.get(cle)]
    if manquants:
        raise SealedReleaseRowError(
            f"sealed artifact {artifact_id} carries no {', '.join(manquants)} — "
            "a sealed payload without its release references is refused, never "
            "completed with a convenience value"
        )
    declare = payload.get("pipeline_kind")
    if declare is not None and declare != SEALED_RELEASE_PIPELINE:
        raise SealedReleaseRowError(
            f"sealed artifact {artifact_id}: the payload declares pipeline_kind="
            f"{declare!r} while the resource is {SEALED_RELEASE_PIPELINE!r}"
        )
    if payload["content_sha256"] != sha256:
        raise SealedReleaseRowError(
            f"sealed artifact {artifact_id}: payload content_sha256 "
            f"{payload['content_sha256']!r} differs from the typed sha256 column "
            f"{sha256!r} — the reader refuses a contradiction between its sources"
        )
    if payload.get("collection") and payload["collection"] != scope.collection:
        raise SealedReleaseRowError(
            f"sealed artifact {artifact_id}: payload collection "
            f"{payload['collection']!r} differs from the resource scope "
            f"{scope.collection!r}"
        )
    rights, decision_id, registry_sha256 = rights_resolver.resolve(
        content_sha256=sha256
    )
    return SealedReleaseArtifactRecord(
        pipeline_kind=SEALED_RELEASE_PIPELINE,
        artifact_id=artifact_id,
        resource_id=resource_id,
        run_id=run_id,
        scope=scope,
        sha256=sha256,
        size_bytes=size_bytes,
        mime_declared="application/pdf",
        content_type_detected=None,
        release_id=str(payload["release_id"]),
        release_manifest_sha256=str(payload["release_manifest_sha256"]),
        content_sha256=sha256,
        provenance_artifact_url=str(payload["provenance_artifact_url"]),
        rights_status=rights,
        rights_decision_id=decision_id,
        rights_registry_sha256=registry_sha256,
        pages_count=int(payload["page_count"]) if payload.get("page_count") else 1,
        chunk_count=int(payload["chunk_count"]),
        title=payload.get("title"),
        type_doc=payload.get("type_doc"),
    )


def find_latest_artifact(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    rights_resolver: SealedRightsResolver | None = None,
) -> ArtifactRecord | SealedReleaseArtifactRecord | None:
    """Relit le dernier artefact persisté, dans la représentation de SON pipeline.

    Le modèle est choisi par le **discriminateur durable** — la colonne
    ``resources.pipeline_kind``, gouvernée et écrite à l'ingestion — jamais
    en essayant plusieurs validations jusqu'à ce qu'une accepte. Un payload
    de découverte incomplet échoue comme payload de découverte ; il n'est
    pas requalifié en batch parce qu'il lui manque des champs.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT a.payload, a.artifact_id, a.run_id, a.sha256, a.size_bytes,"
            "       r.pipeline_kind, r.tenant, r.collection, r.niveau, r.voie,"
            "       r.matiere, r.candidat, r.audience, r.visibility,"
            "       r.school_year, r.programme_version"
            "  FROM ingestion_control.artifacts a"
            "  JOIN ingestion_control.resources r USING (resource_id)"
            " WHERE a.resource_id = %s"
            " ORDER BY a.collected_at DESC LIMIT 1",
            (resource_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    (payload, artifact_id, run_id, sha256, size_bytes, pipeline_kind,
     tenant, collection, niveau, voie, matiere, candidat, audience,
     visibility, school_year, programme_version) = row

    if pipeline_kind == RESOURCE_PIPELINE:
        record: ArtifactRecord | SealedReleaseArtifactRecord = (
            ArtifactRecord.model_validate(payload)
        )
    elif pipeline_kind == SEALED_RELEASE_PIPELINE:
        record = _read_sealed_release_artifact(
            payload,
            resource_id=resource_id,
            artifact_id=artifact_id,
            run_id=run_id,
            sha256=sha256,
            size_bytes=size_bytes,
            scope=ResourceScope(
                tenant=tenant, collection=collection, niveau=niveau, voie=voie,
                matiere=matiere, candidat=candidat, audience=audience,
                visibility=visibility, school_year=school_year,
                programme_version=programme_version,
            ),
            rights_resolver=rights_resolver,
        )
    else:
        raise SealedReleaseRowError(
            f"resource {resource_id} carries the unknown pipeline_kind "
            f"{pipeline_kind!r} — the reader refuses rather than guessing "
            "which representation applies"
        )

    # Les colonnes typées font autorité sur le payload : elles sont
    # contraintes par le schéma, lui ne l'est pas. Une contradiction est un
    # refus, jamais le choix de la valeur qui permet de construire l'objet.
    for champ, en_base in (
        ("artifact_id", artifact_id),
        ("resource_id", resource_id),
        ("run_id", run_id),
        ("sha256", sha256),
    ):
        porte = getattr(record, champ)
        if str(porte) != str(en_base):
            raise SealedReleaseRowError(
                f"artifact {artifact_id}: the record declares {champ}={porte!r} "
                f"while the typed column holds {en_base!r} — the reader refuses "
                "a contradiction between its sources"
            )
    return record


def persist_sealed_release_candidate(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    run_id: UUID,
    dedup_key: str,
    source_url: str,
    domain: str,
    proposed_type_doc: str,
    payload: dict[str, object],
    candidate_id: UUID | None = None,
) -> UUID:
    """Persiste un candidat issu d'une release scellée — sans URL canonique.

    Aucun paramètre ``canonical_url`` n'existe ici, et l'INSERT écrit
    ``NULL`` littéralement : un appelant ne peut donc pas en fournir une,
    même par erreur. La contrainte
    ``resource_candidates_canonical_url_by_pipeline`` (migration 014) fait
    respecter la même règle côté base, dans l'autre sens — elle REFUSE une
    URL canonique sur cette origine.

    ``source_url`` reste ce qu'il a toujours été : la provenance observée,
    jamais promue en identité du document.

    ``payload`` porte les faits de la release (digests, placement,
    autorisation) et se décrit lui-même par ``protocol_version`` — il n'est
    jamais relu comme un ``ResourceCandidate`` (cf.
    ``find_resource_candidate``, qui refuse explicitement ces lignes)."""
    candidate = candidate_id or uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.resource_candidates
                (candidate_id, resource_id, run_id, dedup_key, source_url,
                 canonical_url, domain, proposed_type_doc, pipeline_kind, payload)
            VALUES (%s, %s, %s, %s, %s, NULL, %s, %s, %s, %s)
            ON CONFLICT (resource_id, run_id) DO NOTHING
            """,
            (
                candidate, resource_id, run_id, dedup_key, source_url,
                domain, proposed_type_doc, SEALED_RELEASE_PIPELINE, Jsonb(payload),
            ),
        )
    return candidate


def persist_sealed_release_artifact(
    conn: psycopg.Connection,
    *,
    resource_id: UUID,
    run_id: UUID,
    sha256: str,
    size_bytes: int,
    mime_declared: str,
    mime_detected: str,
    provenance_url: str,
    payload: dict[str, object],
    artifact_id: UUID | None = None,
) -> UUID:
    """Persiste l'artefact d'une release scellée, lu dans le store vérifié.

    ``original_url`` et ``final_url`` reçoivent la MÊME valeur, et c'est un
    fait, pas un remplissage : aucune requête n'a été émise ici, donc
    aucune redirection n'a été suivie. Les octets ne viennent pas du
    réseau mais du store transféré et vérifié par digest.

    ``artifacts`` n'a pas de colonne ``pipeline_kind`` : l'origine se lit
    sur la ressource et sur le candidat, qui la portent."""
    artifact = artifact_id or uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO ingestion_control.artifacts
                (artifact_id, resource_id, run_id, sha256, size_bytes,
                 mime_declared, mime_detected, original_url, final_url, payload)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (resource_id, sha256) DO NOTHING
            """,
            (
                artifact, resource_id, run_id, sha256, size_bytes,
                mime_declared, mime_detected, provenance_url, provenance_url,
                Jsonb(payload),
            ),
        )
    return artifact


__all__ = [
    "RESOURCE_PIPELINE",
    "SEALED_RELEASE_PIPELINE",
    "SealedReleaseRowError",
    "create_ingestion_run",
    "create_resource",
    "find_latest_artifact",
    "find_resource_candidate",
    "get_resource_state",
    "persist_artifact",
    "persist_resource_candidate",
    "persist_sealed_release_artifact",
    "persist_sealed_release_candidate",
]
