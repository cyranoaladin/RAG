"""Chat contracts for conversational responses.

These models are intentionally strict: the assistant must answer with explicit
structure and citations tied to retrieved chunks.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nexus_contracts.retrieval import RetrievalResult
from nexus_contracts.student_profile import StudentProfile


class ChatRole(str):
    ...


class ChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["system", "user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class SearchPayload(BaseModel):
    """Browser-to-BFF search input; no identity or server credentials."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    collections: list[str] = Field(min_length=1)
    k: int | None = Field(default=None, ge=1, le=50)

    @field_validator("collections")
    @classmethod
    def validate_search_collections(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("collections cannot contain empty values")
        return cleaned


class ChatPayload(BaseModel):
    """Browser-to-BFF chat input; the BFF alone builds the learner profile."""

    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1, max_length=2000)
    collections: list[str] = Field(min_length=1)
    top_k: int | None = Field(default=None, ge=1, le=20)
    history: list[ChatMessage] | None = None

    @field_validator("collections")
    @classmethod
    def validate_chat_collections(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        if any(not value for value in cleaned):
            raise ValueError("collections cannot contain empty values")
        return cleaned


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    student_profile: StudentProfile
    query: str = Field(min_length=1, max_length=2000)
    collections: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)
    history: list[ChatMessage] = Field(default_factory=list)
    answer_max_chars: int = Field(default=1800, ge=120, le=4000)
    include_retrieval: bool = True

    @field_validator("collections")
    @classmethod
    def validate_collections(cls, values: list[str]) -> list[str]:
        cleaned = [value.strip() for value in values]
        normalized = [value for value in cleaned if value]
        if not normalized:
            raise ValueError("collections cannot be empty")
        return normalized


class ChatCitation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chunk_id: str = Field(min_length=1)
    doc_id: str = Field(min_length=1)
    source_label: str = Field(min_length=1)
    source_uri: str = Field(min_length=1)
    rights: str = Field(min_length=1)
    page: int | None = Field(default=None, ge=1)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1)
    grounded: bool = Field(default=True)
    citations: list[ChatCitation] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    refusal_reason: str | None = None
    retrieval_hits: list[RetrievalResult] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_grounding_or_refusal(self) -> ChatResponse:
        if self.grounded and not self.citations:
            raise ValueError("grounded responses require citations")
        if not self.grounded and not self.refusal_reason:
            raise ValueError("ungrounded responses require refusal_reason")
        return self
