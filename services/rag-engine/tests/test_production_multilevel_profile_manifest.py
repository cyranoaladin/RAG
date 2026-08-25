"""Dispatch explicite staging/production du resolver multi-niveaux."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from ingestor.ingestion_profiles.manifest import verify_profile_manifest
from ingestor.ingestion_profiles.registry import load_profile_registry
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
