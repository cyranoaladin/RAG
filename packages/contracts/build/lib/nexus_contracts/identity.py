"""Contrats canoniques de l'identité interne Nexus."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import (
    Field,
    StrictInt,
    StrictStr,
    StringConstraints,
    field_validator,
    model_validator,
)

from nexus_contracts.document import (
    Candidat,
    Niveau,
    StatutEnseignement,
    StrictBaseModel,
    Voie,
)
from nexus_contracts.canonical_json import canonical_model_bytes

JS_SAFE_INTEGER = 9_007_199_254_740_991

BoundedIdentifier = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$"),
]
BoundedSlug = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=100, pattern=r"^[a-z0-9_]+$"),
]
CollectionName = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=128, pattern=r"^[a-z0-9_]+$"),
]
ExternalTokenParty = Annotated[
    StrictStr,
    StringConstraints(min_length=1, max_length=256),
]
PseudonymousSubject = Annotated[
    StrictStr,
    StringConstraints(
        min_length=20,
        max_length=128,
        pattern=r"^psn_[A-Za-z0-9_-]+$",
    ),
]
TokenIdentifier = Annotated[
    StrictStr,
    StringConstraints(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9_-]+$",
    ),
]
SchoolYear = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^\d{4}-\d{4}$"),
]
Sha256Digest = Annotated[
    StrictStr,
    StringConstraints(pattern=r"^[0-9a-f]{64}$"),
]
StrictTimestamp = Annotated[
    StrictInt,
    Field(gt=0, le=JS_SAFE_INTEGER),
]


def require_consecutive_school_year(value: str) -> str:
    start, end = (int(part) for part in value.split("-"))
    if end != start + 1:
        raise ValueError("school_year must use the form YYYY-YYYY+1")
    return value


class PedagogicalProfile(StrictBaseModel):
    """Sous-ensemble pédagogique fermé, sans identifiant ni champ libre."""

    voie: Voie = Field(description="Parcours de l'élève")
    matieres: list[BoundedSlug] = Field(
        min_length=1,
        max_length=16,
        description="Matières suivies",
        json_schema_extra={"uniqueItems": True},
    )
    statut_enseignement: StatutEnseignement = Field(description="Statut pédagogique")
    candidat: Candidat = Field(description="Type de candidat")
    audience: Literal["libre", "aefe", "tous"] = Field(
        description="Audience ciblée"
    )

    @field_validator("matieres")
    @classmethod
    def validate_matieres(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("matieres cannot contain duplicates")
        return values


class InternalIdentity(StrictBaseModel):
    """Claims minimaux produits par le cockpit et consommés par rag-engine."""

    aud: BoundedIdentifier
    exp: StrictTimestamp
    iss: BoundedIdentifier
    jti: TokenIdentifier
    tenant: BoundedSlug
    niveau: Niveau = Field(description="Niveau principal du profil")
    role: Literal["student", "teacher", "admin", "ingest_agent", "reviewer"]
    school_year: SchoolYear
    sub: PseudonymousSubject
    pedagogical_profile: PedagogicalProfile

    @field_validator("school_year")
    @classmethod
    def validate_school_year(cls, value: str) -> str:
        return require_consecutive_school_year(value)


class InternalIdentityEnvelope(StrictBaseModel):
    """Enveloppe signée liant le transport à une identité et à un scope."""

    protocol_version: Literal["1"]
    iss: ExternalTokenParty
    aud: ExternalTokenParty
    sub: PseudonymousSubject
    jti: TokenIdentifier
    iat: StrictTimestamp
    exp: StrictTimestamp
    identity: InternalIdentity
    scope_id: BoundedSlug
    scope_digest: Sha256Digest
    request_sha256: Sha256Digest | None = None
    manifest_sha256: Sha256Digest | None = None
    allowed_collections: list[CollectionName] = Field(
        min_length=1,
        max_length=16,
        json_schema_extra={"uniqueItems": True},
    )

    @field_validator("allowed_collections")
    @classmethod
    def validate_allowed_collections(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("allowed_collections cannot contain duplicates")
        return values

    @model_validator(mode="after")
    def validate_transport_bindings(self) -> InternalIdentityEnvelope:
        if self.sub != self.identity.sub:
            raise ValueError("sub must equal identity.sub")
        if self.jti != self.identity.jti:
            raise ValueError("jti must equal identity.jti")
        if self.exp > self.identity.exp:
            raise ValueError("exp cannot exceed identity.exp")
        if self.iat > self.exp:
            raise ValueError("iat cannot exceed exp")
        if (self.request_sha256 is None) != (self.manifest_sha256 is None):
            raise ValueError(
                "request_sha256 and manifest_sha256 must be provided together"
            )
        if self.request_sha256 is not None and self.exp - self.iat > 30:
            raise ValueError("manifest-bound envelopes cannot exceed 30 seconds")
        return self


def canonical_identity_envelope_bytes(envelope: InternalIdentityEnvelope) -> bytes:
    """Return stable bytes for cross-runtime signing and verification."""

    return canonical_model_bytes(envelope)


__all__ = [
    "InternalIdentity",
    "InternalIdentityEnvelope",
    "PedagogicalProfile",
    "canonical_identity_envelope_bytes",
]
