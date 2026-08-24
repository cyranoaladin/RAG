"""Adaptateur rag-engine du manifeste partagé de profils production.

La lecture YAML stricte, les autorités, l'égalité d'ensemble et les
empreintes sont définies dans ``nexus-contracts`` afin que le plan de
contrôle et le runtime prennent exactement la même décision sur les mêmes
octets. Ce module conserve l'API et les erreurs historiques de rag-engine.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from nexus_contracts.ingestion import profile_manifest_fingerprint
from nexus_contracts.profile_manifest import (
    SUPPORTED_PRODUCTION_PROFILE_MANIFEST_VERSION,
    ProductionProfileManifestError,
    validate_production_profile_manifest,
)

from .registry import (
    ProfileKey,
    ProfileRegistry,
    ProfileRegistryError,
    profile_fingerprint,
)

SUPPORTED_MANIFEST_VERSION = SUPPORTED_PRODUCTION_PROFILE_MANIFEST_VERSION


class ProfileManifestError(ProfileRegistryError):
    """Le manifeste est absent, ambigu ou incohérent avec le registre."""


@dataclass(frozen=True)
class ProfileAuthority:
    approved_by: str
    approved_at: str


@dataclass(frozen=True)
class ManifestVerification:
    manifest_fingerprint: str
    declared_count: int
    manifest_version: str
    provenance: str
    generated_at: str
    authorities: Mapping[ProfileKey, ProfileAuthority]


def manifest_fingerprint(manifest_data: Mapping[str, Any]) -> str:
    """Conserve le nom public historique en déléguant au contrat pur."""
    return cast(str, profile_manifest_fingerprint(manifest_data))


def verify_profile_manifest(
    registry: ProfileRegistry,
    manifest_path: Path,
) -> ManifestVerification:
    """Vérifie les octets exacts contre les empreintes du registre local."""
    if not manifest_path.is_file():
        raise ProfileManifestError(f"Production profile manifest not found: {manifest_path}")
    fingerprints = {
        identity: profile_fingerprint(profile) for identity, profile in registry.items()
    }
    try:
        verified = validate_production_profile_manifest(
            manifest_path.read_bytes(),
            profile_fingerprints=fingerprints,
            source=manifest_path.name,
        )
    except ProductionProfileManifestError as exc:
        raise ProfileManifestError(str(exc)) from exc
    return ManifestVerification(
        manifest_fingerprint=verified.manifest_fingerprint,
        declared_count=verified.declared_count,
        manifest_version=verified.manifest_version,
        provenance=verified.provenance,
        generated_at=verified.generated_at,
        authorities={
            identity: ProfileAuthority(
                approved_by=authority.approved_by,
                approved_at=authority.approved_at,
            )
            for identity, authority in verified.authorities.items()
        },
    )


__all__ = [
    "SUPPORTED_MANIFEST_VERSION",
    "ManifestVerification",
    "ProfileAuthority",
    "ProfileManifestError",
    "manifest_fingerprint",
    "verify_profile_manifest",
]
