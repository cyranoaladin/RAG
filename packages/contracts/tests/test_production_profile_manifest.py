"""Sémantique partagée du manifeste et des YAML de profils production."""

from __future__ import annotations

from collections.abc import Callable

import pytest
import yaml

from nexus_contracts.profile_manifest import (
    CanonicalProfileVersionError,
    ProductionProfileManifestError,
    StrictYamlError,
    require_canonical_profile_version,
    strict_yaml_mapping,
    validate_production_profile_manifest,
)

PROFILE_KEY = ("collection_maths", "v1")
FINGERPRINT = "a" * 64


@pytest.mark.parametrize("value", ["v1", "2026.08-rc_1", "A" * 64])
def test_canonical_profile_version_accepts_only_bounded_slug(value: str) -> None:
    assert require_canonical_profile_version(value, source="profile.yml") == value


@pytest.mark.parametrize("value", ["bad version", "-v1", "", "A" * 65])
def test_canonical_profile_version_refuses_ambiguous_identity(value: str) -> None:
    with pytest.raises(CanonicalProfileVersionError):
        require_canonical_profile_version(value, source="profile.yml")


def test_manifest_entry_requires_canonical_profile_version() -> None:
    with pytest.raises(ProductionProfileManifestError, match="profile_version"):
        validate_production_profile_manifest(
            _manifest(profile_version="bad version"),
            profile_fingerprints={(PROFILE_KEY[0], "bad version"): FINGERPRINT},
            source="manifest.yml",
        )


def _manifest(**entry_overrides: object) -> bytes:
    entry: dict[str, object] = {
        "collection": PROFILE_KEY[0],
        "profile_version": PROFILE_KEY[1],
        "fingerprint": FINGERPRINT,
        "approved_by": "test-authority",
        "approved_at": "2026-08-23T00:00:00Z",
    }
    entry.update(entry_overrides)
    return yaml.safe_dump(
        {
            "manifest_version": "1",
            "provenance": "fixture",
            "generated_at": "2026-08-23T00:00:00Z",
            "profiles": [entry],
        },
        sort_keys=True,
    ).encode()


@pytest.mark.parametrize(
    "raw",
    [
        b"scope:\n  collection: first\n  collection: second\n",
        b"enabled: &enabled true\ncopy: *enabled\n",
        b"defaults: &defaults\n  enabled: true\nprofile:\n  <<: *defaults\n",
    ],
    ids=("nested-duplicate", "anchor-alias", "merge"),
)
def test_strict_yaml_mapping_refuses_ambiguous_yaml(raw: bytes) -> None:
    with pytest.raises(StrictYamlError):
        strict_yaml_mapping(raw, source="profile.yml")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda entry: entry.pop("approved_by"), "approved_by"),
        (lambda entry: entry.update(approved_by="   "), "approved_by"),
        (lambda entry: entry.pop("approved_at"), "approved_at"),
        (lambda entry: entry.update(approved_at="not-a-date"), "approved_at"),
    ],
    ids=("missing-approver", "blank-approver", "missing-date", "invalid-date"),
)
def test_manifest_refuses_invalid_approval(
    mutate: Callable[[dict[str, object]], object],
    message: str,
) -> None:
    document = yaml.safe_load(_manifest())
    entry = document["profiles"][0]
    mutate(entry)
    raw = yaml.safe_dump(document, sort_keys=True).encode()

    with pytest.raises(ProductionProfileManifestError, match=message):
        validate_production_profile_manifest(
            raw,
            profile_fingerprints={PROFILE_KEY: FINGERPRINT},
            source="manifest.yml",
        )


def test_manifest_validation_returns_canonical_identity() -> None:
    result = validate_production_profile_manifest(
        _manifest(),
        profile_fingerprints={PROFILE_KEY: FINGERPRINT},
        source="manifest.yml",
    )

    assert result.declared_count == 1
    assert result.manifest_version == "1"
    assert result.provenance == "fixture"
    assert result.authorities[PROFILE_KEY].approved_by == "test-authority"
    assert len(result.manifest_fingerprint) == 64
