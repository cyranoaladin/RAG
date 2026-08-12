"""Bootstrap fail-closed des autorités de release multi-niveaux staging."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ingestor.collection_config import load_collection_config
from ingestor.ingestion_control.sealed_evidence import (
    VerifiedPIIEvidenceRegistry,
    VerifiedRightsEvidenceRegistry,
)
from ingestor.ingestion_profiles.registry import ProfileRegistry
from ingestor.multilevel_evidence import (
    load_multilevel_candidate_inventory,
    load_multilevel_currentness,
)
from ingestor.multilevel_mapping import load_multilevel_mapping
from ingestor.multilevel_verified_placement import (
    MultilevelVerifiedPedagogicalPlacementResolver,
    load_multilevel_release_eligibility,
)
from ingestor.programme_registry import load_programme_index_registry
from ingestor.staging_profile_manifest import verify_staging_profile_manifest
from ingestor.wave0_release import require_file_digest

from .runtime_authority import GovernedRuntimeAuthorities, RuntimeAuthorityStartupError


@dataclass(frozen=True)
class MultilevelRuntimeAuthorityInputs:
    candidate_inventory_path: Path
    candidate_inventory_sha256: str
    currentness_evidence_path: Path
    currentness_evidence_sha256: str
    levels_mapping_path: Path
    levels_mapping_sha256: str
    subjects_mapping_path: Path
    subjects_mapping_sha256: str
    document_types_mapping_path: Path
    document_types_mapping_sha256: str
    release_manifest_path: Path
    release_manifest_sha256: str
    programme_registry_path: Path
    programme_registry_sha256: str
    profile_manifest_path: Path
    profile_manifest_sha256: str
    collection_config_path: Path
    collection_config_sha256: str
    pii_evidence_path: Path
    pii_evidence_sha256: str
    rights_evidence_path: Path
    rights_evidence_sha256: str
    corpus_manifest_sha256: str
    repository_root: Path


def load_multilevel_runtime_authorities(
    inputs: MultilevelRuntimeAuthorityInputs,
    *,
    profile_registry: ProfileRegistry,
) -> GovernedRuntimeAuthorities:
    """Construire une seule autorité cohérente avant toute connexion DB."""
    try:
        collection_config_sha = require_file_digest(
            inputs.collection_config_path,
            inputs.collection_config_sha256,
            label="runtime collection config",
        )
        profile_manifest_sha = require_file_digest(
            inputs.profile_manifest_path,
            inputs.profile_manifest_sha256,
            label="multilevel staging profile manifest",
        )
        inventory = load_multilevel_candidate_inventory(
            inputs.candidate_inventory_path,
            expected_sha256=inputs.candidate_inventory_sha256,
        )
        currentness = load_multilevel_currentness(
            inputs.currentness_evidence_path,
            expected_sha256=inputs.currentness_evidence_sha256,
            candidate_inventory=inventory,
        )
        mapping = load_multilevel_mapping(
            levels_path=inputs.levels_mapping_path,
            expected_levels_sha256=inputs.levels_mapping_sha256,
            subjects_path=inputs.subjects_mapping_path,
            expected_subjects_sha256=inputs.subjects_mapping_sha256,
            document_types_path=inputs.document_types_mapping_path,
            expected_document_types_sha256=inputs.document_types_mapping_sha256,
        )
        programme = load_programme_index_registry(
            registry_path=inputs.programme_registry_path,
            expected_registry_sha256=inputs.programme_registry_sha256,
            repository_root=inputs.repository_root,
        )
        profile_manifest = verify_staging_profile_manifest(
            profile_registry, inputs.profile_manifest_path
        )
        if profile_manifest.manifest_sha256 != profile_manifest_sha:
            raise RuntimeAuthorityStartupError("profile manifest digest differs")
        release = load_multilevel_release_eligibility(
            inputs.release_manifest_path,
            expected_sha256=inputs.release_manifest_sha256,
        )
        resolver = MultilevelVerifiedPedagogicalPlacementResolver.from_authorities(
            candidate_inventory=inventory,
            currentness=currentness,
            mapping=mapping,
            profiles=profile_registry,
            profile_manifest=profile_manifest,
            programme_registry=programme,
            collection_config=load_collection_config(inputs.collection_config_path),
            release_eligibility=release,
        )
        pii = VerifiedPIIEvidenceRegistry.load(
            inputs.pii_evidence_path,
            expected_evidence_sha256=inputs.pii_evidence_sha256,
            expected_corpus_manifest_sha256=inputs.corpus_manifest_sha256,
        )
        rights = VerifiedRightsEvidenceRegistry.load(
            inputs.rights_evidence_path,
            expected_registry_sha256=inputs.rights_evidence_sha256,
            expected_corpus_manifest_sha256=inputs.corpus_manifest_sha256,
        )
    except Exception as exc:
        if isinstance(exc, RuntimeAuthorityStartupError):
            raise
        raise RuntimeAuthorityStartupError(str(exc)) from exc

    if resolver.release_pii_evidence_sha256 != pii.evidence_sha256:
        raise RuntimeAuthorityStartupError("release PII evidence digest differs")
    if resolver.release_pii_policy_sha256 != pii.policy_sha256:
        raise RuntimeAuthorityStartupError("release PII policy digest differs")
    if resolver.release_rights_registry_sha256 != rights.registry_sha256:
        raise RuntimeAuthorityStartupError("release rights registry digest differs")
    return GovernedRuntimeAuthorities(
        placement_resolver=resolver,
        pii_evidence_registry=pii,
        rights_evidence_registry=rights,
        collection_config_sha256=collection_config_sha,
    )


__all__ = [
    "MultilevelRuntimeAuthorityInputs",
    "load_multilevel_runtime_authorities",
]
