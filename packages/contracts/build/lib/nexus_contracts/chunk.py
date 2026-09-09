from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexus_contracts.document import Niveau, TypeDoc, Voie


class Audience(str, Enum):
    libre = "libre"
    aefe = "aefe"
    tous = "tous"


class ChunkMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant: str = Field(min_length=1)
    niveau: Niveau
    voie: Voie
    matiere: str = Field(min_length=1)
    audience: list[Audience] = Field(min_length=1)
    type_doc: TypeDoc
    notions: list[str] = Field(default_factory=list)
    source_label: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    rights: str = Field(min_length=1)
    official: bool
    doc_id: str = Field(min_length=1)

    difficulte: int | None = Field(default=None, ge=1, le=5)
    page: int | None = Field(default=None, ge=1)
    chapitre: str | None = None

    @field_validator("audience")
    @classmethod
    def validate_audience_no_duplicates(cls, values: list[Audience]) -> list[Audience]:
        if len(values) != len(set(values)):
            raise ValueError("audience must not contain duplicates")
        return values

    @field_validator("notions")
    @classmethod
    def validate_notions(cls, values: list[str]) -> list[str]:
        cleaned = [v.strip() for v in values]
        if any(not v for v in cleaned):
            raise ValueError("notions cannot contain empty values")
        return cleaned
