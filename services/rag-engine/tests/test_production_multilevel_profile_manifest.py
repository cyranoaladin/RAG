"""Dispatch explicite staging/production du resolver multi-niveaux."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ingestor.ingestion_profiles.manifest import verify_profile_manifest
from ingestor.ingestion_profiles.registry import load_profile_registry
from ingestor.ingestion_worker.multilevel_runtime_authority import (
    MultilevelRuntimeAuthorityInputs,
    load_multilevel_runtime_authorities,
)
from ingestor.multilevel_evidence import load_multilevel_candidate_inventory
from ingestor.multilevel_verified_placement import (
    MultilevelPlacementResolutionError,
    production_profile_manifest_verification,
    require_profile_manifest_authority,
)
from ingestor.staging_profile_manifest import verify_staging_profile_manifest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_PROFILES = ENGINE_ROOT / "configs/ingestion_profiles"
PRODUCTION_MANIFEST = ENGINE_ROOT / "configs/ingestion_manifest.yml"
STAGING_PROFILES = PRODUCTION_PROFILES / "staging/multilevel"
STAGING_MANIFEST = PRODUCTION_PROFILES / "staging/multilevel_manifest.json"
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
RELEASE_ROOT = (
    REPOSITORY_ROOT
    / "services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_production_manifest_uses_semantic_fingerprint_not_raw_yaml_sha() -> None:
    registry = load_profile_registry(PRODUCTION_PROFILES)
    verified = verify_profile_manifest(registry, PRODUCTION_MANIFEST)
    authority = production_profile_manifest_verification(verified)
    raw_sha = hashlib.sha256(PRODUCTION_MANIFEST.read_bytes()).hexdigest()

    assert authority.manifest_sha256 == verified.manifest_fingerprint
    assert authority.manifest_sha256 != raw_sha
    assert authority.declared_count == 18
    require_profile_manifest_authority(
        authority, environment="production", profile_count=len(registry)
    )


def test_staging_and_production_manifest_schemas_cannot_cross() -> None:
    staging_registry = load_profile_registry(STAGING_PROFILES)
    staging = verify_staging_profile_manifest(staging_registry, STAGING_MANIFEST)
    production_registry = load_profile_registry(PRODUCTION_PROFILES)
    production = production_profile_manifest_verification(
        verify_profile_manifest(production_registry, PRODUCTION_MANIFEST)
    )

    with pytest.raises(MultilevelPlacementResolutionError, match="production"):
        require_profile_manifest_authority(
            staging, environment="production", profile_count=len(staging_registry)
        )
    with pytest.raises(MultilevelPlacementResolutionError, match="staging"):
        require_profile_manifest_authority(
            production, environment="rehearsal", profile_count=len(production_registry)
        )


def test_real_production_authorities_resolve_all_twenty_six_placements() -> None:
    bindings = json.loads((RELEASE_ROOT / "authority_bindings.json").read_text())[
        "bindings"
    ]

    def bound(name: str) -> tuple[Path, str]:
        binding = bindings[name]
        return REPOSITORY_ROOT / binding["path"], binding["file_sha256"]

    candidate_path, candidate_sha = bound("candidate_inventory_sha256")
    currentness_path, currentness_sha = bound("currentness_evidence_sha256")
    levels_path, levels_sha = bound("level_mapping_sha256")
    subjects_path, subjects_sha = bound("subject_mapping_sha256")
    types_path, types_sha = bound("document_type_mapping_sha256")
    programme_path, programme_sha = bound("programme_registry_sha256")
    profile_manifest_path, profile_manifest_sha = bound("profile_manifest_sha256")
    pii_path, pii_sha = bound("pii_evidence_sha256")
    rights_path, rights_sha = bound("rights_registry_sha256")
    release_path = RELEASE_ROOT / "production-profile-gate.release.json"
    collection_config = ENGINE_ROOT / "configs/rag_collections.yml"
    profiles = load_profile_registry(PRODUCTION_PROFILES)
    by_collection = {profile.scope.collection: profile for profile in profiles.values()}
    inputs = MultilevelRuntimeAuthorityInputs(
        candidate_inventory_path=candidate_path,
        candidate_inventory_sha256=candidate_sha,
        currentness_evidence_path=currentness_path,
        currentness_evidence_sha256=currentness_sha,
        levels_mapping_path=levels_path,
        levels_mapping_sha256=levels_sha,
        subjects_mapping_path=subjects_path,
        subjects_mapping_sha256=subjects_sha,
        document_types_mapping_path=types_path,
        document_types_mapping_sha256=types_sha,
        release_manifest_path=release_path,
        release_manifest_sha256=_sha256(release_path),
        programme_registry_path=programme_path,
        programme_registry_sha256=programme_sha,
        profile_manifest_path=profile_manifest_path,
        profile_manifest_sha256=profile_manifest_sha,
        collection_config_path=collection_config,
        collection_config_sha256=_sha256(collection_config),
        pii_evidence_path=pii_path,
        pii_evidence_sha256=pii_sha,
        rights_evidence_path=rights_path,
        rights_evidence_sha256=rights_sha,
        corpus_manifest_sha256=(
            "d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e"
        ),
        repository_root=REPOSITORY_ROOT,
    )

    authorities = load_multilevel_runtime_authorities(
        inputs, profile_registry=profiles, environment="production"
    )
    inventory = load_multilevel_candidate_inventory(
        candidate_path, expected_sha256=candidate_sha
    )
    resolved = []
    for candidate in inventory.placements:
        profile = by_collection[candidate.collection]
        placement = authorities.placement_resolver.resolve(
            content_sha256=candidate.content_sha256,
            collection=candidate.collection,
            profile_version=profile.profile_version,
            school_year="2026-2027",
            source_placement_id=candidate.source_placement_id,
            claimed_source_path=candidate.physical_path,
        )
        authorities.pii_evidence_registry.verify_content_clearance(
            candidate.content_sha256
        )
        authorities.rights_evidence_registry.resolve_rights(
            content_sha256=candidate.content_sha256,
            source_path=candidate.physical_path,
        )
        resolved.append(placement)

    assert len(resolved) == 26
    assert len({item.content_sha256 for item in resolved}) == 26
    assert len({item.nexus_collection for item in resolved}) == 18
