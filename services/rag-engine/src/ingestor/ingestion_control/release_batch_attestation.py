"""Attestation de publication d'une release scellée — protocole LOT42-RELEASE-BATCH-V1.

Ce module produit l'artefact de revue **depuis les faits mesurés**, jamais
depuis des arguments d'opérateur : les comptes viennent de la base, les
digests du catalogue vérifié, les autorisations des lignes réellement
enregistrées. Un opérateur ne peut pas déclarer ``quality_passed`` ni
choisir un compteur.

Il n'approuve rien et ne publie rien : il prépare ce qu'un humain relira.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from nexus_contracts.authority_artifacts import (
    ReleaseBatchExpectedCounts,
    ReleaseBatchPlacementEvidence,
    ReleaseBatchPublicationReviewArtifact,
)

BATCH_PROTOCOL = "LOT42-RELEASE-BATCH-V1"
BATCH_DECISION = "AUTHORIZE_SEALED_RELEASE_PUBLICATION"
SEALED_RELEASE_PIPELINE = "sealed_release_pipeline"


class ReleaseBatchAttestationError(RuntimeError):
    """Refus explicite — jamais un contournement."""


@dataclass(frozen=True)
class MeasuredReleaseBatchFacts:
    """Ce que la BASE dit du périmètre, mesuré et non déclaré."""

    release_id: str
    release_manifest_sha256: str
    artifacts_release_sha256: str
    candidate_inventory_sha256: str
    artifact_transfer_manifest_sha256: str
    collections: tuple[str, ...]
    scope_authorization_ids: tuple[str, ...]
    subjects: int
    unique_artifacts: int
    placements: int
    unique_chunks: int
    provenance_source_url_count: int
    resource_ids: tuple[UUID, ...]
    #: ``resource_id -> (artifact_id, content_sha256, collection, authorization)``
    par_ressource: Mapping[UUID, tuple[UUID, str, str, str]]


def _une_valeur(valeurs: set[str], *, champ: str) -> str:
    """Une release n'a qu'une identité. Plusieurs valeurs = refus."""
    if len(valeurs) != 1:
        raise ReleaseBatchAttestationError(
            f"the sealed rows declare {len(valeurs)} distinct {champ} "
            f"({sorted(valeurs)!r}) — a release has exactly one"
        )
    return valeurs.pop()


def measure_release_batch_facts(
    conn: psycopg.Connection,
    *,
    release_id: str,
) -> MeasuredReleaseBatchFacts:
    """Mesure le périmètre depuis les lignes scellées de CE release_id.

    Rien n'est passé en argument hormis l'identité de la release : les
    comptes, les collections et les autorisations sont lus.
    """
    lignes = conn.execute(
        "SELECT r.resource_id, a.artifact_id, a.sha256, r.collection, a.payload"
        "  FROM ingestion_control.resources r"
        "  JOIN ingestion_control.artifacts a USING (resource_id)"
        " WHERE r.pipeline_kind = %s"
        "   AND a.payload->>'release_id' = %s"
        " ORDER BY r.resource_id",
        (SEALED_RELEASE_PIPELINE, release_id),
    ).fetchall()
    if not lignes:
        raise ReleaseBatchAttestationError(
            f"no sealed row belongs to release {release_id!r} — there is "
            "nothing to attest"
        )

    collections: set[str] = set()
    autorisations: set[str] = set()
    manifestes: set[str] = set()
    artefacts_release: set[str] = set()
    inventaires: set[str] = set()
    transferts: set[str] = set()
    contenus: set[str] = set()
    provenances: set[str] = set()
    chunks_par_contenu: dict[str, int] = {}
    par_ressource: dict[UUID, tuple[UUID, str, str, str]] = {}

    for resource_id, artifact_id, sha256, collection, payload in lignes:
        manquants = [
            cle
            for cle in (
                "release_manifest_sha256",
                "artifacts_release_sha256",
                "candidate_inventory_sha256",
                "artifact_transfer_manifest_sha256",
                "scope_authorization_id",
                "provenance_artifact_url",
                "chunk_count",
                "review_status",
                "placement_status",
                "currentness",
            )
            if payload.get(cle) in (None, "")
        ]
        if manquants:
            raise ReleaseBatchAttestationError(
                f"sealed row {resource_id} carries no {', '.join(manquants)}"
            )
        # Les trois déclarations de placement sont ce qui rend une revue
        # unique défendable. Une seule divergence et le lot n'est plus
        # homogène : refus, jamais une moyenne.
        for champ, attendu in (
            ("review_status", "reviewed"),
            ("placement_status", "active"),
            ("currentness", "current"),
        ):
            if payload[champ] != attendu:
                raise ReleaseBatchAttestationError(
                    f"sealed row {resource_id} declares {champ}="
                    f"{payload[champ]!r}, expected {attendu!r} — the batch is "
                    "not homogeneous and cannot be covered by one review"
                )
        collections.add(collection)
        autorisations.add(str(payload["scope_authorization_id"]))
        manifestes.add(str(payload["release_manifest_sha256"]))
        artefacts_release.add(str(payload["artifacts_release_sha256"]))
        inventaires.add(str(payload["candidate_inventory_sha256"]))
        transferts.add(str(payload["artifact_transfer_manifest_sha256"]))
        contenus.add(sha256)
        provenances.add(str(payload["provenance_artifact_url"]))
        chunks_par_contenu.setdefault(sha256, int(payload["chunk_count"]))
        par_ressource[resource_id] = (
            artifact_id, sha256, collection, str(payload["scope_authorization_id"])
        )

    return MeasuredReleaseBatchFacts(
        release_id=release_id,
        release_manifest_sha256=_une_valeur(manifestes, champ="release_manifest_sha256"),
        artifacts_release_sha256=_une_valeur(
            artefacts_release, champ="artifacts_release_sha256"
        ),
        candidate_inventory_sha256=_une_valeur(
            inventaires, champ="candidate_inventory_sha256"
        ),
        artifact_transfer_manifest_sha256=_une_valeur(
            transferts, champ="artifact_transfer_manifest_sha256"
        ),
        collections=tuple(sorted(collections)),
        scope_authorization_ids=tuple(sorted(autorisations)),
        subjects=len(collections),
        unique_artifacts=len(contenus),
        placements=len(lignes),
        # Les chunks DISTINCTS : sommés sur les artefacts uniques, jamais sur
        # les placements — un document placé deux fois ne double pas ses
        # identités de chunks.
        unique_chunks=sum(chunks_par_contenu.values()),
        provenance_source_url_count=len(provenances),
        resource_ids=tuple(par_ressource),
        par_ressource=par_ressource,
    )


def require_facts_match_catalog(
    facts: MeasuredReleaseBatchFacts, catalog: Any
) -> None:
    """Les faits mesurés décrivent-ils LE catalogue vérifié ?

    Un digest bien formé mais étranger à la release attendue est refusé
    ici : la forme ne suffit jamais à établir l'appartenance.
    """
    if catalog.release_id != facts.release_id:
        raise ReleaseBatchAttestationError(
            f"the verified catalogue describes release {catalog.release_id!r}, "
            f"not {facts.release_id!r}"
        )
    if catalog.release_manifest_sha256 != facts.release_manifest_sha256:
        raise ReleaseBatchAttestationError(
            "the sealed rows name release manifest "
            f"{facts.release_manifest_sha256[:16]}…, the verified catalogue "
            f"{catalog.release_manifest_sha256[:16]}…"
        )
    if catalog.registry_sha256 != facts.artifacts_release_sha256:
        raise ReleaseBatchAttestationError(
            "the sealed rows name artifact registry "
            f"{facts.artifacts_release_sha256[:16]}…, the verified catalogue "
            f"{catalog.registry_sha256[:16]}…"
        )
    if len(catalog.artifacts) != facts.unique_artifacts:
        raise ReleaseBatchAttestationError(
            f"the catalogue carries {len(catalog.artifacts)} artifacts, the "
            f"sealed rows {facts.unique_artifacts}"
        )
    inconnus = [
        sha for _, (_, sha, _, _) in facts.par_ressource.items()
        if sha not in catalog.artifacts
    ]
    if inconnus:
        raise ReleaseBatchAttestationError(
            f"{len(inconnus)} sealed content(s) are absent from the verified "
            f"catalogue (first: {inconnus[0][:12]}…)"
        )


def build_release_batch_review_artifact(
    *,
    review_id: str,
    facts: MeasuredReleaseBatchFacts,
    valid_from: datetime,
    valid_until: datetime,
) -> ReleaseBatchPublicationReviewArtifact:
    """Construit l'artefact **entièrement** depuis les faits mesurés."""
    return ReleaseBatchPublicationReviewArtifact(
        protocol_version=BATCH_PROTOCOL,
        review_id=review_id,
        decision=BATCH_DECISION,
        release_id=facts.release_id,
        release_manifest_sha256=facts.release_manifest_sha256,
        artifacts_release_sha256=facts.artifacts_release_sha256,
        candidate_inventory_sha256=facts.candidate_inventory_sha256,
        artifact_transfer_manifest_sha256=facts.artifact_transfer_manifest_sha256,
        expected_counts=ReleaseBatchExpectedCounts(
            subjects=facts.subjects,
            unique_artifacts=facts.unique_artifacts,
            placements=facts.placements,
            unique_chunks=facts.unique_chunks,
        ),
        collections=facts.collections,
        placement_evidence=ReleaseBatchPlacementEvidence(
            review_status="reviewed",
            placement_status="active",
            currentness="current",
        ),
        scope_authorization_ids=facts.scope_authorization_ids,
        provenance_source_url_count=facts.provenance_source_url_count,
        provenance_note=(
            "Provenance documentaire scellee : "
            f"{facts.provenance_source_url_count} URL(s) de provenance pour "
            f"{facts.unique_artifacts} artefacts. Ce champ dit d'ou le corpus "
            "vient ; il ne designe pas une ressource a recuperer et n'est pas "
            "une URL canonique."
        ),
        valid_from=valid_from,
        valid_until=valid_until,
    )


def canonical_bytes(
    artifact: ReleaseBatchPublicationReviewArtifact,
) -> bytes:
    """Délègue au contrat : la forme canonique appartient au modèle.

    En réimplémenter une seconde ici produirait des octets voisins mais
    différents, et la revue humaine ne serait plus liée au contenu relu.
    """
    return artifact.canonical_bytes()


def artifact_digest(artifact: ReleaseBatchPublicationReviewArtifact) -> str:
    return artifact.digest()


def require_artifact_matches_facts(
    artifact: ReleaseBatchPublicationReviewArtifact,
    facts: MeasuredReleaseBatchFacts,
) -> None:
    """L'artefact APPROUVÉ décrit-il encore les faits persistés ?

    C'est ce qui détecte une modification survenue **entre** la proposition
    et l'enregistrement. Comparer les types SQL ne le ferait pas.
    """
    ecarts: list[str] = []
    for champ, attendu, observe in (
        ("release_id", facts.release_id, artifact.release_id),
        ("release_manifest_sha256", facts.release_manifest_sha256,
         artifact.release_manifest_sha256),
        ("artifacts_release_sha256", facts.artifacts_release_sha256,
         artifact.artifacts_release_sha256),
        ("candidate_inventory_sha256", facts.candidate_inventory_sha256,
         artifact.candidate_inventory_sha256),
        ("artifact_transfer_manifest_sha256",
         facts.artifact_transfer_manifest_sha256,
         artifact.artifact_transfer_manifest_sha256),
        ("subjects", facts.subjects, artifact.expected_counts.subjects),
        ("unique_artifacts", facts.unique_artifacts,
         artifact.expected_counts.unique_artifacts),
        ("placements", facts.placements, artifact.expected_counts.placements),
        ("unique_chunks", facts.unique_chunks,
         artifact.expected_counts.unique_chunks),
        ("collections", facts.collections, artifact.collections),
        ("scope_authorization_ids", facts.scope_authorization_ids,
         artifact.scope_authorization_ids),
        ("provenance_source_url_count", facts.provenance_source_url_count,
         artifact.provenance_source_url_count),
    ):
        if attendu != observe:
            ecarts.append(f"{champ}: reviewed={observe!r} persisted={attendu!r}")
    if ecarts:
        raise ReleaseBatchAttestationError(
            "the approved review no longer describes the persisted facts — "
            "something changed between proposal and recording: "
            + "; ".join(ecarts)
        )


def require_resource_is_covered(
    artifact: ReleaseBatchPublicationReviewArtifact,
    facts: MeasuredReleaseBatchFacts,
    *,
    resource_id: UUID,
) -> None:
    """Une revue unique n'autorise pas un ensemble extensible.

    L'appartenance se vérifie sur les faits mesurés du périmètre, pas sur la
    seule présence d'un index SQL.
    """
    if resource_id not in facts.par_ressource:
        raise ReleaseBatchAttestationError(
            f"resource {resource_id} is not part of release "
            f"{facts.release_id!r} — the batch review does not cover it"
        )
    _, _, collection, authorization = facts.par_ressource[resource_id]
    if collection not in artifact.collections:
        raise ReleaseBatchAttestationError(
            f"resource {resource_id} belongs to collection {collection!r}, "
            "which the approved review does not cover"
        )
    if authorization not in artifact.scope_authorization_ids:
        raise ReleaseBatchAttestationError(
            f"resource {resource_id} names authorization {authorization!r}, "
            "which the approved review does not cover"
        )


__all__ = [
    "BATCH_DECISION",
    "BATCH_PROTOCOL",
    "MeasuredReleaseBatchFacts",
    "ReleaseBatchAttestationError",
    "artifact_digest",
    "build_release_batch_review_artifact",
    "canonical_bytes",
    "measure_release_batch_facts",
    "require_artifact_matches_facts",
    "require_facts_match_catalog",
    "require_resource_is_covered",
]
