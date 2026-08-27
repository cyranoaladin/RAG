"""Validation pure et partagée des profils et manifestes YAML production."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

import yaml  # type: ignore[import-untyped]

from nexus_contracts.ingestion import profile_manifest_fingerprint

SUPPORTED_PRODUCTION_PROFILE_MANIFEST_VERSION = "1"
_FINGERPRINT_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CANONICAL_PROFILE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")

ProfileIdentity = tuple[str, str]


class StrictYamlError(ValueError):
    """Les octets YAML sont invalides ou ambigus."""


class CanonicalProfileVersionError(ValueError):
    """La version ne forme pas une identité canonique bornée."""


class ProductionProfileManifestError(ValueError):
    """Le manifeste ne correspond pas exactement aux profils vérifiés."""


@dataclass(frozen=True)
class ProductionProfileAuthority:
    approved_by: str
    approved_at: str


@dataclass(frozen=True)
class ProductionProfileManifestVerification:
    manifest_fingerprint: str
    declared_count: int
    manifest_version: str
    provenance: str
    generated_at: str
    authorities: Mapping[ProfileIdentity, ProductionProfileAuthority]


class _StrictYamlLoader(yaml.SafeLoader):
    def construct_mapping(
        self, node: yaml.MappingNode, deep: bool = False
    ) -> dict[Any, Any]:
        seen: set[Any] = set()
        for key_node, _value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                repeated = key in seen
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    f"unhashable mapping key {key!r}: {exc}",
                    node.start_mark,
                ) from exc
            if repeated:
                raise yaml.constructor.ConstructorError(
                    None,
                    None,
                    f"found duplicate key {key!r}",
                    node.start_mark,
                )
            seen.add(key)
        return super().construct_mapping(node, deep=deep)

    def compose_node(self, parent: yaml.Node | None, index: Any) -> yaml.Node | None:
        event = self.peek_event()
        anchor = getattr(event, "anchor", None)
        if anchor is not None:
            kind = "alias" if isinstance(event, yaml.events.AliasEvent) else "anchor"
            raise yaml.constructor.ConstructorError(
                None,
                None,
                f"YAML {kind} {anchor!r} is not permitted",
                event.start_mark,
            )
        return super().compose_node(parent, index)


def strict_yaml_mapping(raw: bytes, *, source: str) -> dict[str, Any]:
    """Parse des octets YAML sans doublon, ancre, alias ni clé de fusion."""
    try:
        text = raw.decode("utf-8")
        document = yaml.load(text, Loader=_StrictYamlLoader)  # noqa: S506
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise StrictYamlError(f"Invalid YAML in {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise StrictYamlError(f"Invalid YAML mapping in {source}")
    return cast(dict[str, Any], document)


def _required_text(document: Mapping[str, Any], field: str, source: str) -> str:
    value = document.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ProductionProfileManifestError(
            f"Manifest {source} is missing required field {field!r}"
        )
    return value


def require_canonical_profile_version(value: str, *, source: str) -> str:
    if CANONICAL_PROFILE_VERSION_PATTERN.fullmatch(value) is None:
        raise CanonicalProfileVersionError(
            f"{source}: profile_version {value!r} does not match "
            f"{CANONICAL_PROFILE_VERSION_PATTERN.pattern!r}"
        )
    return value


def validate_production_profile_manifest(
    raw: bytes,
    *,
    profile_fingerprints: Mapping[ProfileIdentity, str],
    source: str,
) -> ProductionProfileManifestVerification:
    """Valide le manifeste contre l'ensemble exact des profils vérifiés."""
    try:
        document = strict_yaml_mapping(raw, source=source)
    except StrictYamlError as exc:
        raise ProductionProfileManifestError(str(exc)) from exc

    manifest_version = _required_text(document, "manifest_version", source)
    if manifest_version != SUPPORTED_PRODUCTION_PROFILE_MANIFEST_VERSION:
        raise ProductionProfileManifestError(
            f"Manifest {source} declares manifest_version={manifest_version!r}, "
            f"only {SUPPORTED_PRODUCTION_PROFILE_MANIFEST_VERSION!r} is supported"
        )
    provenance = _required_text(document, "provenance", source)
    generated_at = _required_text(document, "generated_at", source)
    entries = document.get("profiles")
    if not isinstance(entries, list) or not entries:
        raise ProductionProfileManifestError(
            f"Manifest {source} declares zero profiles"
        )

    declared: dict[ProfileIdentity, str] = {}
    authorities: dict[ProfileIdentity, ProductionProfileAuthority] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, Mapping):
            raise ProductionProfileManifestError(
                f"Manifest entry #{index} is not a mapping"
            )
        collection = entry.get("collection")
        profile_version = entry.get("profile_version")
        fingerprint = entry.get("fingerprint")
        approved_by = entry.get("approved_by")
        approved_at = entry.get("approved_at")
        if not isinstance(collection, str) or not collection:
            raise ProductionProfileManifestError(
                f"Manifest entry #{index} is missing 'collection'"
            )
        if not isinstance(profile_version, str) or not profile_version:
            raise ProductionProfileManifestError(
                f"Manifest entry #{index} is missing 'profile_version'"
            )
        try:
            require_canonical_profile_version(
                profile_version, source=f"Manifest entry #{index}"
            )
        except CanonicalProfileVersionError as exc:
            raise ProductionProfileManifestError(str(exc)) from exc
        if (
            not isinstance(fingerprint, str)
            or _FINGERPRINT_PATTERN.fullmatch(fingerprint) is None
        ):
            raise ProductionProfileManifestError(
                f"Manifest entry #{index} has a missing or malformed 'fingerprint'"
            )
        if not isinstance(approved_by, str) or not approved_by.strip():
            raise ProductionProfileManifestError(
                f"Manifest entry #{index} has a missing or empty 'approved_by'"
            )
        if not isinstance(approved_at, str) or not approved_at.strip():
            raise ProductionProfileManifestError(
                f"Manifest entry #{index} has a missing or empty 'approved_at'"
            )
        try:
            datetime.fromisoformat(approved_at)
        except ValueError as exc:
            raise ProductionProfileManifestError(
                f"Manifest entry #{index} has an invalid ISO 8601 'approved_at': "
                f"{approved_at!r}"
            ) from exc

        identity = (collection, profile_version)
        if identity in declared:
            raise ProductionProfileManifestError(
                f"Manifest declares {identity!r} more than once"
            )
        declared[identity] = fingerprint
        authorities[identity] = ProductionProfileAuthority(
            approved_by=approved_by,
            approved_at=approved_at,
        )

    declared_identities = set(declared)
    actual_identities = set(profile_fingerprints)
    missing = declared_identities - actual_identities
    if missing:
        raise ProductionProfileManifestError(
            f"Manifest declares profiles not present in the loaded registry: {sorted(missing)}"
        )
    unexpected = actual_identities - declared_identities
    if unexpected:
        raise ProductionProfileManifestError(
            f"Registry contains profiles not declared in the manifest: {sorted(unexpected)}"
        )
    for identity, expected_fingerprint in declared.items():
        actual_fingerprint = profile_fingerprints[identity]
        if actual_fingerprint != expected_fingerprint:
            raise ProductionProfileManifestError(
                f"Fingerprint mismatch for collection={identity[0]!r} "
                f"profile_version={identity[1]!r}: manifest declares "
                f"{expected_fingerprint}, loaded profile is {actual_fingerprint}"
            )

    return ProductionProfileManifestVerification(
        manifest_fingerprint=profile_manifest_fingerprint(document),
        declared_count=len(declared),
        manifest_version=manifest_version,
        provenance=provenance,
        generated_at=generated_at,
        authorities=authorities,
    )


__all__ = [
    "CANONICAL_PROFILE_VERSION_PATTERN",
    "CanonicalProfileVersionError",
    "ProductionProfileAuthority",
    "ProductionProfileManifestError",
    "ProductionProfileManifestVerification",
    "SUPPORTED_PRODUCTION_PROFILE_MANIFEST_VERSION",
    "StrictYamlError",
    "require_canonical_profile_version",
    "strict_yaml_mapping",
    "validate_production_profile_manifest",
]
