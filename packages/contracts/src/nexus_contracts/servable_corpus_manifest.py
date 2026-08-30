"""Versioned servable-corpus manifest referencing Nexus ResourceVersions."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, StrictStr, StringConstraints, field_validator, model_validator

from nexus_contracts.canonical_json import canonical_model_sha256
from nexus_contracts.document import StrictBaseModel
from nexus_contracts.identity import (
    CollectionName,
    SchoolYear,
    Sha256Digest,
    require_consecutive_school_year,
)

BoundedVersion = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$"),
]
GitCommit = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$"),
]
RepositoryName = Annotated[
    StrictStr,
    StringConstraints(
        min_length=3,
        max_length=200,
        pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
    ),
]
ChunkIdentifier = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9_.:-]+$"),
]


def require_aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


class ChunkLocator(StrictBaseModel):
    chunk_index: int | None = Field(default=None, ge=0)
    page: int | None = Field(default=None, ge=1)
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    section: str | None = Field(default=None, min_length=1, max_length=200)
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_locator(self) -> "ChunkLocator":
        if all(
            value is None
            for value in (
                self.page,
                self.chunk_index,
                self.page_start,
                self.page_end,
                self.section,
                self.start_char,
                self.end_char,
            )
        ):
            raise ValueError("locator must contain page, section, or character bounds")
        if (self.page_start is None) != (self.page_end is None):
            raise ValueError("page_start and page_end must be provided together")
        if self.page is not None and self.page_start is not None:
            raise ValueError("page and page range are mutually exclusive")
        if self.page_start is not None and self.page_end is not None:
            if self.page_end < self.page_start:
                raise ValueError("page_end cannot precede page_start")
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("start_char and end_char must be provided together")
        if self.start_char is not None and self.end_char is not None:
            if self.end_char <= self.start_char:
                raise ValueError("end_char must be greater than start_char")
        return self


class CorpusChunkBinding(StrictBaseModel):
    chunk_id: ChunkIdentifier
    locator: ChunkLocator


class CorpusResourceVersion(StrictBaseModel):
    resource_id: UUID
    resource_version_id: UUID
    content_sha256: Sha256Digest
    chunks: list[CorpusChunkBinding] = Field(min_length=1)

    @field_validator("chunks")
    @classmethod
    def validate_unique_chunks(
        cls, values: list[CorpusChunkBinding]
    ) -> list[CorpusChunkBinding]:
        ids = [value.chunk_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("chunk_id values must be unique")
        return values


class ServableCorpus(StrictBaseModel):
    corpus_id: BoundedVersion
    corpus_version_id: BoundedVersion
    academic_year: SchoolYear
    curriculum_version: BoundedVersion
    physical_collection: CollectionName
    scope_id: BoundedVersion
    scope_sha256: Sha256Digest
    resources: list[CorpusResourceVersion] = Field(min_length=1)

    _validate_academic_year = field_validator("academic_year")(
        require_consecutive_school_year
    )

    @field_validator("resources")
    @classmethod
    def validate_unique_resource_versions(
        cls, values: list[CorpusResourceVersion]
    ) -> list[CorpusResourceVersion]:
        ids = [value.resource_version_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("resource_version_id values must be unique in a corpus")
        return values


class ServableCorpusManifestPayload(StrictBaseModel):
    protocol_version: Literal["1"]
    manifest_version: BoundedVersion
    resource_registry_version: BoundedVersion
    resource_registry_sha256: Sha256Digest
    producer_repository: RepositoryName
    producer_commit: GitCommit
    generated_at: datetime
    corpora: list[ServableCorpus] = Field(min_length=1)

    _validate_generated_at = field_validator("generated_at")(require_aware_datetime)

    @field_validator("corpora")
    @classmethod
    def validate_unique_corpora(cls, values: list[ServableCorpus]) -> list[ServableCorpus]:
        ids = [(value.corpus_id, value.corpus_version_id) for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("corpus_id/corpus_version_id pairs must be unique")
        return values


class ServableCorpusManifest(ServableCorpusManifestPayload):
    manifest_sha256: Sha256Digest

    def compute_sha256(self) -> str:
        return canonical_model_sha256(self, exclude={"manifest_sha256"})

    def payload(self) -> ServableCorpusManifestPayload:
        return ServableCorpusManifestPayload.model_validate(
            self.model_dump(mode="python", exclude={"manifest_sha256"})
        )

    @model_validator(mode="after")
    def validate_manifest_sha256(self) -> "ServableCorpusManifest":
        if self.manifest_sha256 != self.compute_sha256():
            raise ValueError("manifest_sha256 does not match canonical payload")
        return self


def seal_servable_corpus_manifest(
    payload: ServableCorpusManifestPayload,
) -> ServableCorpusManifest:
    return ServableCorpusManifest(
        **payload.model_dump(mode="python"),
        manifest_sha256=canonical_model_sha256(payload),
    )


__all__ = [
    "BoundedVersion",
    "ChunkIdentifier",
    "ChunkLocator",
    "CorpusChunkBinding",
    "CorpusResourceVersion",
    "GitCommit",
    "RepositoryName",
    "ServableCorpus",
    "ServableCorpusManifest",
    "ServableCorpusManifestPayload",
    "require_aware_datetime",
    "seal_servable_corpus_manifest",
]
