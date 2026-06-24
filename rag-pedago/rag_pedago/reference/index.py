from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from schema.official_reference import (
    CandidateStatusReference,
    EstablishmentContextReference,
    ExamReference,
    OfficialClaim,
    OfficialSource,
    SchoolLevelReference,
    SubjectReference,
)


class OfficialReferenceIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sources: dict[str, OfficialSource]
    levels: dict[str, SchoolLevelReference]
    subjects: dict[str, SubjectReference]
    exams: dict[str, ExamReference]
    candidate_statuses: dict[str, CandidateStatusReference]
    establishment_contexts: dict[str, EstablishmentContextReference]
    claims: dict[str, OfficialClaim]

    def has_level(self, value: str) -> bool:
        return value in self.levels

    def has_subject(self, value: str) -> bool:
        return value in self.subjects

    def has_exam(self, value: str) -> bool:
        return value in self.exams

    def has_candidate_status(self, value: str) -> bool:
        return value in self.candidate_statuses

    def has_claim(self, value: str) -> bool:
        return value in self.claims

    def is_deprecated_candidate_status(self, value: str) -> bool:
        status = self.candidate_statuses.get(value)
        return False if status is None else status.deprecated

    def claim_is_verified(self, value: str) -> bool:
        claim = self.claims.get(value)
        return False if claim is None else claim.verification_status == "verified"

    def source_is_verified(self, value: str) -> bool:
        source = self.sources.get(value)
        return False if source is None else source.verification_status == "verified"

    def source_is_pending(self, value: str) -> bool:
        source = self.sources.get(value)
        return False if source is None else source.verification_status == "pending"
