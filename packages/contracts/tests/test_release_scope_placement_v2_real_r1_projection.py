"""Full-scale, real-data proof (R1G mandate section 25): build the
canonical V2 inputs directly from the sealed production-profile-gate-2026-2027-v1
release authorities (subject release JSON files, the real v2_livraison_319
profile registry, the real profile manifest) -- never from fabricated or
CI-fixture data -- and prove the V2 producer represents all 486 real
placements exactly.
"""
from __future__ import annotations

import json
from pathlib import Path

from nexus_contracts.authorization_set import release_placement_binding_key
from nexus_contracts.release_scope_placement import produce_release_scope_placement_v2_from_blobs

from ingestor.ingestion_profiles.manifest import verify_profile_manifest
from ingestor.ingestion_profiles.registry import load_profile_registry, profile_fingerprint

_REPO_ROOT = Path(__file__).resolve().parents[3]
_RAG_ENGINE = _REPO_ROOT / "services" / "rag-engine"
_RAG_PEDAGO = _REPO_ROOT / "services" / "rag-pedago"
_PROFILES_DIR = _RAG_ENGINE / "configs" / "ingestion_profiles" / "v2_livraison_319"
_MANIFEST_PATH = _RAG_ENGINE / "configs" / "ingestion_profiles" / "ingestion_manifest_v2_livraison_319.yml"
_SUBJECTS_DIR = (
    _RAG_PEDAGO / "data" / "releases" / "prerentree_2026_2027" / "profile_gate" / "subjects"
)
_REGISTRY_PATH = _RAG_PEDAGO / "data" / "releases" / "prerentree_2026_2027" / "release-registry.json"

RELEASE_ID = "production-profile-gate-2026-2027-v1"

MATRIX_PATH = "matrix.json"
PLACEMENTS_PATH = "placements.json"
REGISTRY_PATH = "registry.json"
CONTENTS_PATH = "expected.txt"
PROFILES_PATH = "profiles.json"
MANIFEST_PATH_KEY = "manifest.yml"


def _real_inputs() -> tuple[dict[str, bytes], int, int]:
    """Constructs every V2 producer input directly from real, sealed
    authorities already in the repository -- never from a fabricated or
    historical/superseded intermediate artifact (R1G section 23/24: the
    real 486-scale matrix/placements/expected-contents were confirmed
    MISSING as standalone historical files by the prior forensic mission;
    every fact used here is instead derived directly from the strongest
    currently-sealed authority)."""
    registry = load_profile_registry(_PROFILES_DIR)
    verification = verify_profile_manifest(registry, _MANIFEST_PATH)

    subject_files = sorted(_SUBJECTS_DIR.glob("*.release.json"))
    assert len(subject_files) == 11

    accepted_placements: list[dict] = []
    matrix: list[dict] = []
    verified_profiles: list[dict] = []
    expected_contents: set[str] = set()
    source_blobs: dict[str, bytes] = {
        REGISTRY_PATH: _REGISTRY_PATH.read_bytes(),
        MANIFEST_PATH_KEY: _MANIFEST_PATH.read_bytes(),
    }

    for subject_file in subject_files:
        subject = json.loads(subject_file.read_text(encoding="utf-8"))
        collection = subject["collection"]
        profile_version = None
        for (coll, version), _profile in registry.items():
            if coll == collection:
                profile_version = version
                break
        assert profile_version is not None, f"no registered profile for {collection!r}"
        profile = registry[(collection, profile_version)]
        profile_path_str = f"profiles/{collection}.yml"
        source_blobs[profile_path_str] = (_PROFILES_DIR / f"{collection}.yml").read_bytes()

        contents_for_collection: list[str] = []
        for artifact in subject["artifacts"]:
            content_sha256 = artifact["content_sha256"]
            contents_for_collection.append(content_sha256)
            expected_contents.add(content_sha256)
            accepted_placements.append(
                {
                    "content_sha256": content_sha256,
                    "release_id": RELEASE_ID,
                    "collection": collection,
                    "profile_version": profile_version,
                }
            )

        scope_dims = profile.scope.model_dump(mode="json")
        matrix.append(
            {
                "partition_id": collection,
                "partition_kind": "EXACT_VERSIONED_RELEASE_PROFILE",
                "content_count": len(contents_for_collection),
                "content_sha256": contents_for_collection,
                "profile_decision_required": False,
                "evidence_sources": [profile_path_str],
                "dimensions": {
                    field: {"grounded": True, "source_of_truth": profile_path_str, "value": value}
                    for field, value in scope_dims.items()
                },
            }
        )
        # profile_fingerprint: recomputed directly from the real, loaded
        # profile object -- `verify_profile_manifest` already proved this
        # exact value matches the sealed manifest's own authority.
        verified_profiles.append(
            {
                "profile_id": collection,
                "profile_version": profile_version,
                "profile_fingerprint": profile_fingerprint(profile),
                "scope": scope_dims,
                "source_path": profile_path_str,
            }
        )

    source_blobs[MATRIX_PATH] = json.dumps(matrix).encode("utf-8")
    source_blobs[PLACEMENTS_PATH] = json.dumps(accepted_placements).encode("utf-8")
    source_blobs[CONTENTS_PATH] = (
        "\n".join(sorted(expected_contents)) + "\n"
    ).encode("utf-8")
    source_blobs[PROFILES_PATH] = json.dumps(
        {
            "profile_manifest_digest": verification.manifest_fingerprint,
            "profiles": verified_profiles,
        }
    ).encode("utf-8")

    return source_blobs, len(accepted_placements), len(expected_contents)


def test_v2_producer_represents_all_486_real_r1_release_placements() -> None:
    source_blobs, placement_count, unique_content_count = _real_inputs()
    assert placement_count == 486
    assert unique_content_count == 319

    produced = produce_release_scope_placement_v2_from_blobs(
        source_blobs=source_blobs,
        profile_proposal_matrix_path=MATRIX_PATH,
        accepted_placements_path=PLACEMENTS_PATH,
        release_registry_path=REGISTRY_PATH,
        expected_contents_path=CONTENTS_PATH,
        verified_profiles_path=PROFILES_PATH,
        profile_manifest_path=MANIFEST_PATH_KEY,
    )

    assert len(produced.placement.placements) == 486
    assert {entry.content_sha256 for entry in produced.placement.placements} == set(
        source_blobs[CONTENTS_PATH].decode().splitlines()
    )
    bindings = {
        release_placement_binding_key(entry) for entry in produced.placement.placements
    }
    assert len(bindings) == 486, "every one of the 486 real placements is a distinct binding"

    multiplacement = {}
    for entry in produced.placement.placements:
        multiplacement.setdefault(entry.content_sha256, set()).add(entry.profile_id)
    truly_multiplaced = {sha: cols for sha, cols in multiplacement.items() if len(cols) > 1}
    assert len(truly_multiplaced) == 167
