"""Digest-addressed index advertising the active and N-1 corpus manifests."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from nexus_contracts.canonical_json import canonical_model_sha256
from nexus_contracts.document import StrictBaseModel
from nexus_contracts.identity import Sha256Digest
from nexus_contracts.servable_corpus_manifest import (
    BoundedVersion,
    GitCommit,
    RepositoryName,
    require_aware_datetime,
)


class SupportedManifest(StrictBaseModel):
    manifest_version: BoundedVersion
    manifest_sha256: Sha256Digest
    retire_at: datetime | None

    @field_validator("retire_at")
    @classmethod
    def validate_retire_at(cls, value: datetime | None) -> datetime | None:
        return None if value is None else require_aware_datetime(value)


class ServableCorpusIndexPayload(StrictBaseModel):
    protocol_version: Literal["1"]
    producer_repository: RepositoryName
    producer_commit: GitCommit
    generated_at: datetime
    resource_registry_sha256: Sha256Digest
    active_manifest_sha256: Sha256Digest
    supported_manifests: list[SupportedManifest] = Field(min_length=1, max_length=2)

    _validate_generated_at = field_validator("generated_at")(require_aware_datetime)

    @model_validator(mode="after")
    def validate_supported_window(self) -> "ServableCorpusIndexPayload":
        digests = [value.manifest_sha256 for value in self.supported_manifests]
        versions = [value.manifest_version for value in self.supported_manifests]
        if len(digests) != len(set(digests)):
            raise ValueError("supported manifest_sha256 values must be unique")
        if len(versions) != len(set(versions)):
            raise ValueError("supported manifest_version values must be unique")
        active = [
            item
            for item in self.supported_manifests
            if item.manifest_sha256 == self.active_manifest_sha256
        ]
        if len(active) != 1:
            raise ValueError("active_manifest_sha256 must identify one supported manifest")
        if active[0].retire_at is not None:
            raise ValueError("active manifest cannot have retire_at")
        for item in self.supported_manifests:
            if item.retire_at is not None and item.retire_at <= self.generated_at:
                raise ValueError("retire_at must be after generated_at")
        return self


class ServableCorpusIndex(ServableCorpusIndexPayload):
    index_sha256: Sha256Digest

    def compute_sha256(self) -> str:
        return canonical_model_sha256(self, exclude={"index_sha256"})

    def payload(self) -> ServableCorpusIndexPayload:
        return ServableCorpusIndexPayload.model_validate(
            self.model_dump(mode="python", exclude={"index_sha256"})
        )

    @model_validator(mode="after")
    def validate_index_sha256(self) -> "ServableCorpusIndex":
        if self.index_sha256 != self.compute_sha256():
            raise ValueError("index_sha256 does not match canonical payload")
        return self


def seal_servable_corpus_index(
    payload: ServableCorpusIndexPayload,
) -> ServableCorpusIndex:
    return ServableCorpusIndex(
        **payload.model_dump(mode="python"),
        index_sha256=canonical_model_sha256(payload),
    )


__all__ = [
    "ServableCorpusIndex",
    "ServableCorpusIndexPayload",
    "SupportedManifest",
    "seal_servable_corpus_index",
]
