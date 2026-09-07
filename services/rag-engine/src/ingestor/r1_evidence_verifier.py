"""R1 evidence verifier: static, read-only proof that an already-exported
``ResourceRegistryBootstrap`` represents exactly the sealed production
release it claims to -- never a database connection, never a mutation.

This is deliberately NOT another exporter and NOT a redesign of the
``ResourceRegistryBootstrap`` contract. It consumes:

  * the bootstrap file an operator already produced with the existing
    ``resource_registry_bootstrap_cli`` command, and
  * the same sealed release chain that command's own
    ``--release-registry-path``/``--release-registry-sha256`` arguments
    already pin (``ingestor.release_readiness.load_release_registry_file``,
    unmodified, reused as-is for its digest-verified parse of the release
    authority),

and proves the bootstrap's semantic placement universe is exactly the
sealed release's -- not merely that per-artifact ``(collection,
content_sha256)`` bindings match, which is the narrower invariant the
exporter's own ``export_resource_registry_bootstrap_inventory`` already
enforces at write time (see ``resource_registry_bootstrap.py``).

Structural note on ``audience``: the sealed release chain (the top-level
``production-profile-gate.release.json`` and every per-subject
``subjects/*.release.json`` it SHA256-pins) carries no ``audience`` field
anywhere in committed data -- confirmed by direct inspection, not assumed.
``BootstrapPlacement.audience`` is a live PostgreSQL column with no sealed,
digest-bound authoritative expected value. The canonical placement tuple
used for equality comparison here is therefore the 10 dimensions the sealed
release DOES carry; ``audience`` is reported as an observed DISTRIBUTION
only (see ``distributions``), never compared against an expectation that
does not exist. This is reported explicitly in the result, not silently
narrowed.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from nexus_contracts import ResourceRegistryBootstrap

from ingestor.release_readiness import (
    ReleaseReadinessError,
    ReleaseRegistryExpectation,
    load_release_registry_file,
)

CANONICAL_PLACEMENT_FIELDS: tuple[str, ...] = (
    "tenant",
    "collection",
    "niveau",
    "voie",
    "matiere",
    "statut_enseignement",
    "candidat",
    "visibility",
    "school_year",
    "programme_version",
)


class R1EvidenceVerifierError(ValueError):
    """The bootstrap or the release authority cannot be evaluated safely."""


@dataclass(frozen=True)
class R1EvidenceReport:
    ready: bool
    gates: dict[str, Any] = field(default_factory=dict)
    distributions: dict[str, dict[str, int]] = field(default_factory=dict)
    collisions: dict[str, Any] = field(default_factory=dict)
    blockers: tuple[str, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "ready": self.ready,
            "gates": self.gates,
            "distributions": self.distributions,
            "collisions": self.collisions,
            "blockers": list(self.blockers),
        }


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_bootstrap(path: Path) -> ResourceRegistryBootstrap:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R1EvidenceVerifierError(f"bootstrap file is not readable JSON: {exc}") from exc
    try:
        return ResourceRegistryBootstrap.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError, deliberately broad at the boundary
        raise R1EvidenceVerifierError(
            f"bootstrap does not validate against the pinned contract: {exc}"
        ) from exc


def _canonical_tuple(values: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(values[field_name] for field_name in CANONICAL_PLACEMENT_FIELDS)


def _expected_placement_tuples(
    registry: ReleaseRegistryExpectation,
) -> tuple[set[tuple[Any, ...]], set[str]]:
    tuples: set[tuple[Any, ...]] = set()
    collections: set[str] = set()
    for manifest in registry.manifests:
        for artifact in manifest.expectation.artifacts:
            for placement in artifact.placements:
                tuples.add(_canonical_tuple(placement))
                collections.add(str(placement["collection"]))
    return tuples, collections


def _actual_placement_tuples(
    bootstrap: ResourceRegistryBootstrap,
) -> tuple[set[tuple[Any, ...]], set[str]]:
    tuples: set[tuple[Any, ...]] = set()
    collections: set[str] = set()
    for resource in bootstrap.resources:
        for placement in resource.placements:
            values = placement.model_dump(mode="json")
            tuples.add(_canonical_tuple(values))
            collections.add(placement.collection)
    return tuples, collections


def _uri_scheme(uri: str) -> str:
    scheme = urlparse(uri).scheme
    return scheme or "(none)"


def _distributions(bootstrap: ResourceRegistryBootstrap) -> dict[str, dict[str, int]]:
    resource_level: dict[str, Counter[str]] = {
        "rights": Counter(),
        "official": Counter(),
        "visibility": Counter(),
        "mime_type": Counter(),
        "type_doc": Counter(),
        "source_kind": Counter(),
        "source_uri_scheme": Counter(),
    }
    placement_level: dict[str, Counter[str]] = {
        "candidat": Counter(),
        "audience": Counter(),
        "niveau": Counter(),
        "voie": Counter(),
        "matiere": Counter(),
        "statut_enseignement": Counter(),
        "programme_version": Counter(),
        "tenant": Counter(),
        "collection": Counter(),
        "school_year": Counter(),
    }
    for resource in bootstrap.resources:
        resource_level["rights"][str(resource.rights)] += 1
        resource_level["official"][str(resource.official)] += 1
        resource_level["mime_type"][resource.mime_type] += 1
        resource_level["type_doc"][str(resource.type_doc)] += 1
        resource_level["source_kind"][resource.source_kind] += 1
        resource_level["source_uri_scheme"][_uri_scheme(resource.source_uri)] += 1
        for placement in resource.placements:
            resource_level["visibility"][placement.visibility] += 1
            placement_level["candidat"][placement.candidat] += 1
            for audience_value in placement.audience:
                placement_level["audience"][str(audience_value)] += 1
            placement_level["niveau"][placement.niveau] += 1
            placement_level["voie"][placement.voie] += 1
            placement_level["matiere"][placement.matiere] += 1
            placement_level["statut_enseignement"][placement.statut_enseignement] += 1
            placement_level["programme_version"][placement.programme_version] += 1
            placement_level["tenant"][placement.tenant] += 1
            placement_level["collection"][placement.collection] += 1
            placement_level["school_year"][placement.school_year] += 1
    merged = {**resource_level, **placement_level}
    return {name: dict(counter) for name, counter in merged.items()}


def _multiplacement_evidence(bootstrap: ResourceRegistryBootstrap) -> dict[str, int]:
    multiplacement_resources = 0
    candidat_heterogeneous = 0
    audience_heterogeneous = 0
    visibility_heterogeneous = 0
    programme_version_heterogeneous = 0
    course_tuple_heterogeneous = 0
    for resource in bootstrap.resources:
        if len(resource.placements) <= 1:
            continue
        multiplacement_resources += 1
        candidats = {p.candidat for p in resource.placements}
        audiences = {tuple(sorted(p.audience)) for p in resource.placements}
        visibilities = {p.visibility for p in resource.placements}
        programme_versions = {p.programme_version for p in resource.placements}
        # "Course tuple" here means the academic-identity dimensions a
        # placement carries on the producer side only -- niveau/voie/matiere/
        # statut_enseignement. This assigns no Nexus courseKey or mapping.
        course_tuples = {
            (p.niveau, p.voie, p.matiere, p.statut_enseignement) for p in resource.placements
        }
        if len(candidats) > 1:
            candidat_heterogeneous += 1
        if len(audiences) > 1:
            audience_heterogeneous += 1
        if len(visibilities) > 1:
            visibility_heterogeneous += 1
        if len(programme_versions) > 1:
            programme_version_heterogeneous += 1
        if len(course_tuples) > 1:
            course_tuple_heterogeneous += 1
    return {
        "MULTIPLACEMENT_RESOURCE_COUNT": multiplacement_resources,
        "RESOURCES_WITH_CANDIDATE_HETEROGENEITY": candidat_heterogeneous,
        "RESOURCES_WITH_AUDIENCE_HETEROGENEITY": audience_heterogeneous,
        "RESOURCES_WITH_VISIBILITY_HETEROGENEITY": visibility_heterogeneous,
        "RESOURCES_WITH_PROGRAMME_VERSION_HETEROGENEITY": programme_version_heterogeneous,
        "RESOURCES_WITH_COURSE_TUPLE_HETEROGENEITY": course_tuple_heterogeneous,
    }


def _collisions(bootstrap: ResourceRegistryBootstrap) -> dict[str, Any]:
    resource_id_versions: dict[str, set[str]] = {}
    chunk_owners: dict[str, set[str]] = {}
    duplicate_identical_placements = 0
    conflicting_same_collection_placements = 0
    for resource in bootstrap.resources:
        resource_id_versions.setdefault(str(resource.resource_id), set()).add(
            str(resource.resource_version_id)
        )
        for chunk in resource.chunks:
            chunk_owners.setdefault(chunk.chunk_id, set()).add(str(resource.resource_version_id))
        seen_tuples: set[tuple[Any, ...]] = set()
        semantic_by_collection: dict[str, tuple[Any, ...]] = {}
        for placement in resource.placements:
            values = placement.model_dump(mode="json")
            full_tuple = _canonical_tuple(values) + (tuple(sorted(values["audience"])),)
            if full_tuple in seen_tuples:
                duplicate_identical_placements += 1
            seen_tuples.add(full_tuple)
            existing = semantic_by_collection.get(placement.collection)
            if existing is not None and existing != full_tuple:
                conflicting_same_collection_placements += 1
            semantic_by_collection[placement.collection] = full_tuple

    resource_ids_with_multiple_versions = {
        resource_id: sorted(versions)
        for resource_id, versions in resource_id_versions.items()
        if len(versions) > 1
    }
    chunk_ids_shared_across_resources = {
        chunk_id: sorted(owners) for chunk_id, owners in chunk_owners.items() if len(owners) > 1
    }
    return {
        "RESOURCE_ID_WITH_MULTIPLE_VERSIONS_COUNT": len(resource_ids_with_multiple_versions),
        "resource_ids_with_multiple_versions": resource_ids_with_multiple_versions,
        "CHUNK_ID_SHARED_ACROSS_RESOURCES_COUNT": len(chunk_ids_shared_across_resources),
        "chunk_ids_shared_across_resources": chunk_ids_shared_across_resources,
        "DUPLICATE_IDENTICAL_PLACEMENT_COUNT": duplicate_identical_placements,
        "CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT": conflicting_same_collection_placements,
    }


def verify_r1_evidence(
    *,
    bootstrap_path: Path,
    release_registry_path: Path,
    release_registry_sha256: str,
) -> R1EvidenceReport:
    """Pure, read-only, no PostgreSQL connection ever opened."""
    bootstrap = _load_bootstrap(bootstrap_path)
    try:
        registry = load_release_registry_file(release_registry_path, release_registry_sha256)
    except ReleaseReadinessError as exc:
        raise R1EvidenceVerifierError(f"release authority is not sound: {exc}") from exc

    expected_tuples, expected_collections = _expected_placement_tuples(registry)
    actual_tuples, actual_collections = _actual_placement_tuples(bootstrap)

    exported_minus_sealed = actual_tuples - expected_tuples
    sealed_minus_exported = expected_tuples - actual_tuples
    exported_collections_minus_sealed = actual_collections - expected_collections
    sealed_collections_minus_exported = expected_collections - actual_collections

    resource_ids = {str(r.resource_id) for r in bootstrap.resources}
    resource_version_ids = {str(r.resource_version_id) for r in bootstrap.resources}
    content_sha256s = {r.content_sha256 for r in bootstrap.resources}
    rag_artifact_ids = {r.rag_artifact_id for r in bootstrap.resources}
    chunk_ids = {chunk.chunk_id for r in bootstrap.resources for chunk in r.chunks}
    placement_count = sum(len(r.placements) for r in bootstrap.resources)
    chunk_count = sum(len(r.chunks) for r in bootstrap.resources)

    collisions = _collisions(bootstrap)

    gates: dict[str, Any] = {
        "PRODUCER_REPOSITORY": bootstrap.producer_repository,
        "PRODUCER_COMMIT": bootstrap.producer_commit,
        "BOOTSTRAP_PROTOCOL_VERSION": bootstrap.protocol_version,
        "BOOTSTRAP_PACKAGE_VERSION": bootstrap.package_version,
        "BOOTSTRAP_SOURCE_SNAPSHOT_SHA256": bootstrap.source_snapshot_sha256,
        "BOOTSTRAP_INVENTORY_SHA256": bootstrap.inventory_sha256,
        "BOOTSTRAP_FILE_SHA256": _sha256_file(bootstrap_path),
        "BOOTSTRAP_RESOURCE_ROWS": len(bootstrap.resources),
        "BOOTSTRAP_RESOURCE_VERSION_IDS": len(resource_version_ids),
        "BOOTSTRAP_PLACEMENTS": placement_count,
        "BOOTSTRAP_CHUNKS": chunk_count,
        "DISTINCT_RESOURCE_IDS": len(resource_ids),
        "DISTINCT_RESOURCE_VERSION_IDS": len(resource_version_ids),
        "DISTINCT_CONTENT_SHA256": len(content_sha256s),
        "DISTINCT_RAG_ARTIFACT_IDS": len(rag_artifact_ids),
        "DISTINCT_CHUNK_IDS": len(chunk_ids),
        "RELEASE_ID": registry.manifests[0].expectation.release_id,
        "RELEASE_SCHOOL_YEAR": registry.manifests[0].expectation.school_year,
        "EXPECTED_PLACEMENT_TUPLES": len(expected_tuples),
        "ACTUAL_PLACEMENT_TUPLES": len(actual_tuples),
        "EXPORTED_COLLECTIONS_MINUS_SEALED_COLLECTIONS": sorted(
            exported_collections_minus_sealed
        ),
        "SEALED_COLLECTIONS_MINUS_EXPORTED_COLLECTIONS": sorted(
            sealed_collections_minus_exported
        ),
        "EXPORTED_PLACEMENT_SET_MINUS_SEALED_PLACEMENT_SET_COUNT": len(exported_minus_sealed),
        "SEALED_PLACEMENT_SET_MINUS_EXPORTED_PLACEMENT_SET_COUNT": len(sealed_minus_exported),
        "AUDIENCE_COMPARED_AGAINST_SEALED_AUTHORITY": False,
        "AUDIENCE_STRUCTURAL_GAP_REASON": (
            "no committed sealed-release artifact carries an audience field; "
            "reported as an observed distribution only"
        ),
    }
    gates.update(_multiplacement_evidence(bootstrap))

    blockers: list[str] = []
    if exported_minus_sealed:
        blockers.append(
            f"EXPORTED_PLACEMENT_SET_MINUS_SEALED_PLACEMENT_SET="
            f"{len(exported_minus_sealed)}"
        )
    if sealed_minus_exported:
        blockers.append(
            f"SEALED_PLACEMENT_SET_MINUS_EXPORTED_PLACEMENT_SET="
            f"{len(sealed_minus_exported)}"
        )
    if exported_collections_minus_sealed:
        blockers.append(
            "EXPORTED_COLLECTIONS_MINUS_SEALED_COLLECTIONS="
            f"{sorted(exported_collections_minus_sealed)}"
        )
    if sealed_collections_minus_exported:
        blockers.append(
            "SEALED_COLLECTIONS_MINUS_EXPORTED_COLLECTIONS="
            f"{sorted(sealed_collections_minus_exported)}"
        )
    if collisions["CHUNK_ID_SHARED_ACROSS_RESOURCES_COUNT"]:
        blockers.append(
            "CHUNK_ID_SHARED_ACROSS_RESOURCES_COUNT="
            f"{collisions['CHUNK_ID_SHARED_ACROSS_RESOURCES_COUNT']}"
        )
    if collisions["CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT"]:
        blockers.append(
            "CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT="
            f"{collisions['CONFLICTING_SAME_COLLECTION_PLACEMENT_COUNT']}"
        )
    if bootstrap.inventory_sha256 != bootstrap.compute_sha256():
        # Unreachable in practice -- ResourceRegistryBootstrap already
        # refuses to construct with a mismatched inventory_sha256 -- kept as
        # an explicit, named gate rather than relying only on the pydantic
        # validator having already run during _load_bootstrap.
        blockers.append("BOOTSTRAP_INVENTORY_SHA256_MISMATCH")

    return R1EvidenceReport(
        ready=not blockers,
        gates=gates,
        distributions=_distributions(bootstrap),
        collisions=collisions,
        blockers=tuple(blockers),
    )


__all__ = [
    "CANONICAL_PLACEMENT_FIELDS",
    "R1EvidenceReport",
    "R1EvidenceVerifierError",
    "verify_r1_evidence",
]
