"""Manifest borné de profils réservé au staging local.

Ce contrat ne représente ni une approbation humaine de production, ni une
attestation LOT41A/LOT42. Il fige seulement l'ensemble exact des profils que
le harnais staging peut présenter aux gates existants.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .ingestion_profiles.registry import (
    ProfileKey,
    ProfileRegistry,
    profile_fingerprint,
)

MANIFEST_KIND = "NEXUS_STAGING_PROFILE_MANIFEST_V1"
AUTHORITY_MODE = "STAGING_LOCAL_GITHUB_ONLY"


class StagingProfileManifestError(RuntimeError):
    """Le manifest staging est ambigu, dérivé ou prétend une autorité réelle."""


@dataclass(frozen=True)
class StagingProfileManifestVerification:
    manifest_sha256: str
    declared_count: int
    provenance: str
    generated_at: str
    authority_mode: str
    production_approval: bool


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    document: dict[str, Any] = {}
    for key, value in pairs:
        if key in document:
            raise StagingProfileManifestError(
                f"staging profile manifest contains duplicate key {key!r}"
            )
        document[key] = value
    return document


def _nonempty(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StagingProfileManifestError(f"{label} must be a non-empty string")
    return value


def verify_staging_profile_manifest(
    registry: ProfileRegistry,
    manifest_path: Path,
) -> StagingProfileManifestVerification:
    try:
        raw = manifest_path.read_bytes()
        document = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_pairs
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingProfileManifestError(
            "staging profile manifest cannot be read"
        ) from exc
    if not isinstance(document, Mapping) or set(document) != {
        "manifest_kind",
        "provenance",
        "generated_at",
        "authority_mode",
        "production_approval",
        "profiles",
    }:
        raise StagingProfileManifestError(
            "staging profile manifest fields are not exact"
        )
    if document.get("manifest_kind") != MANIFEST_KIND:
        raise StagingProfileManifestError("staging profile manifest kind is invalid")
    if document.get("authority_mode") != AUTHORITY_MODE:
        raise StagingProfileManifestError("staging authority mode is invalid")
    if document.get("production_approval") is not False:
        raise StagingProfileManifestError(
            "staging profile manifest cannot claim production approval"
        )
    provenance = _nonempty(document.get("provenance"), label="provenance")
    generated_at = _nonempty(document.get("generated_at"), label="generated_at")
    raw_profiles = document.get("profiles")
    if not isinstance(raw_profiles, list) or not raw_profiles:
        raise StagingProfileManifestError("staging profile manifest is empty")

    declared: dict[ProfileKey, str] = {}
    for entry in raw_profiles:
        if not isinstance(entry, Mapping) or set(entry) != {
            "collection",
            "profile_version",
            "fingerprint",
        }:
            raise StagingProfileManifestError("staging profile entry is not exact")
        key = (
            _nonempty(entry.get("collection"), label="profile collection"),
            _nonempty(entry.get("profile_version"), label="profile version"),
        )
        fingerprint = _nonempty(
            entry.get("fingerprint"), label="profile fingerprint"
        )
        if key in declared:
            raise StagingProfileManifestError("staging profile identity is duplicated")
        declared[key] = fingerprint
    if set(declared) != set(registry):
        raise StagingProfileManifestError(
            "staging profile manifest differs from the loaded registry"
        )
    for key, profile in registry.items():
        if declared[key] != profile_fingerprint(profile):
            raise StagingProfileManifestError(
                f"staging profile fingerprint differs for {key!r}"
            )
    return StagingProfileManifestVerification(
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        declared_count=len(declared),
        provenance=provenance,
        generated_at=generated_at,
        authority_mode=AUTHORITY_MODE,
        production_approval=False,
    )


__all__ = [
    "AUTHORITY_MODE",
    "MANIFEST_KIND",
    "StagingProfileManifestError",
    "StagingProfileManifestVerification",
    "verify_staging_profile_manifest",
]
