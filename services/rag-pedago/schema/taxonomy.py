from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from schema.document import Niveau, StatutEnseignement, Voie


NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class Notion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStr
    label: NonEmptyStr | None = None
    subnotions: list[NonEmptyStr] = Field(default_factory=list)

    @classmethod
    def from_raw(cls, value: Any) -> Notion:
        if isinstance(value, str):
            return cls(id=value, label=value)
        if isinstance(value, dict):
            return cls.model_validate(value)
        raise TypeError("notion must be a string or mapping")


class Theme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStr
    label: NonEmptyStr
    notions: list[Notion] = Field(default_factory=list)

    @field_validator("notions", mode="before")
    @classmethod
    def normalize_notions(cls, values: Any) -> list[Any]:
        if values is None:
            return []
        return [Notion.from_raw(value) for value in values]


class TaxonomySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStr
    matiere: NonEmptyStr
    niveau: Niveau
    voie: Voie
    statut_enseignement: StatutEnseignement
    programme_version: NonEmptyStr
    themes: list[Theme] = Field(min_length=1)
    competences: list[NonEmptyStr] = Field(default_factory=list)

    @property
    def known_notion_ids(self) -> set[str]:
        ids: set[str] = set()
        for theme in self.themes:
            for notion in theme.notions:
                ids.add(notion.id)
                ids.update(notion.subnotions)
        return ids

