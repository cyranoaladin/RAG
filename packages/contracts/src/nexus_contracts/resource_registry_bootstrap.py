"""One-time governed export used to bootstrap the Nexus Resource Registry."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictStr, StringConstraints, field_validator, model_validator

from nexus_contracts.canonical_json import canonical_model_sha256
from nexus_contracts.document import Rights, StatutEnseignement, StrictBaseModel, TypeDoc
from nexus_contracts.identity import Sha256Digest
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.servable_corpus_manifest import (
    ChunkIdentifier,
    ChunkLocator,
    GitCommit,
    RepositoryName,
    require_aware_datetime,
)

PackageVersion = Annotated[StrictStr, StringConstraints(pattern=r"^\d+\.\d+\.\d+$")]


class BootstrapChunk(StrictBaseModel):
    chunk_id: ChunkIdentifier
    locator: ChunkLocator


class BootstrapPlacement(ResourceScope):
    statut_enseignement: StatutEnseignement


class BootstrapResourceVersion(StrictBaseModel):
    resource_id: UUID
    resource_version_id: UUID
    content_sha256: Sha256Digest
    rag_artifact_id: Sha256Digest
    size_bytes: int = Field(ge=0)
    mime_type: str = Field(min_length=1, max_length=255)
    source_label: str = Field(min_length=1, max_length=512)
    source_uri: str = Field(min_length=1, max_length=2048)
    rights: Rights
    official: bool
    source_kind: str = Field(min_length=1, max_length=256)
    type_doc: TypeDoc
    placements: list[BootstrapPlacement] = Field(min_length=1)
    chunks: list[BootstrapChunk] = Field(min_length=1)

    @field_validator("source_uri")
    @classmethod
    def validate_source_uri(cls, value: str) -> str:
        if not value.startswith(("https://", "http://")):
            raise ValueError("source_uri must be an HTTP(S) provenance URL")
        return value

    @model_validator(mode="after")
    def validate_rag_artifact_identity(self) -> "BootstrapResourceVersion":
        if self.rag_artifact_id != self.content_sha256:
            raise ValueError("rag_artifact_id must equal content_sha256")
        ids = [item.chunk_id for item in self.chunks]
        if len(ids) != len(set(ids)):
            raise ValueError("chunk_id values must be unique")
        return self


class ResourceRegistryBootstrapPayload(StrictBaseModel):
    protocol_version: Literal["1"]
    producer_repository: RepositoryName
    producer_commit: GitCommit
    package_version: PackageVersion
    source_snapshot_sha256: Sha256Digest
    generated_at: datetime
    resources: list[BootstrapResourceVersion] = Field(min_length=1)

    _validate_generated_at = field_validator("generated_at")(require_aware_datetime)

    @field_validator("resources")
    @classmethod
    def validate_unique_resource_versions(
        cls, values: list[BootstrapResourceVersion]
    ) -> list[BootstrapResourceVersion]:
        version_ids = [value.resource_version_id for value in values]
        if len(version_ids) != len(set(version_ids)):
            raise ValueError("resource_version_id values must be unique")
        return values


class ResourceRegistryBootstrap(ResourceRegistryBootstrapPayload):
    inventory_sha256: Sha256Digest

    def compute_sha256(self) -> str:
        return canonical_model_sha256(self, exclude={"inventory_sha256"})

    def payload(self) -> ResourceRegistryBootstrapPayload:
        return ResourceRegistryBootstrapPayload.model_validate(
            self.model_dump(mode="python", exclude={"inventory_sha256"})
        )

    @model_validator(mode="after")
    def validate_inventory_sha256(self) -> "ResourceRegistryBootstrap":
        if self.inventory_sha256 != self.compute_sha256():
            raise ValueError("inventory_sha256 does not match canonical payload")
        return self


def seal_resource_registry_bootstrap(
    payload: ResourceRegistryBootstrapPayload,
) -> ResourceRegistryBootstrap:
    return ResourceRegistryBootstrap(
        **payload.model_dump(mode="python"),
        inventory_sha256=canonical_model_sha256(payload),
    )


__all__ = [
    "BootstrapChunk",
    "BootstrapPlacement",
    "BootstrapResourceVersion",
    "ResourceRegistryBootstrap",
    "ResourceRegistryBootstrapPayload",
    "seal_resource_registry_bootstrap",
]
