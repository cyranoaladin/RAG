"""Résolution Wave 0 liée au catalogue, à la currentness et au profil exacts.

Le catalogue conserve sa classification physique candidate. Ce module ne la
réécrit pas : il superpose une décision de currentness artifact-bound puis
vérifie un unique placement Nexus avant de rendre un fait consommable par les
deux workers.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from uuid import UUID

import yaml
from nexus_contracts.document import Niveau, TypeDoc, Voie
from nexus_contracts.ingestion import ResourceScope

try:
    from .governed_publisher_v2 import EligiblePlacement
    from .ingestion_profiles.registry import (
        ProfileRegistry,
        profile_fingerprint,
        select_profile,
    )
    from .wave0_release import (
        CandidateInventory,
        CandidatePlacement,
        ClosedPedagogicalMapping,
        PedagogicalMapping,
        ReleaseAuthorityError,
        Wave0ReleaseAuthority,
        load_aggregate_release,
        load_candidate_inventory,
        load_pedagogical_mapping,
    )
except ImportError:  # image worker aplatie
    from governed_publisher_v2 import EligiblePlacement  # type: ignore[no-redef]
    from ingestion_profiles.registry import (  # type: ignore[no-redef]
        ProfileRegistry,
        profile_fingerprint,
        select_profile,
    )
    from wave0_release import (  # type: ignore[no-redef]
        CandidateInventory,
        CandidatePlacement,
        ClosedPedagogicalMapping,
        PedagogicalMapping,
        ReleaseAuthorityError,
        Wave0ReleaseAuthority,
        load_aggregate_release,
        load_candidate_inventory,
        load_pedagogical_mapping,
    )

CURRENTNESS_EVIDENCE_KIND = "WAVE0_ARTIFACT_CURRENTNESS_V2"
SEALED_CATALOG_KIND = "REAL_SEALED_CORPUS"
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_SCHOOL_YEAR = re.compile(r"\A[0-9]{4}-[0-9]{4}\Z")


class PlacementResolutionError(RuntimeError):
    """Une preuve manque, dérive ou désigne un placement ambigu."""


@dataclass(frozen=True)
class _CurrentnessArtifact:
    content_sha256: str
    exact_path: str
    external_level: str
    subject: str
    effective_currentness: str
    current_for_school_year: str


@dataclass(frozen=True)
class VerifiedPedagogicalPlacement:
    content_sha256: str
    source_path: str
    source_url: str
    source_placement_id: str
    external_level: str
    external_subject: str
    external_scope: str
    external_document_type: str
    effective_currentness: str
    nexus_collection: str
    nexus_niveau: Niveau
    nexus_voie: Voie
    nexus_matiere: str
    nexus_statut_enseignement: str
    nexus_programme_version: str
    nexus_domain: str
    nexus_scope: ResourceScope
    type_doc: TypeDoc
    profile_version: str
    profile_fingerprint: str
    corpus_manifest_sha256: str
    catalog_sha256: str
    placement_catalog_sha256: str
    currentness_evidence_sha256: str
    programme_index_sha256: str
    niveau_conformity: bool
    voie_conformity: bool
    matiere_conformity: bool
    programme_conformity: bool


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _require_sha(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise PlacementResolutionError(f"{label} must be a lowercase 64-hex SHA")
    return value


def _require_file_digest(path: Path, expected: str, *, label: str) -> str:
    _require_sha(expected, label=f"expected {label} SHA")
    actual = _file_sha256(path)
    if actual != expected:
        raise PlacementResolutionError(
            f"{label} hashes to {actual}, not expected digest {expected}"
        )
    return actual


def _load_currentness(
    path: Path,
    *,
    expected_sha256: str,
    expected_manifest_sha256: str,
    candidate_inventory: CandidateInventory,
) -> tuple[str, str, dict[str, _CurrentnessArtifact]]:
    evidence_sha = _require_file_digest(
        path, expected_sha256, label="currentness evidence"
    )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PlacementResolutionError("currentness evidence cannot be read") from exc
    if not isinstance(document, Mapping):
        raise PlacementResolutionError("currentness evidence must be a mapping")
    if document.get("evidence_kind") != CURRENTNESS_EVIDENCE_KIND:
        raise PlacementResolutionError("currentness evidence kind is invalid")
    school_year = document.get("school_year")
    if not isinstance(school_year, str) or _SCHOOL_YEAR.fullmatch(school_year) is None:
        raise PlacementResolutionError("currentness evidence school year is invalid")
    if school_year != candidate_inventory.school_year:
        raise PlacementResolutionError(
            "currentness evidence differs from candidate inventory school year"
        )
    if document.get("corpus_manifest_sha256") != expected_manifest_sha256:
        raise PlacementResolutionError("currentness evidence manifest differs")
    if document.get("candidate_inventory_sha256") != candidate_inventory.sha256:
        raise PlacementResolutionError("currentness evidence candidate inventory differs")
    raw_artifacts = document.get("artifacts")
    if not isinstance(raw_artifacts, list) or not raw_artifacts:
        raise PlacementResolutionError("currentness evidence artifacts are absent")

    artifacts: dict[str, _CurrentnessArtifact] = {}
    required = {
        "content_sha256",
        "exact_path",
        "external_level",
        "subject",
        "effective_currentness",
        "current_for_school_year",
    }
    for raw in raw_artifacts:
        if not isinstance(raw, Mapping) or not required <= set(raw):
            raise PlacementResolutionError("currentness artifact fields are incomplete")
        sha = _require_sha(raw.get("content_sha256"), label="currentness artifact SHA")
        if sha in artifacts:
            raise PlacementResolutionError(f"content {sha} appears twice in currentness evidence")
        exact_path = raw.get("exact_path")
        if not isinstance(exact_path, str) or not exact_path.startswith(
            "01_EDUSCOL_OFFICIEL/"
        ):
            raise PlacementResolutionError("currentness artifact path is invalid")
        if raw.get("effective_currentness") != "actuel":
            raise PlacementResolutionError("currentness must be 'actuel' on the positive path")
        if raw.get("current_for_school_year") != school_year:
            raise PlacementResolutionError("artifact currentness school year differs")
        level = raw.get("external_level")
        subject = raw.get("subject")
        if not isinstance(level, str) or not level:
            raise PlacementResolutionError("currentness artifact level is invalid")
        if not isinstance(subject, str) or not subject:
            raise PlacementResolutionError("currentness artifact subject is invalid")
        if raw.get("current_download_sha256") != sha or raw.get("byte_identity") is not True:
            raise PlacementResolutionError("currentness byte identity is not exact")
        for url_field in ("current_source_listing_url", "current_download_url"):
            url = raw.get(url_field)
            if not isinstance(url, str) or urlparse(url).hostname not in {
                "eduscol.education.fr",
                "eduscol.education.gouv.fr",
            }:
                raise PlacementResolutionError("currentness official URL is invalid")
        artifacts[sha] = _CurrentnessArtifact(
            content_sha256=sha,
            exact_path=exact_path,
            external_level=level,
            subject=subject,
            effective_currentness="actuel",
            current_for_school_year=school_year,
        )
    if set(artifacts) != set(candidate_inventory.unique_content_sha256):
        raise PlacementResolutionError(
            "currentness evidence differs from the candidate inventory artifact set"
        )
    for sha, artifact in artifacts.items():
        candidates = candidate_inventory.candidates_for(sha)
        if not candidates or any(
            candidate.physical_path != artifact.exact_path
            or candidate.external_level != artifact.external_level
            or candidate.external_subject != artifact.subject
            for candidate in candidates
        ):
            raise PlacementResolutionError(
                "currentness evidence differs from the candidate inventory facts"
            )
    return evidence_sha, school_year, artifacts


def _load_programme_index(
    path: Path,
    *,
    expected_sha256: str,
) -> tuple[str, dict[str, str]]:
    index_sha = _require_file_digest(
        path, expected_sha256, label="canonical programme index"
    )
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise PlacementResolutionError("canonical programme index cannot be read") from exc
    if not isinstance(document, Mapping):
        raise PlacementResolutionError("canonical programme index must be a mapping")
    if document.get("niveau") != Niveau.troisieme.value or document.get("voie") != "college":
        raise PlacementResolutionError("canonical programme index scope is invalid")
    raw_fiches = document.get("fiches")
    if not isinstance(raw_fiches, list) or not raw_fiches:
        raise PlacementResolutionError("canonical programme index has no entries")
    by_collection: dict[str, str] = {}
    for raw in raw_fiches:
        if not isinstance(raw, Mapping):
            raise PlacementResolutionError("canonical programme entry is malformed")
        collection = raw.get("collection_cible")
        programme = raw.get("programme_version")
        if (
            not isinstance(collection, str)
            or not collection
            or not isinstance(programme, str)
            or not programme
        ):
            raise PlacementResolutionError("canonical programme entry is incomplete")
        if collection in by_collection:
            raise PlacementResolutionError("canonical programme collection is duplicated")
        by_collection[collection] = programme
    return index_sha, by_collection


@dataclass(frozen=True)
class VerifiedPedagogicalPlacementResolver:
    catalog_sha256: str
    corpus_manifest_sha256: str
    placement_catalog_sha256: str
    currentness_evidence_sha256: str
    candidate_inventory_sha256: str
    mapping_sha256: str
    release_manifest_sha256: str
    release_pii_evidence_sha256: str
    release_pii_policy_sha256: str
    release_rights_registry_sha256: str
    release_profile_manifest_digest: str
    release_embedding_model_id: str
    release_embedding_inventory_sha256: str
    release_embedding_dimension: int
    currentness_school_year: str
    programme_index_sha256: str
    _artifacts: Mapping[str, Mapping[str, object]]
    _currentness: Mapping[str, _CurrentnessArtifact]
    _candidate_inventory: CandidateInventory
    _mapping: ClosedPedagogicalMapping
    _release: Wave0ReleaseAuthority
    _profiles: ProfileRegistry
    _collection_config: Mapping[str, object]
    _canonical_programme_by_collection: Mapping[str, str]

    @classmethod
    def load(
        cls,
        *,
        catalog_path: Path,
        expected_catalog_sha256: str,
        candidate_inventory_path: Path,
        expected_candidate_inventory_sha256: str,
        currentness_evidence_path: Path,
        expected_currentness_evidence_sha256: str,
        mapping_path: Path,
        expected_mapping_sha256: str,
        release_manifest_path: Path,
        expected_release_manifest_sha256: str,
        expected_manifest_sha256: str,
        profile_registry: ProfileRegistry,
        collection_config: Mapping[str, object],
        programme_index_path: Path,
        expected_programme_index_sha256: str,
    ) -> VerifiedPedagogicalPlacementResolver:
        manifest = _require_sha(expected_manifest_sha256, label="expected manifest SHA")
        catalog_sha = _require_file_digest(
            catalog_path, expected_catalog_sha256, label="sealed catalog"
        )
        try:
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PlacementResolutionError("sealed catalog cannot be read") from exc
        if not isinstance(catalog, Mapping):
            raise PlacementResolutionError("sealed catalog must be a mapping")
        if catalog.get("catalog_kind") != SEALED_CATALOG_KIND:
            raise PlacementResolutionError("sealed catalog kind is invalid")
        if catalog.get("verification_passed") is not True:
            raise PlacementResolutionError("sealed catalog is not verified")
        if catalog.get("manifest_sha256") != manifest:
            raise PlacementResolutionError("sealed catalog manifest differs")
        placement_catalog_sha = _require_sha(
            catalog.get("placement_catalog_sha256"), label="placement catalog SHA"
        )
        artifacts = catalog.get("artifacts")
        if not isinstance(artifacts, Mapping):
            raise PlacementResolutionError("sealed catalog artifacts are absent")
        try:
            candidate_inventory = load_candidate_inventory(
                candidate_inventory_path,
                expected_sha256=expected_candidate_inventory_sha256,
            )
            mapping = load_pedagogical_mapping(
                mapping_path, expected_sha256=expected_mapping_sha256
            )
        except ReleaseAuthorityError as exc:
            raise PlacementResolutionError(str(exc)) from exc
        if (
            candidate_inventory.corpus_manifest_sha256 != manifest
            or candidate_inventory.sealed_catalog_sha256 != catalog_sha
            or candidate_inventory.placement_catalog_sha256 != placement_catalog_sha
        ):
            raise PlacementResolutionError(
                "candidate inventory differs from the sealed catalog authorities"
            )
        evidence_sha, school_year, currentness = _load_currentness(
            currentness_evidence_path,
            expected_sha256=expected_currentness_evidence_sha256,
            expected_manifest_sha256=manifest,
            candidate_inventory=candidate_inventory,
        )
        try:
            release = load_aggregate_release(
                release_manifest_path,
                expected_sha256=expected_release_manifest_sha256,
                candidate_inventory=candidate_inventory,
                expected_currentness_evidence_sha256=evidence_sha,
            )
        except ReleaseAuthorityError as exc:
            raise PlacementResolutionError(str(exc)) from exc
        for candidate in candidate_inventory.candidates:
            release_collections = {
                collection
                for collection, sha in release.artifacts
                if sha == candidate.content_sha256
                and candidate.source_placement_id
                in release.artifacts[(collection, sha)].expected_placement_ids
            }
            if not release_collections:
                continue
            try:
                mapping.resolve_type_doc(candidate.external_document_type)
                for release_collection in release_collections:
                    mapping.resolve_placement(
                        candidate, collection=release_collection
                    )
            except ReleaseAuthorityError as exc:
                raise PlacementResolutionError(str(exc)) from exc
        programme_index_sha, canonical_programmes = _load_programme_index(
            programme_index_path,
            expected_sha256=expected_programme_index_sha256,
        )
        profile_manifest_digests = {
            authority.profile_manifest_digest
            for authority in release.artifacts.values()
        }
        if len(profile_manifest_digests) != 1:
            raise PlacementResolutionError(
                "release subject manifests disagree on profile manifest digest"
            )
        embedding = release.models.get("embedding")
        if not isinstance(embedding, Mapping):
            raise PlacementResolutionError("release embedding model is absent")
        return cls(
            catalog_sha256=catalog_sha,
            corpus_manifest_sha256=manifest,
            placement_catalog_sha256=placement_catalog_sha,
            currentness_evidence_sha256=evidence_sha,
            candidate_inventory_sha256=candidate_inventory.sha256,
            mapping_sha256=mapping.sha256,
            release_manifest_sha256=release.sha256,
            release_pii_evidence_sha256=release.authorities["pii_evidence_sha256"],
            release_pii_policy_sha256=release.authorities["pii_policy_sha256"],
            release_rights_registry_sha256=release.authorities["rights_registry_sha256"],
            release_profile_manifest_digest=next(iter(profile_manifest_digests)),
            release_embedding_model_id=str(embedding["model_id"]),
            release_embedding_inventory_sha256=str(embedding["inventory_sha256"]),
            release_embedding_dimension=int(embedding["dimension"]),
            currentness_school_year=school_year,
            programme_index_sha256=programme_index_sha,
            _artifacts={
                str(key): value
                for key, value in artifacts.items()
                if isinstance(key, str) and isinstance(value, Mapping)
            },
            _currentness=currentness,
            _candidate_inventory=candidate_inventory,
            _mapping=mapping,
            _release=release,
            _profiles=dict(profile_registry),
            _collection_config=dict(collection_config),
            _canonical_programme_by_collection=canonical_programmes,
        )

    def resolve(
        self,
        *,
        content_sha256: str,
        collection: str,
        profile_version: str,
        school_year: str,
        source_placement_id: str | None = None,
        claimed_source_path: str | None = None,
        claimed_source_url: str | None = None,
        claimed_type_doc: str | None = None,
    ) -> VerifiedPedagogicalPlacement:
        sha = _require_sha(content_sha256, label="content SHA")
        release_artifact = self._release.artifact_for(
            collection=collection, content_sha256=sha
        )
        if release_artifact is None:
            raise PlacementResolutionError(
                "content is absent from the release-eligible allowlist"
            )
        allowed_placement_ids = release_artifact.expected_placement_ids
        if source_placement_id is None:
            if len(allowed_placement_ids) != 1:
                raise PlacementResolutionError(
                    "release artifact has ambiguous placements; source_placement_id is required"
                )
            selected_placement_id = next(iter(allowed_placement_ids))
        else:
            selected_placement_id = source_placement_id
            if selected_placement_id not in allowed_placement_ids:
                raise PlacementResolutionError(
                    "source placement identity is absent from the release allowlist"
                )
        currentness = self._currentness.get(sha)
        if currentness is None:
            raise PlacementResolutionError(f"content {sha} has no currentness evidence")
        if school_year != self.currentness_school_year:
            raise PlacementResolutionError("requested school year differs from currentness evidence")

        artifact = self._artifacts.get(sha)
        if not isinstance(artifact, Mapping) or artifact.get("sha256") != sha:
            raise PlacementResolutionError("content is absent from the sealed catalog")
        physical_objects = artifact.get("physical_objects")
        placements = artifact.get("pedagogical_placements")
        if not isinstance(physical_objects, list) or not physical_objects:
            raise PlacementResolutionError("artifact has no physical object")
        if not isinstance(placements, list) or not placements:
            raise PlacementResolutionError("artifact has no pedagogical placement")
        if artifact.get("physical_object_count") != len(physical_objects):
            raise PlacementResolutionError("artifact physical object count differs")
        if artifact.get("pedagogical_placement_count") != len(placements):
            raise PlacementResolutionError("artifact placement count differs")
        matching_physical = [
            raw
            for raw in physical_objects
            if isinstance(raw, Mapping)
            and raw.get("content_sha256") == sha
            and raw.get("path") == release_artifact.source_path
        ]
        matching_placements = [
            raw
            for raw in placements
            if isinstance(raw, Mapping)
            and raw.get("content_sha256") == sha
            and raw.get("scope_path") == selected_placement_id
        ]
        if len(matching_physical) != 1:
            raise PlacementResolutionError(
                "release source path has no unique sealed physical object"
            )
        if len(matching_placements) != 1:
            raise PlacementResolutionError(
                "release placement identity has no unique catalog placement"
            )
        physical = matching_physical[0]
        placement = matching_placements[0]
        if not isinstance(physical, Mapping) or not isinstance(placement, Mapping):
            raise PlacementResolutionError("artifact placement records are malformed")
        if physical.get("content_sha256") != sha or placement.get("content_sha256") != sha:
            raise PlacementResolutionError("catalog content SHA differs")
        source_path = physical.get("path")
        if not isinstance(source_path, str) or source_path != currentness.exact_path:
            raise PlacementResolutionError("currentness path differs from sealed catalog path")
        if claimed_source_path is not None and claimed_source_path != source_path:
            raise PlacementResolutionError("claimed source path differs from sealed catalog")
        if placement.get("level") != currentness.external_level:
            raise PlacementResolutionError("currentness level differs from catalog placement")
        if placement.get("subject") != currentness.subject:
            raise PlacementResolutionError("currentness subject differs from catalog placement")

        inventory_candidates = [
            candidate
            for candidate in self._candidate_inventory.candidates_for(sha)
            if candidate.source_placement_id == selected_placement_id
        ]
        if len(inventory_candidates) != 1:
            raise PlacementResolutionError(
                "release placement has no unique candidate inventory record"
            )
        inventory_candidate: CandidatePlacement = inventory_candidates[0]
        catalog_facts = {
            "level": inventory_candidate.external_level,
            "scope": inventory_candidate.external_scope,
            "subject": inventory_candidate.external_subject,
            "document_type": inventory_candidate.external_document_type,
            "source_url": inventory_candidate.source_url,
        }
        if any(placement.get(field) != value for field, value in catalog_facts.items()):
            raise PlacementResolutionError(
                "candidate inventory differs from the sealed catalog placement"
            )
        try:
            mapping: PedagogicalMapping = self._mapping.resolve_placement(
                inventory_candidate, collection=collection
            )
            type_doc = self._mapping.resolve_type_doc(
                inventory_candidate.external_document_type
            )
        except ReleaseAuthorityError as exc:
            raise PlacementResolutionError(str(exc)) from exc
        profile = select_profile(
            self._profiles, collection=collection, profile_version=profile_version
        )
        if (
            release_artifact.profile_version != profile.profile_version
            or release_artifact.profile_fingerprint != profile_fingerprint(profile)
        ):
            raise PlacementResolutionError(
                "runtime profile differs from the release manifest profile"
            )
        source_url = placement.get("source_url")
        if not isinstance(source_url, str) or not source_url:
            raise PlacementResolutionError("catalog placement source URL is absent")
        if claimed_source_url is not None and claimed_source_url != source_url:
            raise PlacementResolutionError("claimed source URL differs from sealed catalog")
        if claimed_type_doc is not None and claimed_type_doc != type_doc.value:
            raise PlacementResolutionError("claimed document type differs from governed mapping")
        if urlparse(source_url).hostname not in profile.allowed_domains:
            raise PlacementResolutionError("catalog source URL is outside profile domains")
        if (
            profile.scope.collection != mapping.nexus_collection
            or profile.scope.niveau is not mapping.nexus_niveau
            or profile.scope.voie is not mapping.nexus_voie
            or profile.scope.matiere != mapping.nexus_matiere
            or profile.scope.school_year != school_year
        ):
            raise PlacementResolutionError("profile scope differs from governed placement")
        if not str(profile.scope.programme_version).strip():
            raise PlacementResolutionError("profile programme version is absent")
        canonical_programme = self._canonical_programme_by_collection.get(collection)
        if (
            canonical_programme != str(profile.scope.programme_version)
            or release_artifact.programme_version != canonical_programme
        ):
            raise PlacementResolutionError(
                "profile differs from the canonical programme version"
            )

        raw_collections = self._collection_config.get("collections")
        collection_entry = (
            raw_collections.get(collection)
            if isinstance(raw_collections, Mapping)
            else None
        )
        if not isinstance(collection_entry, Mapping):
            raise PlacementResolutionError("Nexus collection is not declared")
        nexus_domain = collection_entry.get("domain")
        if not isinstance(nexus_domain, str) or not nexus_domain.strip():
            raise PlacementResolutionError("declared collection domain is absent")
        catalogue_voie = collection_entry.get("voie")
        if (
            collection_entry.get("niveau") != mapping.nexus_niveau.value
            or collection_entry.get("matiere") != mapping.nexus_matiere
            or collection_entry.get("statut") != mapping.nexus_statut_enseignement
            or catalogue_voie != mapping.nexus_voie.value
        ):
            raise PlacementResolutionError("declared collection differs from governed placement")

        niveau_conformity = (
            placement.get("level") == currentness.external_level
            and mapping.external_level == currentness.external_level
            and profile.scope.niveau is mapping.nexus_niveau
        )
        voie_conformity = (
            str(placement.get("scope", "")).startswith("college/")
            and mapping.nexus_voie is Voie.college
            and profile.scope.voie is Voie.college
        )
        matiere_conformity = (
            placement.get("subject") == currentness.subject
            and mapping.external_subject == currentness.subject
            and profile.scope.matiere == mapping.nexus_matiere
        )
        programme_conformity = (
            currentness.effective_currentness == "actuel"
            and currentness.current_for_school_year == school_year
            and profile.scope.school_year == school_year
            and str(profile.scope.programme_version) == canonical_programme
        )

        return VerifiedPedagogicalPlacement(
            content_sha256=sha,
            source_path=source_path,
            source_url=source_url,
            source_placement_id=selected_placement_id,
            external_level=mapping.external_level,
            external_subject=mapping.external_subject,
            external_scope=mapping.external_scope,
            external_document_type=inventory_candidate.external_document_type,
            effective_currentness=currentness.effective_currentness,
            nexus_collection=mapping.nexus_collection,
            nexus_niveau=mapping.nexus_niveau,
            nexus_voie=mapping.nexus_voie,
            nexus_matiere=mapping.nexus_matiere,
            nexus_statut_enseignement=mapping.nexus_statut_enseignement,
            nexus_programme_version=str(profile.scope.programme_version),
            nexus_domain=nexus_domain,
            nexus_scope=profile.scope,
            type_doc=type_doc,
            profile_version=profile.profile_version,
            profile_fingerprint=profile_fingerprint(profile),
            corpus_manifest_sha256=self.corpus_manifest_sha256,
            catalog_sha256=self.catalog_sha256,
            placement_catalog_sha256=self.placement_catalog_sha256,
            currentness_evidence_sha256=self.currentness_evidence_sha256,
            programme_index_sha256=self.programme_index_sha256,
            niveau_conformity=niveau_conformity,
            voie_conformity=voie_conformity,
            matiere_conformity=matiere_conformity,
            programme_conformity=programme_conformity,
        )


def to_eligible_placement(
    placement: VerifiedPedagogicalPlacement,
    *,
    resource_id: UUID,
    current_profile_manifest_digest: str,
) -> EligiblePlacement:
    """Convertir avec le digest du manifest de profils, jamais celui du corpus."""
    return EligiblePlacement(
        resource_id=resource_id,
        scope=placement.nexus_scope,
        statut_enseignement=placement.nexus_statut_enseignement,
        domain=placement.nexus_domain,
        source_scope=placement.external_scope,
        source_placement_id=placement.source_placement_id,
        source_path=placement.source_path,
        source_uri=placement.source_url,
        current_profile_fingerprint=placement.profile_fingerprint,
        current_manifest_digest=current_profile_manifest_digest,
        currentness="current",
    )


__all__ = [
    "CURRENTNESS_EVIDENCE_KIND",
    "PlacementResolutionError",
    "VerifiedPedagogicalPlacement",
    "VerifiedPedagogicalPlacementResolver",
    "to_eligible_placement",
]
