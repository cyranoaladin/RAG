from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from schema.document import Niveau, Rights, SourceType, TypeDoc


class SourceAuthorityLevel(str, Enum):
    official_verified = "official_verified"
    official_unverified = "official_unverified"
    nexus_validated = "nexus_validated"
    imported_unverified = "imported_unverified"
    generated_draft = "generated_draft"
    unknown = "unknown"


class VerificationStatus(str, Enum):
    verified = "verified"
    pending = "pending"
    failed = "failed"
    draft = "draft"
    unknown = "unknown"


class SourceManifestItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_name: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    title: str | None = None
    detected_matiere: str | None = None
    detected_niveau: Niveau | None = None
    detected_type_doc: TypeDoc | None = None
    source_type: SourceType = SourceType.unknown
    rights: Rights
    fetched: bool = False
    sha256: str | None = Field(default=None, pattern=r"^[a-fA-F0-9]{64}$")
    discovered_at: datetime


class SourceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: str = Field(min_length=1)
    allowed_domains: list[str] = Field(default_factory=list)
    purposes: list[str] = Field(default_factory=list)
    scrape_policy: str | None = None
    robots_required: bool = True
    rate_limit_seconds: int = Field(default=2, ge=0)


class SourceTrust(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: SourceType
    authority_level: SourceAuthorityLevel
    last_verified_at: datetime | None = None
    verification_status: VerificationStatus = VerificationStatus.unknown
    official_url: str | None = None
    official_source_ref: str | None = None
    retrieval_allowed: bool | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def derive_retrieval_allowed(self) -> SourceTrust:
        if self.retrieval_allowed is not None:
            return self
        self.retrieval_allowed = self.authority_level in {
            SourceAuthorityLevel.official_verified,
            SourceAuthorityLevel.nexus_validated,
        }
        return self
