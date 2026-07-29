from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nexus_contracts.document import Candidat, Niveau, StatutEnseignement, Voie


class PedagogicalProfile(BaseModel):
    """Noyau pedagogique d'une identité interne.

    Champs volontairement resserrés à ce qui est nécessaire dans le cockpit actuel.
    """

    model_config = ConfigDict(extra="forbid")

    voie: Voie = Field(description="Parcours de l'élève")
    matieres: list[str] = Field(min_length=1, description="Matières suivies")
    statut_enseignement: StatutEnseignement = Field(description="Statut pédagogique")
    candidat: Candidat = Field(description="Type de candidat")
    audience: Literal["libre", "aefe", "tous"] = Field(description="Audience ciblée")

    @field_validator("matieres")
    @classmethod
    def validate_matieres(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("matieres cannot contain empty values")
        return cleaned


class InternalIdentity(BaseModel):
    """Contrat d'identité métier produit par le cockpit.

    L'implémentation locale (nexus/contracts) le sérialise et valide strictement.
    """

    model_config = ConfigDict(extra="forbid")

    aud: str = Field(min_length=1)
    exp: int = Field(ge=0)
    iss: str = Field(min_length=1)
    jti: str = Field(min_length=1)
    tenant: str = Field(min_length=1)
    niveau: Niveau = Field(description="Niveau principal du profil")
    role: Literal["student", "teacher", "admin", "ingest_agent", "reviewer"]
    sub: str = Field(min_length=1)
    pedagogical_profile: PedagogicalProfile


__all__ = [
    "InternalIdentity",
    "PedagogicalProfile",
]
