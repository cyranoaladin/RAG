from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schema.document import Candidat, Niveau


class ModalitePonctuelle(str, Enum):
    A = "A"
    B = "B"
    unknown = "unknown"


class ExamProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    niveau: Niveau
    session: int = Field(ge=1900, le=2200)
    school_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    candidat: Candidat
    zone: str = Field(min_length=1)
    exam_center: str | None = None
    registration_status: str | None = None
    convocation_status: str | None = None
    modalite_ponctuelles: ModalitePonctuelle = ModalitePonctuelle.unknown

    epreuves_a_passer: list[str] = Field(default_factory=list)
    epreuves_deja_validees: list[str] = Field(default_factory=list)
    epreuves_a_repasser: list[str] = Field(default_factory=list)
    notes_connues: dict[str, float] = Field(default_factory=dict)
    options: list[str] = Field(default_factory=list)
    specialites_premiere: list[str] = Field(default_factory=list)
    specialites_terminale: list[str] = Field(default_factory=list)
    specialite_abandonnee: str | None = None
    grand_oral_required: bool = True
    documents_required: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    official_level_ref: str | None = None
    official_exam_ref: str | None = None
    candidate_status_ref: str | None = None
    validation_mode: Literal["warn", "strict"] = "warn"

    @field_validator("school_year")
    @classmethod
    def validate_school_year(cls, value: str) -> str:
        if not re.match(r"^\d{4}-\d{4}$", value):
            raise ValueError("school_year must use the form YYYY-YYYY")
        start, end = (int(part) for part in value.split("-"))
        if end != start + 1:
            raise ValueError("school_year must use the form YYYY-YYYY+1")
        return value

    @field_validator(
        "epreuves_a_passer",
        "epreuves_deja_validees",
        "epreuves_a_repasser",
        "options",
        "specialites_premiere",
        "specialites_terminale",
        "documents_required",
    )
    @classmethod
    def validate_lists(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("list fields cannot contain empty values")
        return cleaned

    @model_validator(mode="after")
    def populate_warnings(self) -> ExamProfile:
        warnings = set(self.warnings)
        options = set(self.options)
        terminale_specialities = set(self.specialites_terminale)

        is_free_candidate = self.candidat in {Candidat.individuel, Candidat.libre, Candidat.cned_libre}

        if self.niveau is Niveau.terminale and len(terminale_specialities) < 2:
            warnings.add("terminale_generale_less_than_two_eds")
        if self.niveau is Niveau.premiere and len(self.specialites_premiere) < 3:
            warnings.add("premiere_generale_less_than_three_eds")
        if is_free_candidate and self.modalite_ponctuelles is ModalitePonctuelle.unknown:
            warnings.add("candidat_libre_modalite_ponctuelle_unknown")
        if is_free_candidate and self.niveau is Niveau.terminale and len(terminale_specialities) < 2:
            warnings.add("candidat_libre_terminale_without_two_specialities")
        if "maths_expertes" in options and "mathematiques" not in terminale_specialities:
            warnings.add("maths_expertes_without_maths_specialite")
        if "maths_complementaires" in options and "mathematiques" in terminale_specialities:
            warnings.add("maths_complementaires_with_maths_specialite_kept")

        self.warnings = sorted(warnings)

        if self.validation_mode == "strict" and self.warnings:
            raise ValueError(f"exam profile warnings in strict mode: {', '.join(self.warnings)}")
        return self

    @property
    def warning_codes(self) -> list[str]:
        return self.warnings
