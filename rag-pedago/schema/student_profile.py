from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schema.document import Candidat, Niveau, StatutEnseignement, Voie


class StatusDetail(str, Enum):
    aefe = "aefe"
    systeme_francais_hors_aefe = "systeme_francais_hors_aefe"
    systeme_tunisien = "systeme_tunisien"
    double_cursus = "double_cursus"
    candidat_libre = "candidat_libre"
    cned_reglemente = "cned_reglemente"
    cned_libre = "cned_libre"
    unknown = "unknown"


class StudentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_id: str | None = None
    establishment: str | None = None
    status_detail: StatusDetail = StatusDetail.unknown

    niveau: Niveau
    voie: Voie
    matieres: list[str] = Field(min_length=1)
    statut_enseignement: StatutEnseignement
    candidat: Candidat
    school_year: str = Field(pattern=r"^\d{4}-\d{4}$")
    zone: str = Field(min_length=1)

    specialites: list[str] = Field(default_factory=list)
    options: list[str] = Field(default_factory=list)
    target_pathway: str | None = None
    objective: str | None = None
    risk_level: Literal["low", "medium", "high", "critical"] | None = None
    needs: list[str] = Field(default_factory=list)
    availability: dict[str, object] = Field(default_factory=dict)
    nexus_offer: str | None = None
    nexus_group_id: str | None = None
    teacher_confirmed: bool = False
    school_calendar_zone: str | None = None
    warnings: list[str] = Field(default_factory=list)
    official_level_ref: str | None = None
    candidate_status_ref: str | None = None

    @field_validator("matieres")
    @classmethod
    def validate_matieres(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("matieres cannot contain empty values")
        return cleaned

    @field_validator("school_year")
    @classmethod
    def validate_school_year(cls, value: str) -> str:
        start, end = (int(part) for part in value.split("-"))
        if end != start + 1:
            raise ValueError("school_year must use the form YYYY-YYYY+1")
        if not re.match(r"^\d{4}-\d{4}$", value):
            raise ValueError("school_year must use the form YYYY-YYYY")
        return value

    @field_validator("specialites", "options", "needs")
    @classmethod
    def validate_optional_lists(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("list fields cannot contain empty values")
        return cleaned

    @model_validator(mode="after")
    def populate_warnings(self) -> StudentProfile:
        warnings = list(self.warnings)
        specialites = set(self.specialites)
        options = set(self.options)

        if "maths_expertes" in options and "mathematiques" not in specialites:
            warnings.append("maths_expertes_without_maths_specialite")
        if "maths_complementaires" in options and "mathematiques" in specialites:
            warnings.append("maths_complementaires_with_maths_specialite_kept")
        if self.status_detail is StatusDetail.candidat_libre and self.candidat not in {
            Candidat.individuel,
            Candidat.libre,
            Candidat.cned_libre,
        }:
            warnings.append("status_detail_candidat_libre_mismatch")
        if self.status_detail is StatusDetail.aefe and "aefe" not in self.zone:
            warnings.append("aefe_status_without_aefe_zone")

        self.warnings = sorted(set(warnings))
        return self

    @property
    def primary_matiere(self) -> str:
        return self.matieres[0]

    @property
    def warning_codes(self) -> list[str]:
        return self.warnings
