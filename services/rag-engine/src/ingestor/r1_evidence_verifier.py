"""R1 evidence verifier: static, read-only proof that an already-exported
``ResourceRegistryBootstrap`` represents exactly the sealed production
release it claims to -- never a database connection, never a mutation.

This is deliberately NOT another exporter and NOT a redesign of the
``ResourceRegistryBootstrap`` contract. It consumes:

  * the bootstrap file an operator already produced with the existing
    ``resource_registry_bootstrap_cli`` command,
  * the same sealed release chain that command's own
    ``--release-registry-path``/``--release-registry-sha256`` arguments
    already pin (``nexus_release_chain.release_readiness.load_release_registry_file``,
    unmodified, reused as-is for its digest-verified parse of the release
    authority), and
  * the declarative profile registry + its signed manifest
    (``ingestor.ingestion_profiles.registry``/``.manifest``, both reused
    unmodified), which is the transitive authority for ``audience``.

and proves the bootstrap's semantic placement universe is exactly the
sealed release's across all 11 canonical dimensions -- not merely that
per-artifact ``(collection, content_sha256)`` bindings match, which is the
narrower invariant the exporter's own
``export_resource_registry_bootstrap_inventory`` already enforces at write
time (see ``resource_registry_bootstrap.py``).

R1B correction to R1A's ``audience`` conclusion
------------------------------------------------
R1A reported ``audience`` as structurally unsealed because it only looked at
subject-release placement files, which indeed never carry it. That was
incomplete. The full chain, proven here at runtime (not merely asserted):

    sealed release . authorities.profile_manifest_sha256
        (authority_bindings.json labels this SEMANTIC_PROFILE_FINGERPRINT)
    == verify_profile_manifest(load_profile_registry(profile_root),
                                profile_manifest_path).manifest_fingerprint
        (recomputed from the REAL committed profile YAML files, not trusted
        from a familiar path -- a wrong or tampered profile directory fails
        this equality)
    == every ExpectedPlacement.profile_manifest_digest already parsed by
       load_release_registry_file (release_readiness.py's own subject/
       aggregate authority cross-checks already require these to agree
       inside the release documents themselves; this module additionally
       ties them to the REAL local profile files)
    -> CollectionProfile.scope.audience is therefore sealed exactly as
       every other ResourceScope dimension is.

``audience`` is compared against this proven authority like every other
canonical dimension. Before trusting ``profile.scope.audience`` for a given
collection, this module also proves that profile's OTHER shared scope
dimensions (tenant/niveau/voie/matiere/candidat/visibility/school_year/
programme_version) agree with the sealed subject-release placement for that
collection, and that the profile's own recomputed fingerprint matches the
release's declared ``profile_fingerprint`` for it -- a profile that merely
shares a collection name is not accepted on that basis alone.
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
from nexus_release_chain.release_readiness import (
    ExpectedPlacement,
    ReleaseReadinessError,
    ReleaseRegistryExpectation,
    load_release_registry_file,
)

from ingestor.ingestion_profiles.manifest import (
    ManifestVerification,
    ProfileManifestError,
    verify_profile_manifest,
)
from ingestor.ingestion_profiles.registry import (
    ProfileRegistry,
    ProfileRegistryError,
    load_profile_registry,
    profile_fingerprint,
    select_profile,
)

#: The 10 SCALAR canonical dimensions. ``audience`` (set-valued) is handled
#: separately and appended as its own canonicalized element -- see
#: ``_audience_tuple`` and every call site that builds a full placement key.
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

#: Dimensions a CollectionProfile's ``scope`` shares with a sealed
#: subject-release placement -- everything ResourceScope carries except
#: ``audience`` itself (that is the value under proof) and ``collection``
#: (the lookup key, checked separately for defense in depth).
_PROFILE_RELEASE_SHARED_SCOPE_FIELDS: tuple[str, ...] = (
    "tenant",
    "niveau",
    "voie",
    "matiere",
    "candidat",
    "visibility",
    "school_year",
    "programme_version",
)


class R1EvidenceVerifierError(ValueError):
    """The bootstrap or an authority it must be checked against cannot be
    evaluated safely (unreadable, malformed, or fails its own internal
    digest/fingerprint proof)."""


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


def _load_profile_authority(
    profile_root: Path, profile_manifest_path: Path
) -> tuple[ProfileRegistry, ManifestVerification]:
    try:
        registry = load_profile_registry(profile_root)
    except ProfileRegistryError as exc:
        raise R1EvidenceVerifierError(f"profile registry is not sound: {exc}") from exc
    if not registry:
        raise R1EvidenceVerifierError(f"profile registry at {profile_root} is empty")
    try:
        verified = verify_profile_manifest(registry, profile_manifest_path)
    except ProfileManifestError as exc:
        raise R1EvidenceVerifierError(f"profile manifest authority is not sound: {exc}") from exc
    return registry, verified


def _all_expected_placements(
    registry: ReleaseRegistryExpectation,
) -> list[ExpectedPlacement]:
    return [
        placement
        for manifest in registry.manifests
        for placement in manifest.expectation.placements
    ]


def _audience_tuple(values: list[Any]) -> tuple[str, ...]:
    # Audience is a str-mixin Enum: str(Audience.libre) == "Audience.libre"
    # (Enum.__str__ takes precedence over str.__str__), so plain str() would
    # silently make every profile-side audience value disagree with the
    # already-plain-string bootstrap side. ``.value`` extracts the true
    # string for enum members; already-plain strings pass through unchanged.
    return tuple(sorted(getattr(value, "value", value) for value in values))


@dataclass(frozen=True)
class _ProfileAuthorityResult:
    profile_manifest_authority_pass: bool
    scope_consistency_pass: bool
    scope_mismatches: tuple[str, ...]
    audience_by_collection: dict[str, tuple[str, ...]]
    verified_manifest_fingerprint: str


def _cross_check_profile_authority(
    expected_placements: list[ExpectedPlacement],
    profile_registry: ProfileRegistry,
    verified_manifest: ManifestVerification,
) -> _ProfileAuthorityResult:
    manifest_authority_pass = True
    scope_mismatches: list[str] = []
    audience_by_collection: dict[str, tuple[str, ...]] = {}

    for placement in expected_placements:
        if placement.profile_manifest_digest != verified_manifest.manifest_fingerprint:
            manifest_authority_pass = False
            continue

        try:
            profile = select_profile(
                profile_registry,
                collection=placement.collection,
                profile_version=placement.profile_version,
            )
        except ProfileRegistryError as exc:
            scope_mismatches.append(
                f"{placement.collection}: no usable profile for "
                f"profile_version={placement.profile_version!r} ({exc})"
            )
            continue

        declared_fingerprint = profile_fingerprint(profile)
        if declared_fingerprint != placement.profile_fingerprint:
            scope_mismatches.append(
                f"{placement.collection}: profile fingerprint {declared_fingerprint} "
                f"does not match the release's declared {placement.profile_fingerprint}"
            )
            continue

        if profile.scope.collection != placement.collection:
            scope_mismatches.append(
                f"{placement.collection}: profile scope.collection is "
                f"{profile.scope.collection!r}"
            )
            continue

        payload = placement.payload
        disagreements = [
            field_name
            for field_name in _PROFILE_RELEASE_SHARED_SCOPE_FIELDS
            # ResourceScope's fields are str-mixin enums (e.g. Niveau,
            # Candidat): compared directly against the release's plain
            # strings, never through str(), whose default Enum.__str__
            # ("Niveau.terminale") would falsely disagree with "terminale".
            if getattr(profile.scope, field_name) != payload.get(field_name)
        ]
        if disagreements:
            scope_mismatches.append(
                f"{placement.collection}: profile/release scope disagree on "
                f"{disagreements}"
            )
            continue

        audience_by_collection[placement.collection] = _audience_tuple(profile.scope.audience)

    return _ProfileAuthorityResult(
        profile_manifest_authority_pass=manifest_authority_pass,
        scope_consistency_pass=not scope_mismatches,
        scope_mismatches=tuple(scope_mismatches),
        audience_by_collection=audience_by_collection,
        verified_manifest_fingerprint=verified_manifest.manifest_fingerprint,
    )


#: The R1G canonical chunk dimensions this verifier independently compares.
#: ``chunk_sha256`` is deliberately excluded: it is checked once, DB-side, by
#: the exporter's own pre-publication guard (``resource_registry_bootstrap
#: .export_resource_registry_bootstrap_inventory``) and never travels in the
#: ``BootstrapChunk`` contract (chunk_id + locator only) for this
#: no-DB-access, static verifier to re-derive.
CANONICAL_CHUNK_DIMENSIONS: tuple[str, ...] = (
    "content_sha256",
    "chunk_id",
    "chunk_index",
    "page_start",
    "page_end",
)


def _expected_chunk_tuples(
    registry: ReleaseRegistryExpectation,
) -> tuple[set[tuple[Any, ...]], set[str]]:
    tuples: set[tuple[Any, ...]] = set()
    artifact_shas: set[str] = set()
    for manifest in registry.manifests:
        for artifact in manifest.expectation.artifacts:
            artifact_shas.add(artifact.content_sha256)
            for chunk in artifact.chunks:
                tuples.add(
                    (
                        artifact.content_sha256,
                        str(chunk["chunk_id"]),
                        int(chunk["chunk_index"]),
                        int(chunk["page_start"]),
                        int(chunk["page_end"]),
                    )
                )
    return tuples, artifact_shas


def _actual_chunk_tuples(bootstrap: ResourceRegistryBootstrap) -> set[tuple[Any, ...]]:
    tuples: set[tuple[Any, ...]] = set()
    for resource in bootstrap.resources:
        for chunk in resource.chunks:
            tuples.add(
                (
                    resource.content_sha256,
                    chunk.chunk_id,
                    chunk.locator.chunk_index,
                    chunk.locator.page_start,
                    chunk.locator.page_end,
                )
            )
    return tuples


def _canonical_tuple(values: dict[str, Any]) -> tuple[Any, ...]:
    return tuple(values[field_name] for field_name in CANONICAL_PLACEMENT_FIELDS)


def _expected_placement_tuples(
    expected_placements: list[ExpectedPlacement],
    audience_by_collection: dict[str, tuple[str, ...]],
) -> tuple[set[tuple[Any, ...]], set[str]]:
    tuples: set[tuple[Any, ...]] = set()
    collections: set[str] = set()
    for placement in expected_placements:
        collections.add(placement.collection)
        audience = audience_by_collection.get(placement.collection)
        if audience is None:
            # Scope authority for this collection did not check out --
            # already reported as a blocker via scope_mismatches. Building a
            # tuple with a fabricated audience would be worse than omitting
            # it: it could accidentally "match" by coincidence.
            continue
        tuples.add(_canonical_tuple(placement.payload) + (audience,))
    return tuples, collections


def _actual_placement_tuples(
    bootstrap: ResourceRegistryBootstrap,
) -> tuple[set[tuple[Any, ...]], set[str]]:
    tuples: set[tuple[Any, ...]] = set()
    collections: set[str] = set()
    for resource in bootstrap.resources:
        for placement in resource.placements:
            values = placement.model_dump(mode="json")
            tuples.add(_canonical_tuple(values) + (_audience_tuple(values["audience"]),))
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
        audiences = {_audience_tuple(p.audience) for p in resource.placements}
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
            full_tuple = _canonical_tuple(values) + (_audience_tuple(values["audience"]),)
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
    profile_root: Path,
    profile_manifest_path: Path,
) -> R1EvidenceReport:
    """Pure, read-only, no PostgreSQL connection ever opened.

    ``profile_root``/``profile_manifest_path`` are operator-supplied paths,
    never trusted merely for sitting at a familiar location: their content
    is accepted only once its fingerprint chain is proven against the
    sealed release (see the module docstring)."""
    bootstrap = _load_bootstrap(bootstrap_path)
    try:
        registry = load_release_registry_file(release_registry_path, release_registry_sha256)
    except ReleaseReadinessError as exc:
        raise R1EvidenceVerifierError(f"release authority is not sound: {exc}") from exc

    profile_registry, verified_manifest = _load_profile_authority(
        profile_root, profile_manifest_path
    )
    expected_placements = _all_expected_placements(registry)
    profile_authority = _cross_check_profile_authority(
        expected_placements, profile_registry, verified_manifest
    )

    expected_tuples, expected_collections = _expected_placement_tuples(
        expected_placements, profile_authority.audience_by_collection
    )
    actual_tuples, actual_collections = _actual_placement_tuples(bootstrap)

    exported_minus_sealed = actual_tuples - expected_tuples
    sealed_minus_exported = expected_tuples - actual_tuples
    exported_collections_minus_sealed = actual_collections - expected_collections
    sealed_collections_minus_exported = expected_collections - actual_collections

    expected_chunk_tuples, expected_chunk_artifact_shas = _expected_chunk_tuples(registry)
    actual_chunk_tuples = _actual_chunk_tuples(bootstrap)
    exported_chunks_minus_sealed = actual_chunk_tuples - expected_chunk_tuples
    sealed_chunks_minus_exported = expected_chunk_tuples - actual_chunk_tuples
    out_of_release_chunks = {
        chunk_tuple
        for chunk_tuple in actual_chunk_tuples
        if chunk_tuple[0] not in expected_chunk_artifact_shas
    }
    chunk_binding_pass = not exported_chunks_minus_sealed and not sealed_chunks_minus_exported

    resource_ids = {str(r.resource_id) for r in bootstrap.resources}
    resource_version_ids = {str(r.resource_version_id) for r in bootstrap.resources}
    content_sha256s = {r.content_sha256 for r in bootstrap.resources}
    rag_artifact_ids = {r.rag_artifact_id for r in bootstrap.resources}
    chunk_ids = {chunk.chunk_id for r in bootstrap.resources for chunk in r.chunks}
    placement_count = sum(len(r.placements) for r in bootstrap.resources)
    chunk_count = sum(len(r.chunks) for r in bootstrap.resources)

    collisions = _collisions(bootstrap)

    gates: dict[str, Any] = {
        "BOOTSTRAP_PRODUCER_REPOSITORY": bootstrap.producer_repository,
        "BOOTSTRAP_PRODUCER_COMMIT": bootstrap.producer_commit,
        "BOOTSTRAP_PROTOCOL_VERSION": bootstrap.protocol_version,
        "BOOTSTRAP_PACKAGE_VERSION": bootstrap.package_version,
        "BOOTSTRAP_SOURCE_SNAPSHOT_SHA256": bootstrap.source_snapshot_sha256,
        "SOURCE_SNAPSHOT_SHA256_VERIFICATION": "PRODUCER_ATTESTED_NOT_STATICALLY_RECOMPUTABLE",
        "SOURCE_SNAPSHOT_SHA256_VERIFICATION_REASON": (
            "source_snapshot_sha256 is computed producer-side over "
            "_safe_snapshot_row material (per-placement currentness/"
            "placement_status/review_status/source_placement_id/source_scope) "
            "that the final BootstrapPlacement contract deliberately does not "
            "carry; this verifier has no DB access and cannot reconstruct "
            "those rows from the bootstrap file alone. It is transitively "
            "protected by inventory_sha256 (which this verifier DOES "
            "independently recompute and which the pinned contract's own "
            "validator already enforces at load time), not independently "
            "recomputable itself."
        ),
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
        "SEALED_RELEASE_ID": registry.manifests[0].expectation.release_id,
        "SEALED_RELEASE_AUTHORITY_SHA": release_registry_sha256,
        "RELEASE_SCHOOL_YEAR": registry.manifests[0].expectation.school_year,
        "R1_PROFILE_MANIFEST_AUTHORITY": (
            "PASS" if profile_authority.profile_manifest_authority_pass else "FAIL"
        ),
        "R1_PROFILE_RELEASE_SCOPE_CONSISTENCY": (
            "PASS" if profile_authority.scope_consistency_pass else "FAIL"
        ),
        "profile_scope_mismatches": list(profile_authority.scope_mismatches),
        "VERIFIED_PROFILE_MANIFEST_FINGERPRINT": profile_authority.verified_manifest_fingerprint,
        "R1_CANONICAL_PLACEMENT_DIMENSIONS": 11,
        "AUDIENCE_COMPARED_AGAINST_SEALED_AUTHORITY": True,
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
        "R1_CANONICAL_CHUNK_DIMENSIONS": list(CANONICAL_CHUNK_DIMENSIONS),
        "EXPECTED_CHUNK_TUPLES": len(expected_chunk_tuples),
        "ACTUAL_CHUNK_TUPLES": len(actual_chunk_tuples),
        "EXPORTED_CHUNK_SET_MINUS_SEALED_CHUNK_SET": len(exported_chunks_minus_sealed),
        "SEALED_CHUNK_SET_MINUS_EXPORTED_CHUNK_SET": len(sealed_chunks_minus_exported),
        "OUT_OF_RELEASE_CHUNKS": len(out_of_release_chunks),
        "R1_BOOTSTRAP_CHUNK_IDENTITY_BINDING": "PASS" if chunk_binding_pass else "FAIL",
        "R1_CHUNK_RELEASE_BINDING": "PASS" if chunk_binding_pass else "FAIL",
    }
    gates.update(_multiplacement_evidence(bootstrap))

    blockers: list[str] = []
    if not profile_authority.profile_manifest_authority_pass:
        blockers.append("R1_PROFILE_MANIFEST_AUTHORITY=FAIL")
    if not profile_authority.scope_consistency_pass:
        blockers.append(
            f"R1_PROFILE_RELEASE_SCOPE_CONSISTENCY=FAIL "
            f"{list(profile_authority.scope_mismatches)}"
        )
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
    if exported_chunks_minus_sealed:
        # R1G: the bootstrap's own chunk set (chunk_id + locator, per
        # artifact) disagrees with the sealed release's chunk authority --
        # an extra, swapped, or otherwise unsealed chunk reached the
        # bootstrap. Distinct from the placement-set checks above, which
        # never looked below the artifact/collection level at all.
        blockers.append(
            f"EXPORTED_CHUNK_SET_MINUS_SEALED_CHUNK_SET={len(exported_chunks_minus_sealed)}"
        )
    if sealed_chunks_minus_exported:
        blockers.append(
            f"SEALED_CHUNK_SET_MINUS_EXPORTED_CHUNK_SET={len(sealed_chunks_minus_exported)}"
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
    if collisions["DUPLICATE_IDENTICAL_PLACEMENT_COUNT"]:
        # An unexplained producer duplicate is never silently deduplicated
        # (issue #155's own rule) -- a bootstrap containing one is never
        # ready, even though it disagrees with nothing else.
        blockers.append(
            "DUPLICATE_IDENTICAL_PLACEMENT_COUNT="
            f"{collisions['DUPLICATE_IDENTICAL_PLACEMENT_COUNT']}"
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
    "CANONICAL_CHUNK_DIMENSIONS",
    "CANONICAL_PLACEMENT_FIELDS",
    "R1EvidenceReport",
    "R1EvidenceVerifierError",
    "verify_r1_evidence",
]
