"""Dispatch explicite staging/production du resolver multi-niveaux."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ingestor.ingestion_profiles.manifest import verify_profile_manifest
from ingestor.ingestion_profiles.registry import ProfileRegistry, load_profile_registry
from ingestor.ingestion_worker.multilevel_runtime_authority import (
    MultilevelRuntimeAuthorityInputs,
    load_multilevel_runtime_authorities,
)
from ingestor.ingestion_worker.runtime_authority import RuntimeAuthorityStartupError
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


def _production_inputs(
    release_path: Path | None = None,
    **review_authority: object,
) -> tuple[MultilevelRuntimeAuthorityInputs, ProfileRegistry]:
    """Construit les entrées réelles du chargeur multi-niveaux.

    Extrait du test de résolution pour qu'une seconde preuve puisse
    substituer le manifeste de release sans dupliquer vingt liaisons."""
    fixture_root = ENGINE_ROOT / "tests/fixtures/profile_gate_20260825"
    bindings = json.loads((fixture_root / "authority_bindings.json").read_text())[
        "bindings"
    ]

    def bound(name: str) -> tuple[Path, str]:
        binding = bindings[name]
        return REPOSITORY_ROOT / binding["path"], binding["file_sha256"]

    candidate_path = fixture_root / "candidate_inventory.json"
    candidate_sha = _sha256(candidate_path)
    currentness_path = fixture_root / "currentness_evidence.json"
    currentness_sha = _sha256(currentness_path)
    levels_path, levels_sha = bound("level_mapping_sha256")
    subjects_path, subjects_sha = bound("subject_mapping_sha256")
    types_path = fixture_root / "eduscol_multilevel_document_types.yml"
    types_sha = _sha256(types_path)
    programme_path = fixture_root / "programme_registry.json"
    programme_sha = _sha256(programme_path)
    profile_manifest_path, profile_manifest_sha = bound("profile_manifest_sha256")
    pii_path = fixture_root / "pii_evidence.json"
    pii_sha = _sha256(pii_path)
    rights_path, rights_sha = bound("rights_registry_sha256")
    release_path = release_path or fixture_root / "production-profile-gate.release.json"
    release_sha = _sha256(release_path)
    collection_config = ENGINE_ROOT / "configs/rag_collections.yml"
    profiles = load_profile_registry(PRODUCTION_PROFILES)
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
        release_manifest_sha256=release_sha,
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
        **review_authority,  # type: ignore[arg-type]
    )
    return inputs, profiles


def test_real_production_authorities_resolve_all_twenty_six_placements() -> None:
    inputs, profiles = _production_inputs()
    fixture_root = ENGINE_ROOT / "tests/fixtures/profile_gate_20260825"
    candidate_path = fixture_root / "candidate_inventory.json"
    candidate_sha = _sha256(candidate_path)
    by_collection = {profile.scope.collection: profile for profile in profiles.values()}
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


def test_the_multilevel_loader_refuses_a_release_chain_it_does_not_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P1-A : porter la chaîne n'est pas la confronter.

    Le chemin multi-niveaux recevait les couples `--pii-review-*`, les
    transmettait au registre, et s'arrêtait là : jamais il ne demandait si la
    release qu'il sert déclare la MÊME chaîne. Une release pouvait donc
    annoncer la chaîne d'une campagne de revue pendant qu'aucune n'était
    vérifiée — chacune cohérente de son côté, et aucune ne couvrant ce que
    l'autre affirme.

    Ici la release déclare une chaîne complète ; le worker n'en charge aucune.

    L'attente de placements reste celle de la release RÉELLE, et SEULE la
    déclaration d'autorité change — pas même le genre de release — pour que
    l'échec ne puisse venir que d'elle.

    Deux versions antérieures réécrivaient aussi `release_kind` en V2. La
    première l'affirmait ; la seconde prétendait le contraire dans sa
    docstring sans avoir retiré la ligne — une correction annoncée mais non
    faite, relevée en revue. La ligne est partie : la release déclarante garde
    son genre V1 réel.
    """
    from ingestor import multilevel_verified_placement as multilevel_release

    original = ENGINE_ROOT / "tests/fixtures/profile_gate_20260825/production-profile-gate.release.json"
    aggregate = json.loads(original.read_text(encoding="utf-8"))
    aggregate["authorities"].update(
        {
            "pii_decision_set_sha256": "a" * 64,
            "pii_review_receipt_sha256": "b" * 64,
            "pii_review_trust_anchor_sha256": "c" * 64,
            "pii_review_index_sha256": "d" * 64,
        }
    )
    declaring = tmp_path / "release-declaring-a-chain.json"
    declaring.write_bytes(
        (json.dumps(aggregate, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    )

    real = multilevel_release.load_release_expectation
    monkeypatch.setattr(
        multilevel_release,
        "load_release_expectation",
        lambda _path, _digest: real(original, _sha256(original)),
    )

    inputs, profiles = _production_inputs(release_path=declaring)
    with pytest.raises(RuntimeAuthorityStartupError) as refusal:
        load_multilevel_runtime_authorities(
            inputs, profile_registry=profiles, environment="production"
        )
    assert "not the one this worker verifies" in str(refusal.value)
