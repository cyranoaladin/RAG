"""Adaptateur rag-engine local de la projection de scope de release."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from nexus_contracts.authorization_set import (
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV1,
)
from nexus_contracts.ingestion import CollectionProfile

from ingestor.ingestion_profiles.manifest import manifest_fingerprint
from ingestor.ingestion_profiles.registry import profile_fingerprint
from ingestor.ingestion_profiles.startup_gate import (
    StartupGateResult,
    enforce_production_manifest_gate,
)
from ingestor.release_scope_placement import (
    ReleaseScopePlacementVerificationError,
    verified_profile_facts,
    verify_release_scope_placement,
)

SHA_A = "a" * 64


def _scope() -> dict[str, object]:
    return {
        "tenant": "libre_terminale",
        "collection": "collection_maths",
        "niveau": "terminale",
        "voie": "generale",
        "matiere": "mathematiques",
        "candidat": "libre",
        "audience": ["libre", "tous"],
        "visibility": "internal",
        "school_year": "2026-2027",
        "programme_version": "BOEN_test_v1",
    }


def _profile(*, scope: dict[str, object] | None = None, enabled: bool = True) -> dict[str, object]:
    return {
        "profile_version": "v1",
        "enabled": enabled,
        "scope": scope or _scope(),
        "title": "Profil de test",
        "owner": "equipe-test",
        "expected_topics": ["sujet"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["education.gouv.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 10,
        "max_documents_per_run": 20,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.6,
    }


def _gate(
    tmp_path: Path,
    *,
    scope: dict[str, object] | None = None,
    enabled: bool = True,
) -> StartupGateResult:
    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    profile_document = _profile(scope=scope, enabled=enabled)
    (profiles_dir / "maths.yml").write_text(yaml.safe_dump(profile_document), encoding="utf-8")
    profile = CollectionProfile.model_validate(profile_document)
    manifest_document = {
        "manifest_version": "1",
        "provenance": "test",
        "generated_at": "2026-08-23T00:00:00Z",
        "profiles": [
            {
                "collection": "collection_maths",
                "profile_version": "v1",
                "fingerprint": profile_fingerprint(profile),
                "approved_by": "test-authority",
                "approved_at": "2026-08-23T00:00:00Z",
            }
        ],
    }
    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_text(yaml.safe_dump(manifest_document), encoding="utf-8")
    gate = enforce_production_manifest_gate(profiles_dir, manifest_path)
    assert gate.manifest.manifest_fingerprint == manifest_fingerprint(manifest_document)
    return gate


def _placement(
    gate: StartupGateResult, *, scope: dict[str, object] | None = None
) -> ReleaseScopePlacementV1:
    fact = verified_profile_facts(gate)[0]
    return ReleaseScopePlacementV1.build(
        profile_manifest_digest=gate.manifest.manifest_fingerprint,
        placements=(
            ReleaseScopePlacementEntryV1.model_validate(
                {
                    "content_sha256": SHA_A,
                    "profile_id": fact.profile_id,
                    "profile_version": fact.profile_version,
                    "profile_fingerprint": fact.profile_fingerprint,
                    "scope": scope or fact.scope,
                }
            ),
        ),
    )


def test_adapter_projects_facts_from_engine_verified_registry(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    facts = verified_profile_facts(gate)

    assert len(facts) == 1
    assert facts[0].profile_id == "collection_maths"
    assert facts[0].profile_version == "v1"
    assert facts[0].scope == gate.registry[("collection_maths", "v1")].scope


def test_adapter_accepts_exact_canonical_placement(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    placement = _placement(gate)

    verified = verify_release_scope_placement(
        raw=placement.canonical_bytes(),
        expected_digest=placement.digest(),
        expected_profile_manifest_digest=gate.manifest.manifest_fingerprint,
        gate=gate,
    )

    assert verified == placement


def test_adapter_refuses_changed_profile_manifest(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    placement = _placement(gate).model_copy(update={"profile_manifest_digest": "f" * 64})

    with pytest.raises(ReleaseScopePlacementVerificationError, match="PROFILE_MANIFEST_MISMATCH"):
        verify_release_scope_placement(
            raw=placement.canonical_bytes(),
            expected_digest=placement.digest(),
            expected_profile_manifest_digest="f" * 64,
            gate=gate,
        )


def test_adapter_refuses_changed_scope_even_with_matching_placement_digest(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path)
    changed_scope = _scope()
    changed_scope["matiere"] = "physique_chimie"
    placement = _placement(gate, scope=changed_scope)

    with pytest.raises(ReleaseScopePlacementVerificationError, match="PROFILE_SCOPE_MISMATCH"):
        verify_release_scope_placement(
            raw=placement.canonical_bytes(),
            expected_digest=placement.digest(),
            expected_profile_manifest_digest=gate.manifest.manifest_fingerprint,
            gate=gate,
        )


def test_adapter_refuses_changed_placement_digest(tmp_path: Path) -> None:
    gate = _gate(tmp_path)
    placement = _placement(gate)

    with pytest.raises(ReleaseScopePlacementVerificationError, match="PLACEMENT_DIGEST_MISMATCH"):
        verify_release_scope_placement(
            raw=placement.canonical_bytes(),
            expected_digest="0" * 64,
            expected_profile_manifest_digest=gate.manifest.manifest_fingerprint,
            gate=gate,
        )


def test_adapter_refuses_disabled_profile_from_real_startup_gate(
    tmp_path: Path,
) -> None:
    gate = _gate(tmp_path, enabled=False)

    with pytest.raises(ReleaseScopePlacementVerificationError, match="PROFILE_DISABLED"):
        verified_profile_facts(gate)
