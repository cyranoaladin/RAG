"""Contrats canoniques du protocole de review Nexus."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator

from nexus_contracts.document import StrictBaseModel
from nexus_contracts.identity import BoundedSlug, CollectionName


class ReviewQueuePayload(StrictBaseModel):
    """Paramètres navigateur vers BFF pour consulter la file de review."""

    collection: CollectionName | None = None
    limit: StrictInt = Field(default=50, ge=1, le=500)
    offset: StrictInt = Field(default=0, ge=0)


class ReviewDecisionPayload(StrictBaseModel):
    """Décision navigateur vers BFF, sans identité ni texte libre."""

    target_type: Literal["doc", "chunk"] = "doc"
    target_id: StrictStr = Field(min_length=1, max_length=256)
    decision: Literal["reviewed", "quarantined"]
    collection: CollectionName | None = None


class ReviewDecisionRequest(StrictBaseModel):
    """Décision BFF vers moteur enrichie du tenant signé."""

    target_type: Literal["doc", "chunk"] = "doc"
    target_id: StrictStr = Field(min_length=1, max_length=256)
    decision: Literal["reviewed", "quarantined"]
    collection: CollectionName | None = None
    tenant: BoundedSlug


class ReviewQueueDocument(StrictBaseModel):
    """Document en attente exposé par la file de review."""

    doc_id: StrictStr = Field(min_length=1, max_length=256)
    collection: CollectionName
    source_label: StrictStr
    source_uri: StrictStr
    rights: StrictStr
    source_kind: StrictStr
    type_doc: StrictStr
    chunk_count: StrictInt = Field(ge=1)
    first_indexed: datetime | None
    last_indexed: datetime | None


class ReviewQueueResponse(StrictBaseModel):
    """Page de documents en attente retournée par le moteur."""

    total_pending_docs: StrictInt = Field(ge=0)
    returned: StrictInt = Field(ge=0)
    offset: StrictInt = Field(ge=0)
    documents: list[ReviewQueueDocument]

    @model_validator(mode="after")
    def validate_returned_count(self) -> ReviewQueueResponse:
        if self.returned != len(self.documents):
            raise ValueError("returned must equal len(documents)")
        return self


class ReviewDecisionResponse(StrictBaseModel):
    """Résultat borné d'une décision de review."""

    target_type: Literal["doc", "chunk"]
    target_id: StrictStr = Field(min_length=1, max_length=256)
    decision: Literal["reviewed", "quarantined"]
    chunks_affected: StrictInt = Field(ge=1)
    cache_invalidated_this_worker: StrictBool
    max_stale_other_workers_s: Literal[0]

    @field_validator("max_stale_other_workers_s", mode="before")
    @classmethod
    def validate_exact_zero(cls, value: object) -> int:
        if type(value) is not int or value != 0:
            raise ValueError("max_stale_other_workers_s must be the integer 0")
        return value


__all__ = [
    "ReviewDecisionPayload",
    "ReviewDecisionRequest",
    "ReviewDecisionResponse",
    "ReviewQueueDocument",
    "ReviewQueuePayload",
    "ReviewQueueResponse",
]
