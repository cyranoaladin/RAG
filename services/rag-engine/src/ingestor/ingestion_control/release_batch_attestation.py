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
from typing import Any, cast
from uuid import UUID

import psycopg
from nexus_contracts.authority_artifacts import (
    ReleaseBatchExpectedCounts,
    ReleaseBatchPlacementEvidence,
    ReleaseBatchPublicationReviewArtifact,
)

from ingestor.ingestion_control.sealed_release_adoption import (
    load_adopted_rows,
    successor_identity_schema_available,
)

BATCH_PROTOCOL = "LOT42-RELEASE-BATCH-V1"
#: Les actualités qu'une revue batch peut couvrir (ADR-0059).
ACTUALITES_REVISABLES = frozenset({"current", "official_snapshot"})
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
    #: L'actualité, homogène, que TOUS les placements déclarent — mesurée,
    #: jamais supposée `current` (ADR-0059).
    currentness: str = "current"
    #: Vrai quand les lignes sont couvertes par ADOPTION (ADR-0059 § 5) et non
    #: acquises sous cette release.
    adopted: bool = False
    #: (collection, content SHA, placement ID, PUBLICATION authorization ID),
    #: read from the control-plane rows, never copied from a release manifest.
    placement_keys: tuple[tuple[str, str, str, str], ...] = ()
    chunk_counts: Mapping[str, int] | None = None


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
    exclude_v2 = (
        "   AND NOT EXISTS ("
        "       SELECT 1 FROM ingestion_control.sealed_release_adoptions ad"
        "        WHERE ad.adoption_version = 'SEALED-RELEASE-ADOPTION-V2'"
        "          AND ad.successor_artifact_id = a.artifact_id"
        "   )"
        if successor_identity_schema_available(conn) else ""
    )
    lignes = conn.execute(
        "SELECT r.resource_id, a.artifact_id, a.sha256, r.collection, a.payload"
        "  FROM ingestion_control.resources r"
        "  JOIN ingestion_control.artifacts a USING (resource_id)"
        " WHERE r.pipeline_kind = %s"
        "   AND a.payload->>'release_id' = %s"
        + exclude_v2 + " ORDER BY r.resource_id",
        (SEALED_RELEASE_PIPELINE, release_id),
    ).fetchall()
    # Un successeur ne possède aucune ligne acquise : il couvre celles de son
    # prédécesseur par adoption. Les deux à la fois ne décrivent pas une
    # release, mais deux.
    adoptees = load_adopted_rows(conn, release_id=release_id)
    if lignes and adoptees:
        raise ReleaseBatchAttestationError(
            f"release {release_id!r} both owns acquired rows and adopts others — "
            "a release is attested either from its own acquisition or from an "
            "adoption, never from a mixture"
        )
    adopted = bool(adoptees)
    if adopted:
        lignes = adoptees
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
    actualites: set[str] = set()
    placement_keys: set[tuple[str, str, str, str]] = set()

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
        ):
            if payload[champ] != attendu:
                raise ReleaseBatchAttestationError(
                    f"sealed row {resource_id} declares {champ}="
                    f"{payload[champ]!r}, expected {attendu!r} — the batch is "
                    "not homogeneous and cannot be covered by one review"
                )
        if payload["currentness"] not in ACTUALITES_REVISABLES:
            raise ReleaseBatchAttestationError(
                f"sealed row {resource_id} declares currentness="
                f"{payload['currentness']!r}, which is never published"
            )
        actualites.add(str(payload["currentness"]))
        collections.add(collection)
        autorisations.add(str(payload["scope_authorization_id"]))
        manifestes.add(str(payload["release_manifest_sha256"]))
        artefacts_release.add(str(payload["artifacts_release_sha256"]))
        inventaires.add(str(payload["candidate_inventory_sha256"]))
        transferts.add(str(payload["artifact_transfer_manifest_sha256"]))
        contenus.add(sha256)
        provenances.add(str(payload["provenance_artifact_url"]))
        placement_id = payload.get("placement_id")
        if not isinstance(placement_id, str) or not placement_id:
            raise ReleaseBatchAttestationError(
                f"sealed row {resource_id} carries no placement_id"
            )
        key = (collection, sha256, placement_id, str(payload["scope_authorization_id"]))
        if key in placement_keys:
            raise ReleaseBatchAttestationError(f"sealed placement {key!r} appears twice")
        placement_keys.add(key)
        if sha256 in chunks_par_contenu and chunks_par_contenu[sha256] != int(payload["chunk_count"]):
            raise ReleaseBatchAttestationError(
                f"sealed content {sha256} has inconsistent chunk_count"
            )
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
        # Une seule actualité pour tout le lot : un mélange n'est pas un état
        # qu'une revue unique puisse couvrir.
        currentness=_une_valeur(actualites, champ="currentness"),
        adopted=adopted,
        placement_keys=tuple(sorted(placement_keys)),
        chunk_counts=dict(sorted(chunks_par_contenu.items())),
    )


def require_public_successor_batch_matches_release(
    facts: MeasuredReleaseBatchFacts,
    release: Any,
    authorization_ids: Mapping[str, str],
) -> None:
    """Require an exact public-text placement bijection before a LOT42 proposal.

    ``release`` is the digest-verified canonical sealed release. Authorization
    IDs are the individually verified LOT41A-V2 publication bindings read from
    the target DB, not operator-supplied fallback IDs.
    """
    for label, measured, expected in (
        ("release_id", facts.release_id, release.release_id),
        ("release manifest", facts.release_manifest_sha256, release.release_manifest_sha256),
        ("artifact registry", facts.artifacts_release_sha256, release.artifacts_release_sha256),
        ("candidate inventory", facts.candidate_inventory_sha256, release.candidate_inventory_sha256),
        ("transfer manifest", facts.artifact_transfer_manifest_sha256,
         release.artifact_transfer_manifest_sha256),
    ):
        if measured != expected:
            raise ReleaseBatchAttestationError(f"public batch {label} differs from release")
    expected_counts = release.expected_counts
    for count_label, count_measured in (
        ("subjects", facts.subjects),
        ("unique_artifacts", facts.unique_artifacts),
        ("placements", facts.placements),
        ("unique_chunks", facts.unique_chunks),
    ):
        if count_measured != expected_counts[count_label]:
            raise ReleaseBatchAttestationError(
                f"public batch {count_label}: DB={count_measured}, release={expected_counts[count_label]}"
            )
    if (
        set(facts.collections) != set(release.collections)
        or set(authorization_ids) != set(release.collections)
        or len(set(authorization_ids.values())) != len(authorization_ids)
        or set(facts.scope_authorization_ids) != set(authorization_ids.values())
    ):
        raise ReleaseBatchAttestationError("public batch collection or authorization population differs")
    if set(release.artifact_media_types) != set(release.artifact_ids) or any(
        media != "text/plain; charset=utf-8" for media in release.artifact_media_types.values()
    ):
        raise ReleaseBatchAttestationError("public batch requires exclusively text derivatives")
    if facts.chunk_counts is None or dict(facts.chunk_counts) != dict(release.artifact_chunk_counts):
        raise ReleaseBatchAttestationError("public batch per-artifact chunk_count differs")
    expected_keys: set[tuple[str, str, str, str]] = set()
    for placement in release.placements:
        if (
            placement.review_status != "reviewed"
            or placement.placement_status != "active"
            or placement.currentness != facts.currentness
            or placement.scope_dimensions.get("visibility") != "public"
            or placement.artifact_id not in release.artifact_ids
        ):
            raise ReleaseBatchAttestationError("public batch placement is not reviewed, active, current, public text")
        expected_keys.add((
            placement.collection, placement.artifact_id, placement.placement_id,
            authorization_ids[placement.collection],
        ))
    if len(expected_keys) != len(release.placements) or tuple(sorted(expected_keys)) != facts.placement_keys:
        raise ReleaseBatchAttestationError("public batch placement identity or scope differs")


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
            currentness=cast(Any, facts.currentness),
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
    octets: bytes = artifact.canonical_bytes()
    return octets


def artifact_digest(artifact: ReleaseBatchPublicationReviewArtifact) -> str:
    digest: str = artifact.digest()
    return digest


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
        # L'actualité approuvée doit être celle des placements persistés : une
        # revue donnée sur « current » ne couvre pas des instantanés (ADR-0059).
        ("currentness", facts.currentness, artifact.placement_evidence.currentness),
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
