"""Résolution pédagogique multi-niveaux fondée uniquement sur des autorités scellées."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from nexus_contracts.document import Voie

from .collection_config import CollectionConfigError, canonicalize_catalogue_voie
from .ingestion_profiles.manifest import ManifestVerification
from .ingestion_profiles.registry import (
    ProfileRegistry,
    ProfileRegistryError,
    profile_fingerprint,
    select_profile,
)
from .multilevel_evidence import (
    MultilevelCandidateInventory,
    MultilevelCandidatePlacement,
    MultilevelCurrentnessEvidence,
    MultilevelEvidenceError,
)
from .multilevel_mapping import ClosedMultilevelMapping, MultilevelMappingError
from .programme_registry import ProgrammeIndexRegistry, ProgrammeRegistryError
from .release_readiness import ReleaseReadinessError, load_release_expectation
from .staging_profile_manifest import StagingProfileManifestVerification
from .verified_pedagogical_placement import VerifiedPedagogicalPlacement

_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")


class MultilevelPlacementResolutionError(RuntimeError):
    """Un placement multi-niveaux n'est pas exactement gouverné."""


@dataclass(frozen=True)
class ProductionProfileManifestVerification:
    """Identité sémantique normalisée du manifeste production partagé."""

    manifest_sha256: str
    declared_count: int
    authority_mode: str = "PRODUCTION_PROFILE_MANIFEST"


def production_profile_manifest_verification(
    verification: ManifestVerification,
) -> ProductionProfileManifestVerification:
    """Adapter le contrat production sans confondre fingerprint et SHA YAML."""
    return ProductionProfileManifestVerification(
        manifest_sha256=_require_sha256(
            verification.manifest_fingerprint,
            label="production profile manifest fingerprint",
        ),
        declared_count=verification.declared_count,
    )


def require_profile_manifest_authority(
    verification: StagingProfileManifestVerification
    | ProductionProfileManifestVerification,
    *,
    environment: str,
    profile_count: int,
) -> None:
    """Refuser explicitement tout croisement staging/production."""
    if environment == "production":
        if not isinstance(verification, ProductionProfileManifestVerification):
            raise MultilevelPlacementResolutionError(
                "production requires a production profile manifest"
            )
        if verification.authority_mode != "PRODUCTION_PROFILE_MANIFEST":
            raise MultilevelPlacementResolutionError(
                "production profile manifest authority is invalid"
            )
    elif environment == "rehearsal":
        if not isinstance(verification, StagingProfileManifestVerification):
            raise MultilevelPlacementResolutionError(
                "staging rehearsal requires a staging profile manifest"
            )
        if (
            verification.authority_mode != "STAGING_LOCAL_GITHUB_ONLY"
            or verification.production_approval is not False
        ):
            raise MultilevelPlacementResolutionError(
                "staging profile manifest authority is invalid"
            )
    else:
        raise MultilevelPlacementResolutionError(
            "profile manifest environment must be rehearsal or production"
        )
    if verification.declared_count != profile_count:
        raise MultilevelPlacementResolutionError(
            "profile manifest count differs from loaded registry"
        )


def _require_sha256(value: object, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise MultilevelPlacementResolutionError(
            f"{label} must be a lowercase SHA-256"
        )
    return value


def _require_nonempty(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MultilevelPlacementResolutionError(f"{label} is absent")
    return value


@dataclass(frozen=True, order=True)
class MultilevelReleasePlacement:
    collection: str
    content_sha256: str
    source_placement_id: str
    nexus_statut_enseignement: str
    programme_version: str
    profile_version: str
    profile_fingerprint: str
    profile_manifest_digest: str

    def __post_init__(self) -> None:
        _require_nonempty(self.collection, label="release collection")
        _require_sha256(self.content_sha256, label="release content SHA")
        _require_nonempty(
            self.source_placement_id, label="release source placement identity"
        )
        _require_nonempty(
            self.nexus_statut_enseignement,
            label="release teaching status",
        )
        _require_nonempty(self.programme_version, label="release programme version")
        _require_nonempty(self.profile_version, label="release profile version")
        _require_sha256(self.profile_fingerprint, label="release profile fingerprint")
        _require_sha256(
            self.profile_manifest_digest, label="release profile manifest digest"
        )


@dataclass(frozen=True)
class MultilevelReleaseEligibility:
    """Allowlist injectée; son loader sera ajouté avec le schéma agrégat final."""

    manifest_sha256: str
    candidate_inventory_sha256: str
    currentness_evidence_sha256: str
    programme_registry_sha256: str
    profile_manifest_sha256: str
    levels_mapping_sha256: str
    subjects_mapping_sha256: str
    document_types_mapping_sha256: str
    pii_evidence_sha256: str
    pii_policy_sha256: str
    rights_registry_sha256: str
    embedding_model_id: str
    embedding_inventory_sha256: str
    embedding_dimension: int
    reranker_model_id: str
    reranker_inventory_sha256: str
    placements: frozenset[MultilevelReleasePlacement]

    def __post_init__(self) -> None:
        for field in (
            "manifest_sha256",
            "candidate_inventory_sha256",
            "currentness_evidence_sha256",
            "programme_registry_sha256",
            "profile_manifest_sha256",
            "levels_mapping_sha256",
            "subjects_mapping_sha256",
            "document_types_mapping_sha256",
            "pii_evidence_sha256",
            "pii_policy_sha256",
            "rights_registry_sha256",
            "embedding_inventory_sha256",
            "reranker_inventory_sha256",
        ):
            _require_sha256(getattr(self, field), label=field)
        _require_nonempty(self.embedding_model_id, label="embedding model identity")
        _require_nonempty(self.reranker_model_id, label="reranker model identity")
        if self.embedding_dimension != 1024:
            raise MultilevelPlacementResolutionError("embedding dimension is not canonical")
        if not self.placements:
            raise MultilevelPlacementResolutionError("release allowlist is empty")
        if any(
            item.profile_manifest_digest != self.profile_manifest_sha256
            for item in self.placements
        ):
            raise MultilevelPlacementResolutionError(
                "release profile manifest digest differs from allowlist authority"
            )


def load_multilevel_release_eligibility(
    path: Path, *, expected_sha256: str
) -> MultilevelReleaseEligibility:
    """Charger l'allowlist exacte depuis l'aggregate validé par readiness."""
    try:
        expectation = load_release_expectation(path, expected_sha256)
        raw = path.read_bytes()
        aggregate = json.loads(raw)
    except (ReleaseReadinessError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MultilevelPlacementResolutionError(
            "multilevel release aggregate cannot be loaded"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise MultilevelPlacementResolutionError("multilevel release aggregate digest differs")
    if not isinstance(aggregate, Mapping) or aggregate.get("release_kind") != (
        "MULTILEVEL_AGGREGATE_RELEASE_V1"
    ):
        raise MultilevelPlacementResolutionError("multilevel release aggregate kind is invalid")
    authorities = aggregate.get("authorities")
    if not isinstance(authorities, Mapping):
        raise MultilevelPlacementResolutionError("multilevel release authorities are absent")
    placements: set[MultilevelReleasePlacement] = set()
    for artifact in expectation.artifacts:
        for raw_placement in artifact.placements:
            placements.add(
                MultilevelReleasePlacement(
                    collection=artifact.collection,
                    content_sha256=artifact.content_sha256,
                    source_placement_id=_require_nonempty(
                        raw_placement.get("source_placement_id"),
                        label="release source placement identity",
                    ),
                    nexus_statut_enseignement=_require_nonempty(
                        raw_placement.get("statut_enseignement"),
                        label="release teaching status",
                    ),
                    programme_version=artifact.programme_version,
                    profile_version=artifact.profile_version,
                    profile_fingerprint=artifact.profile_fingerprint,
                    profile_manifest_digest=artifact.profile_manifest_digest,
                )
            )
    return MultilevelReleaseEligibility(
        manifest_sha256=_require_sha256(expected_sha256, label="release manifest SHA"),
        candidate_inventory_sha256=_require_sha256(
            authorities.get("candidate_inventory_sha256"),
            label="candidate inventory SHA",
        ),
        currentness_evidence_sha256=_require_sha256(
            authorities.get("currentness_evidence_sha256"),
            label="currentness evidence SHA",
        ),
        programme_registry_sha256=_require_sha256(
            authorities.get("programme_registry_sha256"),
            label="programme registry SHA",
        ),
        profile_manifest_sha256=_require_sha256(
            authorities.get("profile_manifest_sha256"),
            label="profile manifest SHA",
        ),
        levels_mapping_sha256=_require_sha256(
            authorities.get("level_mapping_sha256"),
            label="levels mapping SHA",
        ),
        subjects_mapping_sha256=_require_sha256(
            authorities.get("subject_mapping_sha256"),
            label="subjects mapping SHA",
        ),
        document_types_mapping_sha256=_require_sha256(
            authorities.get("document_type_mapping_sha256"),
            label="document types mapping SHA",
        ),
        pii_evidence_sha256=_require_sha256(
            authorities.get("pii_evidence_sha256"), label="PII evidence SHA"
        ),
        pii_policy_sha256=_require_sha256(
            authorities.get("pii_policy_sha256"), label="PII policy SHA"
        ),
        rights_registry_sha256=_require_sha256(
            authorities.get("rights_registry_sha256"), label="rights registry SHA"
        ),
        embedding_model_id=expectation.embedding_model_id,
        embedding_inventory_sha256=expectation.embedding_inventory_sha256,
        embedding_dimension=expectation.embedding_dimension,
        reranker_model_id=expectation.reranker_model_id,
        reranker_inventory_sha256=expectation.reranker_inventory_sha256,
        placements=frozenset(placements),
    )


@dataclass(frozen=True)
class MultilevelVerifiedPedagogicalPlacementResolver:
    """Resolver compatible Worker A/B, sans règle métier liée à un SHA précis."""

    release_manifest_sha256: str
    release_profile_manifest_digest: str
    catalog_sha256: str
    corpus_manifest_sha256: str
    placement_catalog_sha256: str
    currentness_evidence_sha256: str
    candidate_inventory_sha256: str
    programme_index_sha256: str
    currentness_school_year: str
    _candidate_inventory: MultilevelCandidateInventory
    _currentness: MultilevelCurrentnessEvidence
    _mapping: ClosedMultilevelMapping
    _profiles: ProfileRegistry
    _programme_registry: ProgrammeIndexRegistry
    _collection_config: Mapping[str, object]
    _release_eligibility: MultilevelReleaseEligibility

    @property
    def release_pii_evidence_sha256(self) -> str:
        return self._release_eligibility.pii_evidence_sha256

    @property
    def release_pii_policy_sha256(self) -> str:
        return self._release_eligibility.pii_policy_sha256

    @property
    def release_rights_registry_sha256(self) -> str:
        return self._release_eligibility.rights_registry_sha256

    @property
    def release_embedding_model_id(self) -> str:
        return self._release_eligibility.embedding_model_id

    @property
    def release_embedding_inventory_sha256(self) -> str:
        return self._release_eligibility.embedding_inventory_sha256

    @property
    def release_embedding_dimension(self) -> int:
        return self._release_eligibility.embedding_dimension

    @classmethod
    def from_authorities(
        cls,
        *,
        candidate_inventory: MultilevelCandidateInventory,
        currentness: MultilevelCurrentnessEvidence,
        mapping: ClosedMultilevelMapping,
        profiles: ProfileRegistry,
        profile_manifest: StagingProfileManifestVerification
        | ProductionProfileManifestVerification,
        environment: str,
        programme_registry: ProgrammeIndexRegistry,
        collection_config: Mapping[str, object],
        release_eligibility: MultilevelReleaseEligibility,
    ) -> MultilevelVerifiedPedagogicalPlacementResolver:
        if currentness.school_year != candidate_inventory.school_year:
            raise MultilevelPlacementResolutionError(
                "currentness school year differs from candidate inventory"
            )
        if programme_registry.school_year != candidate_inventory.school_year:
            raise MultilevelPlacementResolutionError(
                "programme registry school year differs from candidate inventory"
            )
        bindings = {
            "candidate_inventory_sha256": candidate_inventory.sha256,
            "currentness_evidence_sha256": currentness.sha256,
            "programme_registry_sha256": programme_registry.sha256,
            "profile_manifest_sha256": profile_manifest.manifest_sha256,
            "levels_mapping_sha256": mapping.levels_sha256,
            "subjects_mapping_sha256": mapping.subjects_sha256,
            "document_types_mapping_sha256": mapping.document_types_sha256,
        }
        if any(
            getattr(release_eligibility, field) != expected
            for field, expected in bindings.items()
        ):
            raise MultilevelPlacementResolutionError(
                "release allowlist authority digest differs"
            )
        require_profile_manifest_authority(
            profile_manifest,
            environment=environment,
            profile_count=len(profiles),
        )
        candidate_keys = {
            (item.collection, item.content_sha256, item.source_placement_id)
            for item in candidate_inventory.placements
        }
        release_keys = {
            (item.collection, item.content_sha256, item.source_placement_id)
            for item in release_eligibility.placements
        }
        if environment == "production" and release_keys != candidate_keys:
            raise MultilevelPlacementResolutionError(
                "production release allowlist differs from candidate inventory"
            )
        if environment != "production" and not release_keys <= candidate_keys:
            raise MultilevelPlacementResolutionError(
                "release allowlist contains a placement absent from candidate inventory"
            )
        for collection, _version in profiles:
            if collection not in programme_registry.taxonomy_sha256_by_collection:
                raise MultilevelPlacementResolutionError(
                    f"collection {collection!r} has no sealed taxonomy"
                )
            try:
                programme_registry.programme_for(collection)
            except ProgrammeRegistryError as exc:
                raise MultilevelPlacementResolutionError(str(exc)) from exc
        return cls(
            release_manifest_sha256=release_eligibility.manifest_sha256,
            release_profile_manifest_digest=profile_manifest.manifest_sha256,
            catalog_sha256=candidate_inventory.sealed_catalog_sha256,
            corpus_manifest_sha256=candidate_inventory.corpus_manifest_sha256,
            placement_catalog_sha256=candidate_inventory.placement_catalog_sha256,
            currentness_evidence_sha256=currentness.sha256,
            candidate_inventory_sha256=candidate_inventory.sha256,
            programme_index_sha256=programme_registry.sha256,
            currentness_school_year=candidate_inventory.school_year,
            _candidate_inventory=candidate_inventory,
            _currentness=currentness,
            _mapping=mapping,
            _profiles=dict(profiles),
            _programme_registry=programme_registry,
            _collection_config=dict(collection_config),
            _release_eligibility=release_eligibility,
        )

    def _select_candidate(
        self,
        *,
        content_sha256: str,
        collection: str,
        source_placement_id: str | None,
    ) -> tuple[MultilevelCandidatePlacement, MultilevelReleasePlacement]:
        eligible = {
            item.source_placement_id: item
            for item in self._release_eligibility.placements
            if item.collection == collection and item.content_sha256 == content_sha256
        }
        if not eligible:
            raise MultilevelPlacementResolutionError(
                "content placement is absent from the release allowlist"
            )
        if source_placement_id is None:
            if len(eligible) != 1:
                raise MultilevelPlacementResolutionError(
                    "release placement is ambiguous; source_placement_id is required"
                )
            selected_id = next(iter(eligible))
        else:
            selected_id = source_placement_id
            if selected_id not in eligible:
                raise MultilevelPlacementResolutionError(
                    "source placement identity is absent from the release allowlist"
                )
        matches = tuple(
            candidate
            for candidate in self._candidate_inventory.placements_for(
                content_sha256=content_sha256, collection=collection
            )
            if candidate.source_placement_id == selected_id
        )
        if len(matches) != 1:
            raise MultilevelPlacementResolutionError(
                "release placement has no unique candidate inventory record"
            )
        return matches[0], eligible[selected_id]

    @staticmethod
    def _voie_for_scope(external_scope: str) -> Voie:
        if external_scope.startswith("college/"):
            return Voie.college
        if external_scope.startswith("lycee/"):
            return Voie.generale
        raise MultilevelPlacementResolutionError(
            "external scope has no governed Nexus voie"
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
        sha = _require_sha256(content_sha256, label="content SHA")
        if school_year != self.currentness_school_year:
            raise MultilevelPlacementResolutionError(
                "requested school year differs from governed authorities"
            )
        candidate, release_placement = self._select_candidate(
            content_sha256=sha,
            collection=collection,
            source_placement_id=source_placement_id,
        )
        try:
            currentness = self._currentness.for_content(sha)
        except MultilevelEvidenceError as exc:
            raise MultilevelPlacementResolutionError(str(exc)) from exc
        if currentness.decision != "CURRENT":
            raise MultilevelPlacementResolutionError(
                f"content currentness is {currentness.decision}, not CURRENT"
            )
        if (
            currentness.effective_currentness != "actuel"
            or currentness.exact_path != candidate.physical_path
            or collection not in currentness.collections
        ):
            raise MultilevelPlacementResolutionError(
                "currentness differs from the selected candidate"
            )
        if claimed_source_path is not None and claimed_source_path != candidate.physical_path:
            raise MultilevelPlacementResolutionError(
                "claimed source path differs from candidate inventory"
            )
        source_url = _require_nonempty(
            currentness.current_download_url, label="current download URL"
        )
        if claimed_source_url is not None and claimed_source_url != source_url:
            raise MultilevelPlacementResolutionError(
                "claimed source URL differs from current byte-identity authority"
            )
        try:
            mapped = self._mapping.resolve(
                external_level=candidate.external_level,
                external_subject=candidate.external_subject,
                external_document_type=candidate.external_document_type,
            )
            profile = select_profile(
                self._profiles,
                collection=collection,
                profile_version=profile_version,
            )
            canonical_programme = self._programme_registry.programme_for(collection)
        except (MultilevelMappingError, ProfileRegistryError, ProgrammeRegistryError) as exc:
            raise MultilevelPlacementResolutionError(str(exc)) from exc
        if claimed_type_doc is not None and claimed_type_doc != mapped.type_doc.value:
            raise MultilevelPlacementResolutionError(
                "claimed document type differs from governed mapping"
            )
        actual_profile_fingerprint = profile_fingerprint(profile)
        if release_placement.profile_version != profile.profile_version:
            raise MultilevelPlacementResolutionError(
                "release profile version differs from selected profile"
            )
        if release_placement.profile_fingerprint != actual_profile_fingerprint:
            raise MultilevelPlacementResolutionError(
                "release profile fingerprint differs from selected profile"
            )
        if release_placement.programme_version != canonical_programme:
            raise MultilevelPlacementResolutionError(
                "release programme version differs from canonical programme"
            )
        governed_voie = self._voie_for_scope(candidate.external_scope)
        if (
            urlparse(candidate.source_url).hostname not in profile.allowed_domains
            or urlparse(source_url).hostname not in profile.allowed_domains
        ):
            raise MultilevelPlacementResolutionError(
                "candidate source URL is outside profile domains"
            )
        raw_collections = self._collection_config.get("collections")
        collection_entry = (
            raw_collections.get(collection)
            if isinstance(raw_collections, Mapping)
            else None
        )
        if not isinstance(collection_entry, Mapping):
            raise MultilevelPlacementResolutionError("Nexus collection is not declared")
        try:
            configured_voie = canonicalize_catalogue_voie(collection_entry.get("voie"))
        except CollectionConfigError as exc:
            raise MultilevelPlacementResolutionError(str(exc)) from exc
        configured_statut = _require_nonempty(
            collection_entry.get("statut"), label="collection teaching status"
        )
        domain = _require_nonempty(
            collection_entry.get("domain"), label="collection domain"
        )
        profile_programme = str(profile.scope.programme_version)
        if configured_statut != release_placement.nexus_statut_enseignement:
            raise MultilevelPlacementResolutionError(
                "collection teaching status differs from release authority"
            )
        niveau_conformity = (
            profile.scope.collection == collection
            and profile.scope.niveau is mapped.niveau
            and collection_entry.get("niveau") == mapped.niveau.value
        )
        voie_conformity = (
            profile.scope.voie is governed_voie
            and configured_voie == governed_voie.value
            and (
                (candidate.external_scope.startswith("college/") and governed_voie is Voie.college)
                or (
                    candidate.external_scope.startswith("lycee/")
                    and governed_voie is Voie.generale
                )
            )
        )
        matiere_conformity = (
            self._mapping.subjects.get(candidate.external_subject) == mapped.matiere
            and profile.scope.matiere == mapped.matiere
            and collection_entry.get("matiere") == mapped.matiere
        )
        programme_conformity = (
            currentness.decision == "CURRENT"
            and currentness.effective_currentness == "actuel"
            and currentness.current_for_school_year == school_year
            and profile.scope.school_year == school_year
            and profile_programme == canonical_programme
            and self._programme_registry.school_year == school_year
        )
        if not all(
            (
                niveau_conformity,
                voie_conformity,
                matiere_conformity,
                programme_conformity,
            )
        ):
            raise MultilevelPlacementResolutionError(
                "governed pedagogical conformity is not exact"
            )
        return VerifiedPedagogicalPlacement(
            content_sha256=sha,
            source_path=candidate.physical_path,
            source_url=source_url,
            source_placement_id=candidate.source_placement_id,
            external_level=candidate.external_level,
            external_subject=candidate.external_subject,
            external_scope=candidate.external_scope,
            external_document_type=candidate.external_document_type,
            effective_currentness="actuel",
            nexus_collection=collection,
            nexus_niveau=mapped.niveau,
            nexus_voie=governed_voie,
            nexus_matiere=mapped.matiere,
            nexus_statut_enseignement=configured_statut,
            nexus_programme_version=canonical_programme,
            nexus_domain=domain,
            nexus_scope=profile.scope,
            type_doc=mapped.type_doc,
            profile_version=profile.profile_version,
            profile_fingerprint=actual_profile_fingerprint,
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


__all__ = [
    "MultilevelPlacementResolutionError",
    "MultilevelReleaseEligibility",
    "MultilevelReleasePlacement",
    "MultilevelVerifiedPedagogicalPlacementResolver",
    "load_multilevel_release_eligibility",
]
