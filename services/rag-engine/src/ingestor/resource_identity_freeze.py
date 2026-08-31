"""Require Nexus-issued Resource identities after Registry bootstrap."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from uuid import UUID

from nexus_contracts import ResourceRegistrySnapshot

RESOURCE_REGISTRY_ISSUANCE_REQUIRED = "RESOURCE_REGISTRY_ISSUANCE_REQUIRED"
_SHA256 = re.compile(r"[0-9a-f]{64}")


class ResourceIdentityFreezeError(ValueError):
    """A resource or version identity was not issued by Nexus."""


class ResourceIdentityFreeze:
    def __init__(self, snapshot: ResourceRegistrySnapshot) -> None:
        self._resources = {item.resource_id for item in snapshot.resources}
        self._versions = {
            (item.resource_id, item.resource_version_id, item.content_sha256)
            for item in snapshot.resources
        }

    @staticmethod
    def _uuid(value: str | UUID | None) -> UUID:
        try:
            return value if isinstance(value, UUID) else UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise ResourceIdentityFreezeError(
                RESOURCE_REGISTRY_ISSUANCE_REQUIRED
            ) from exc

    def require_resource_id(self, value: str | UUID | None) -> UUID:
        resource_id = self._uuid(value)
        if resource_id not in self._resources:
            raise ResourceIdentityFreezeError(RESOURCE_REGISTRY_ISSUANCE_REQUIRED)
        return resource_id

    def require_resource_version_id(
        self,
        *,
        resource_id: UUID,
        resource_version_id: str | UUID | None,
        content_sha256: str,
    ) -> UUID:
        version_id = self._uuid(resource_version_id)
        if (resource_id, version_id, content_sha256) not in self._versions:
            raise ResourceIdentityFreezeError(RESOURCE_REGISTRY_ISSUANCE_REQUIRED)
        return version_id

    def require_declared_resource_version_id(
        self,
        *,
        resource_id: UUID,
        resource_version_id: str | UUID | None,
    ) -> UUID:
        version_id = self._uuid(resource_version_id)
        if not any(
            registered_resource_id == resource_id
            and registered_version_id == version_id
            for registered_resource_id, registered_version_id, _content_sha256 in self._versions
        ):
            raise ResourceIdentityFreezeError(RESOURCE_REGISTRY_ISSUANCE_REQUIRED)
        return version_id


def load_optional_pinned_resource_identity_freeze(
    path: Path | None,
    expected_file_sha256: str | None,
) -> ResourceIdentityFreeze | None:
    """Enable the post-bootstrap identity freeze as one atomic cutover.

    Both inputs are optional only to keep the companion deployment compatible
    with Nexus until its governed Registry snapshot exists. Supplying either
    one makes both mandatory; the worker never loads an unpinned snapshot.
    """
    if path is None and expected_file_sha256 is None:
        return None
    if path is None or expected_file_sha256 is None:
        raise ResourceIdentityFreezeError(
            "resource Registry cutover requires atomic path and digest inputs"
        )
    if _SHA256.fullmatch(expected_file_sha256) is None:
        raise ResourceIdentityFreezeError("invalid resource Registry file digest")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise ResourceIdentityFreezeError(
            "resource Registry snapshot is unavailable"
        ) from exc
    if hashlib.sha256(raw).hexdigest() != expected_file_sha256:
        raise ResourceIdentityFreezeError("resource Registry file digest differs")
    try:
        snapshot = ResourceRegistrySnapshot.model_validate_json(raw)
    except ValueError as exc:
        raise ResourceIdentityFreezeError(
            "resource Registry snapshot contract is invalid"
        ) from exc
    return ResourceIdentityFreeze(snapshot)

__all__ = [
    "RESOURCE_REGISTRY_ISSUANCE_REQUIRED",
    "ResourceIdentityFreeze",
    "ResourceIdentityFreezeError",
    "load_optional_pinned_resource_identity_freeze",
]
