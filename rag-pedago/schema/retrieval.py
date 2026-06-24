from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from schema.document import TypeDoc
from schema.student_profile import StudentProfile


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


class RetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_profile: StudentProfile
    need: RetrievalNeed
    retrieval: RetrievalOptions = Field(default_factory=RetrievalOptions)

    def to_payload_filters(self) -> dict[str, str]:
        return {
            "niveau": self.student_profile.niveau.value,
            "voie": self.student_profile.voie.value,
            "matiere": self.student_profile.primary_matiere,
            "statut_enseignement": self.student_profile.statut_enseignement.value,
            "candidat": self.student_profile.candidat.value,
        }


class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_label: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)
    source_uri: str = Field(min_length=1)
    rights: str = Field(min_length=1)


class RetrievalResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    score: float = Field(ge=0)
    title: str | None = None
    excerpt: str = Field(min_length=1)
    citation: Citation | None = None
    metadata: dict[str, object] = Field(default_factory=dict)


class RetrievalResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    results: list[RetrievalResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    filters_applied: dict[str, object] = Field(default_factory=dict)

