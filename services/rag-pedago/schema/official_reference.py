from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class StrictOfficialBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfficialSource(StrictOfficialBase):
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    authority_level: str = Field(min_length=1)
    verification_status: str = "pending"
    last_verified_at: datetime
    applies_to: list[str] = Field(min_length=1)
    notes: str | None = None

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        HttpUrl(value)
        return value

    @model_validator(mode="after")
    def validate_authority_consistency(self) -> OfficialSource:
        if self.authority_level == "official_verified" and self.verification_status != "verified":
            raise ValueError("official_verified sources must have verification_status=verified")
        return self


class SchoolLevelReference(StrictOfficialBase):
    level_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    cycle: str | None = None
    voie: str | None = None
    school_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    common_subjects: list[str] = Field(min_length=1)
    optional_subjects: list[str] = Field(default_factory=list)
    specialties_available: list[str] = Field(default_factory=list)
    expected_specialties_count: int | None = Field(default=None, ge=0)
    expected_outcomes_ref: list[str] = Field(default_factory=list)
    exam_refs: list[str] = Field(default_factory=list)
    official_sources: list[str] = Field(min_length=1)
    verification_status: str = "verified"
    warnings: list[str] = Field(default_factory=list)


class SubjectReference(StrictOfficialBase):
    subject_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    level_id: str = Field(min_length=1)
    is_common: bool = False
    is_specialty: bool = False
    is_option: bool = False
    weekly_hours: float | None = Field(default=None, ge=0)
    annual_hours: float | None = Field(default=None, ge=0)
    programme_version: str | None = None
    taxonomy_id: str | None = None
    allowed_level_ids: list[str] = Field(default_factory=list)
    requires_subjects: list[str] = Field(default_factory=list)
    excludes_terminal_specialties: list[str] = Field(default_factory=list)
    verification_status: str = "verified"
    official_sources: list[str] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class ExamReference(StrictOfficialBase):
    exam_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    level_id: str = Field(min_length=1)
    session: int | None = Field(default=None, ge=1900, le=2200)
    candidate_types: list[str] = Field(min_length=1)
    exam_parts: list[str] = Field(min_length=1)
    is_anticipated: bool = False
    is_terminal: bool = False
    control_continu_weight: float | None = Field(default=None, ge=0, le=100)
    terminal_weight: float | None = Field(default=None, ge=0, le=100)
    coefficients: dict[str, float] = Field(default_factory=dict)
    durations: dict[str, str] = Field(default_factory=dict)
    related_subject_refs: list[str] = Field(default_factory=list)
    verification_status: str = "verified"
    official_sources: list[str] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)


class CandidateStatusReference(StrictOfficialBase):
    status_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    applies_to_levels: list[str] = Field(min_length=1)
    control_continu_mode: str | None = None
    exam_mode: str | None = None
    registration_notes: list[str] = Field(default_factory=list)
    documents_required: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    deprecated: bool = False
    aliases: list[str] = Field(default_factory=list)
    verification_status: str = "verified"
    official_sources: list[str] = Field(min_length=1)


class EstablishmentContextReference(StrictOfficialBase):
    context_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    description: str = Field(min_length=1)
    official_sources: list[str] = Field(min_length=1)
    warnings: list[str] = Field(default_factory=list)
    verification_status: str = "verified"


class OfficialClaim(StrictOfficialBase):
    claim_id: str = Field(min_length=1)
    statement: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    verification_status: str = Field(min_length=1)
    applies_to: list[str] = Field(min_length=1)
    fields_supported: list[str] = Field(min_length=1)
    notes: str | None = None
