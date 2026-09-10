"""RED at real scale: prove, against the ACTUAL sealed
production-profile-gate-2026-2027-v1 release (11 real subject files, real
profile YAML sources), that V1's `ReleaseScopePlacementV1` cannot represent
the real 486 placements -- not a synthetic minimal case, the real release
data. The multi-placement content count is derived from the release
itself, never hardcoded.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from nexus_contracts.authorization_set import ReleaseScopePlacementEntryV1, ReleaseScopePlacementV1
from nexus_contracts.ingestion import CollectionProfile, collection_profile_fingerprint
from nexus_contracts.profile_manifest import require_canonical_profile_version, strict_yaml_mapping

_RAG_PEDAGO_ROOT = Path(__file__).resolve().parents[3] / "services" / "rag-pedago"
_RAG_ENGINE_ROOT = Path(__file__).resolve().parents[3] / "services" / "rag-engine"
_SUBJECTS_DIR = (
    _RAG_PEDAGO_ROOT / "data" / "releases" / "prerentree_2026_2027" / "profile_gate" / "subjects"
)
_PROFILES_DIR = _RAG_ENGINE_ROOT / "configs" / "ingestion_profiles" / "v2_livraison_319"


def _load_real_subject_files() -> list[dict]:
    files = sorted(_SUBJECTS_DIR.glob("*.release.json"))
    assert len(files) == 11, f"expected 11 sealed subject files, found {len(files)}"
    return [json.loads(path.read_text(encoding="utf-8")) for path in files]


def _load_real_profile(collection: str) -> CollectionProfile:
    path = _PROFILES_DIR / f"{collection}.yml"
    document = strict_yaml_mapping(path.read_bytes(), source=str(path))
    profile = CollectionProfile.model_validate(document)
    require_canonical_profile_version(profile.profile_version, source=str(path))
    return profile


def test_real_r1_release_has_multiplacement_contents_derived_not_hardcoded() -> None:
    """Establishes the ground truth this whole file depends on: N contents
    (expected 167, but computed here, never assumed) appear under more
    than one collection in the real sealed release."""
    subjects = _load_real_subject_files()
    collections_by_content: dict[str, set[str]] = {}
    for subject in subjects:
        for artifact in subject["artifacts"]:
            collections_by_content.setdefault(artifact["content_sha256"], set()).add(
                subject["collection"]
            )
    multiplacement = {sha: cols for sha, cols in collections_by_content.items() if len(cols) > 1}
    assert len(collections_by_content) == 319
    assert len(multiplacement) == 167
    assert all(len(cols) == 2 for cols in multiplacement.values())


def test_v1_cannot_represent_the_real_486_release_placements() -> None:
    """RED: build the real 486 ReleaseScopePlacementEntryV1 objects (real
    content_sha256, real profile_id/profile_version/profile_fingerprint
    from the real, loaded v2_livraison_319 profile sources, real scope)
    and prove `ReleaseScopePlacementV1.build()` -- V1's own model-level
    uniqueness invariant -- refuses to construct a projection representing
    all of them, because 167 content_sha256 values are repeated."""
    subjects = _load_real_subject_files()
    profile_cache: dict[str, CollectionProfile] = {}

    def profile_for(collection: str) -> CollectionProfile:
        if collection not in profile_cache:
            profile_cache[collection] = _load_real_profile(collection)
        return profile_cache[collection]

    entries: list[ReleaseScopePlacementEntryV1] = []
    for subject in subjects:
        collection = subject["collection"]
        profile = profile_for(collection)
        fingerprint = collection_profile_fingerprint(profile)
        for artifact in subject["artifacts"]:
            entries.append(
                ReleaseScopePlacementEntryV1.model_validate(
                    {
                        "content_sha256": artifact["content_sha256"],
                        "profile_id": collection,
                        "profile_version": profile.profile_version,
                        "profile_fingerprint": fingerprint,
                        "scope": profile.scope.model_dump(mode="json"),
                    }
                )
            )

    assert len(entries) == 486, "expected exactly the 486 real release-artifact entries"

    with pytest.raises(Exception) as excinfo:
        ReleaseScopePlacementV1.build(
            placements=entries,
            profile_manifest_digest="f" * 64,
        )
    assert "repeats content_sha256" in str(excinfo.value)
