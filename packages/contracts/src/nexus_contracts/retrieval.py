from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)

from nexus_contracts.document import Niveau, StatutEnseignement, TypeDoc, Voie
from nexus_contracts.identity import BoundedIdentifier, BoundedSlug, Sha256Digest
from nexus_contracts.servable_corpus_manifest import ChunkLocator
from nexus_contracts.student_profile import StudentProfile


class RetrievalNeed(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["remediation", "revision", "exercise", "program", "exam_prep", "context"]
    query: str = Field(min_length=1)
    notions: list[str] = Field(default_factory=list)
    desired_doc_types: list[TypeDoc] = Field(default_factory=list)
    difficulty_max: int | None = Field(default=None, ge=1, le=5)

    @field_validator("notions")
    @classmethod
    def validate_notions(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("notions cannot contain empty values")
        return cleaned


class RetrievalOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")

    k: int = Field(default=8, ge=1, le=50)
    hybrid: bool = True
    rerank: bool = True
    include_citations: bool = True


class RetrievalCurriculumScope(BaseModel):
    """Portée de la preuve pédagogique, distincte de la cible élève."""

    model_config = ConfigDict(extra="forbid")

    niveau: Niveau
    voie: Voie
    matiere: BoundedSlug
    statut_enseignement: StatutEnseignement


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_profile: StudentProfile
    curriculum_scope: RetrievalCurriculumScope | None = None
    need: RetrievalNeed
    retrieval: RetrievalOptions = Field(default_factory=RetrievalOptions)
    manifest_sha256: Sha256Digest | None = None
    corpus_id: BoundedIdentifier | None = None
    corpus_version_id: BoundedIdentifier | None = None

    @model_validator(mode="after")
    def validate_manifest_binding(self) -> "RetrievalRequest":
        binding = (self.manifest_sha256, self.corpus_id, self.corpus_version_id)
        if any(value is not None for value in binding) and any(
            value is None for value in binding
        ):
            raise ValueError(
                "manifest_sha256, corpus_id, and corpus_version_id must be provided together"
            )
        return self

    def to_payload_filters(self) -> dict[str, str]:
        curriculum = self.curriculum_scope
        return {
            "niveau": (
                curriculum.niveau.value
                if curriculum is not None
                else self.student_profile.niveau.value
            ),
            "voie": (
                curriculum.voie.value
                if curriculum is not None
                else self.student_profile.voie.value
            ),
            "matiere": (
                curriculum.matiere
                if curriculum is not None
                else self.student_profile.primary_matiere
            ),
            "statut_enseignement": (
                curriculum.statut_enseignement.value
                if curriculum is not None
                else self.student_profile.statut_enseignement.value
            ),
            "candidat": self.student_profile.candidat.value,
            "audience": self.student_profile.audience,
        }


class Citation(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "dependentRequired": {
                name: [
                    "licensor",
                    "licence_id",
                    "source_updated_at",
                    "derivative_notice",
                    "page",
                ]
                for name in (
                    "licensor",
                    "licence_id",
                    "source_updated_at",
                    "derivative_notice",
                )
            },
            "dependentSchemas": {
                name: {
                    "properties": {
                        "licensor": {"type": "string"},
                        "licence_id": {"type": "string"},
                        "source_updated_at": {"type": "string"},
                        "derivative_notice": {"type": "string"},
                        "page": {"type": "integer", "minimum": 1},
                    }
                }
                for name in (
                    "licensor",
                    "licence_id",
                    "source_updated_at",
                    "derivative_notice",
                )
            },
        },
    )

    source_label: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    source_uri: str = Field(min_length=1)
    rights: str = Field(min_length=1)
    # Les citations historiques restent inchangées ; les dérivés publics
    # portent les quatre éléments d'attribution comme un bloc indivisible.
    licensor: str | None = Field(default=None, min_length=1)
    licence_id: str | None = Field(default=None, min_length=1)
    source_updated_at: str | None = Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)?$",
    )
    derivative_notice: str | None = Field(default=None, min_length=1)

    @model_serializer(mode="wrap")
    def serialize_without_absent_attribution(
        self, handler: SerializerFunctionWrapHandler
    ) -> dict[str, Any]:
        payload: dict[str, Any] = handler(self)
        for name in ("licensor", "licence_id", "source_updated_at", "derivative_notice"):
            if payload.get(name) is None:
                payload.pop(name, None)
        return payload

    @model_validator(mode="after")
    def validate_public_derivative_attribution(self) -> "Citation":
        attribution = (
            self.licensor,
            self.licence_id,
            self.source_updated_at,
            self.derivative_notice,
        )
        if any(value is not None for value in attribution) and any(
            value is None for value in attribution
        ):
            raise ValueError("public derivative attribution must be complete")
        if all(value is not None for value in attribution) and self.page is None:
            raise ValueError("public derivative attribution requires page")
        return self


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    score: float = Field(ge=0)
    title: str | None = None
    excerpt: str = Field(min_length=1)
    citation: Citation | None = None
    metadata: dict[str, object] = Field(default_factory=dict)
    resource_id: UUID | None = None
    resource_version_id: UUID | None = None
    content_sha256: Sha256Digest | None = None
    locator: ChunkLocator | None = None
    corpus_id: BoundedIdentifier | None = None
    corpus_version_id: BoundedIdentifier | None = None
    manifest_sha256: Sha256Digest | None = None

    @model_validator(mode="after")
    def validate_canonical_resource_identity(self) -> "RetrievalResult":
        identity = (
            self.resource_id,
            self.resource_version_id,
            self.content_sha256,
            self.locator,
            self.corpus_id,
            self.corpus_version_id,
            self.manifest_sha256,
        )
        if any(value is not None for value in identity) and any(
            value is None for value in identity
        ):
            raise ValueError(
                "canonical retrieval identity fields must be provided together"
            )
        return self


class RetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[RetrievalResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    filters_applied: dict[str, object] = Field(default_factory=dict)


class RetrievalError(BaseModel):
    """Stable machine-readable retrieval failure without provider detail."""

    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "NOT_CONFIGURED",
        "NO_RESULTS",
        "RUNTIME_UNAVAILABLE",
        "TIMEOUT",
        "INVALID_MANIFEST",
        "MANIFEST_VERSION_MISMATCH",
    ]
    request_id: BoundedIdentifier
    retryable: bool
