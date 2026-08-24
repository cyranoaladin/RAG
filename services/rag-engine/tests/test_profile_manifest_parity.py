"""Parité octet-pour-octet entre primitives partagées et startup gate."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
import yaml
from nexus_contracts.ingestion import (
    CollectionProfile,
    collection_profile_fingerprint,
)
from nexus_contracts.profile_manifest import (
    CanonicalProfileVersionError,
    ProductionProfileManifestError,
    StrictYamlError,
    require_canonical_profile_version,
    strict_yaml_mapping,
    validate_production_profile_manifest,
)

from ingestor.ingestion_profiles.manifest import ProfileManifestError
from ingestor.ingestion_profiles.registry import ProfileRegistryLoadError
from ingestor.ingestion_profiles.startup_gate import enforce_production_manifest_gate

PROFILE_ID = "collection_maths"
PROFILE_KEY = (PROFILE_ID, "v1")


def _profile_document() -> dict[str, Any]:
    return {
        "profile_version": "v1",
        "enabled": True,
        "scope": {
            "tenant": "libre_terminale",
            "collection": PROFILE_ID,
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "mathematiques",
            "candidat": "libre",
            "audience": ["libre", "tous"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "BOEN_test_v1",
        },
        "title": "Profil test",
        "owner": "tests",
        "expected_topics": ["notion"],
        "expected_resource_types": ["cours"],
        "allowed_domains": ["education.gouv.fr"],
        "source_authority": "official",
        "search_cadence": "weekly",
        "max_queries_per_run": 1,
        "max_documents_per_run": 1,
        "max_chunk_size": 800,
        "chunk_overlap": 100,
        "min_source_confidence": 0.7,
        "min_scope_confidence": 0.7,
        "min_extraction_quality": 0.7,
    }


def _profile_fingerprint() -> str:
    return cast(
        str,
        collection_profile_fingerprint(CollectionProfile.model_validate(_profile_document())),
    )


def _entry(**overrides: Any) -> dict[str, Any]:
    entry = {
        "collection": PROFILE_ID,
        "profile_version": "v1",
        "fingerprint": _profile_fingerprint(),
        "approved_by": "test-authority",
        "approved_at": "2026-08-23T00:00:00Z",
    }
    entry.update(overrides)
    return entry


def _manifest_document() -> dict[str, Any]:
    return {
        "manifest_version": "1",
        "provenance": "parity-test",
        "generated_at": "2026-08-23T00:00:00Z",
        "profiles": [_entry()],
    }


def _dump(document: dict[str, Any]) -> bytes:
    return yaml.safe_dump(document, sort_keys=True).encode()


def _mutated_manifest(mutate: Callable[[dict[str, Any]], None]) -> bytes:
    document = _manifest_document()
    mutate(document)
    return _dump(document)


def _manifest_cases() -> list[Any]:
    valid = _dump(_manifest_document()).decode()
    return [
        pytest.param(
            valid.replace(
                "  approved_by: test-authority",
                "  approved_by: test-authority\n  approved_by: test-authority",
            ).encode(),
            id="nested-duplicate",
        ),
        pytest.param(
            valid.replace("manifest_version: '1'", "manifest_version: &version '1'").encode(),
            id="anchor",
        ),
        pytest.param(
            valid.replace(
                "provenance: parity-test",
                "provenance: &proof parity-test\nnote: *proof",
            ).encode(),
            id="alias",
        ),
        pytest.param(
            valid.replace(
                "profiles:",
                "authority: &authority\n  approved_by: test-authority\nprofiles:",
            )
            .replace("  approved_by: test-authority", "  <<: *authority")
            .encode(),
            id="merge",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc["profiles"][0].pop("approved_by")),
            id="missing-approved-by",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc["profiles"][0].update(approved_by="   ")),
            id="blank-approved-by",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc["profiles"][0].pop("approved_at")),
            id="missing-approved-at",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc["profiles"][0].update(approved_at="invalid")),
            id="invalid-approved-at",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc.update(manifest_version="2")),
            id="unsupported-version",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc.pop("provenance")),
            id="missing-provenance",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc.pop("generated_at")),
            id="missing-generated-at",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc["profiles"].append(dict(doc["profiles"][0]))),
            id="duplicate-identity",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc["profiles"][0].update(collection="collection_extra")),
            id="profile-set-mismatch",
        ),
        pytest.param(
            _mutated_manifest(lambda doc: doc["profiles"][0].update(fingerprint="f" * 64)),
            id="fingerprint-mismatch",
        ),
    ]


@pytest.mark.parametrize("manifest_raw", _manifest_cases())
def test_bad_manifest_bytes_refused_by_shared_producer_path_and_runtime_gate(
    tmp_path: Path,
    manifest_raw: bytes,
) -> None:
    with pytest.raises(ProductionProfileManifestError):
        validate_production_profile_manifest(
            manifest_raw,
            profile_fingerprints={PROFILE_KEY: _profile_fingerprint()},
            source="manifest.yml",
        )

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "maths.yml").write_bytes(_dump(_profile_document()))
    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_bytes(manifest_raw)
    with pytest.raises(ProfileManifestError):
        enforce_production_manifest_gate(profiles_dir, manifest_path)


@pytest.mark.parametrize("kind", ["duplicate", "anchor"])
def test_bad_profile_bytes_refused_by_shared_producer_path_and_runtime_gate(
    tmp_path: Path,
    kind: str,
) -> None:
    profile_raw = _dump(_profile_document())
    if kind == "duplicate":
        profile_raw = profile_raw.replace(b"enabled: true", b"enabled: true\nenabled: true")
    else:
        profile_raw = profile_raw.replace(b"enabled: true", b"enabled: &value true")
    with pytest.raises(StrictYamlError):
        strict_yaml_mapping(profile_raw, source="maths.yml")

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "maths.yml").write_bytes(profile_raw)
    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_bytes(_dump(_manifest_document()))
    with pytest.raises(ProfileRegistryLoadError):
        enforce_production_manifest_gate(profiles_dir, manifest_path)


def test_noncanonical_profile_version_bytes_refused_by_both_paths(
    tmp_path: Path,
) -> None:
    profile_document = _profile_document()
    profile_document["profile_version"] = "bad version"
    profile_raw = _dump(profile_document)
    parsed = strict_yaml_mapping(profile_raw, source="maths.yml")
    parsed_profile = CollectionProfile.model_validate(parsed)
    with pytest.raises(CanonicalProfileVersionError):
        require_canonical_profile_version(parsed_profile.profile_version, source="maths.yml")

    profiles_dir = tmp_path / "profiles"
    profiles_dir.mkdir()
    (profiles_dir / "maths.yml").write_bytes(profile_raw)
    manifest = _manifest_document()
    manifest["profiles"][0]["profile_version"] = "bad version"
    manifest["profiles"][0]["fingerprint"] = collection_profile_fingerprint(parsed_profile)
    manifest_path = tmp_path / "manifest.yml"
    manifest_path.write_bytes(_dump(manifest))
    with pytest.raises(ProfileRegistryLoadError):
        enforce_production_manifest_gate(profiles_dir, manifest_path)
