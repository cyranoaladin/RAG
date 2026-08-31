"""Nexus-owned identity projection of the canonical ARIA Resource Registry."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from nexus_contracts.canonical_json import canonical_model_sha256
from nexus_contracts.document import StrictBaseModel
from nexus_contracts.identity import Sha256Digest
from nexus_contracts.servable_corpus_manifest import (
    BoundedVersion,
    GitCommit,
    require_aware_datetime,
)


class RegisteredResourceVersion(StrictBaseModel):
    resource_id: UUID
    resource_version_id: UUID
    content_sha256: Sha256Digest


class ResourceRegistrySnapshotPayload(StrictBaseModel):
    protocol_version: Literal["1"]
    registry_version: BoundedVersion
    producer_repository: Literal["cyranoaladin/nexus-project_v0"]
    producer_commit: GitCommit
    generated_at: datetime
    bootstrap_inventory_sha256: Sha256Digest
    resources: list[RegisteredResourceVersion] = Field(min_length=1)

    _validate_generated_at = field_validator("generated_at")(require_aware_datetime)

    @field_validator("resources")
    @classmethod
    def validate_canonical_unique_resource_versions(
        cls,
        values: list[RegisteredResourceVersion],
    ) -> list[RegisteredResourceVersion]:
        version_ids = [value.resource_version_id for value in values]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError("resource_version_id values must be unique")
        if version_ids != sorted(version_ids, key=str):
            raise ValueError("resources must use canonical resource_version_id order")
        return values


class ResourceRegistrySnapshot(ResourceRegistrySnapshotPayload):
    registry_sha256: Sha256Digest

    def compute_sha256(self) -> str:
        return canonical_model_sha256(self, exclude={"registry_sha256"})

    def payload(self) -> ResourceRegistrySnapshotPayload:
        return ResourceRegistrySnapshotPayload.model_validate(
            self.model_dump(mode="python", exclude={"registry_sha256"})
        )

    @model_validator(mode="after")
    def validate_registry_sha256(self) -> "ResourceRegistrySnapshot":
        if self.registry_sha256 != self.compute_sha256():
            raise ValueError("registry_sha256 does not match canonical payload")
        return self


def seal_resource_registry_snapshot(
    payload: ResourceRegistrySnapshotPayload,
) -> ResourceRegistrySnapshot:
    return ResourceRegistrySnapshot(
        **payload.model_dump(mode="python"),
        registry_sha256=canonical_model_sha256(payload),
    )


__all__ = [
    "RegisteredResourceVersion",
    "ResourceRegistrySnapshot",
    "ResourceRegistrySnapshotPayload",
    "seal_resource_registry_snapshot",
]
