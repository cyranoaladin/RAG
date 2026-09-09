"""Strict, manifest-bound retrieval evaluation suite and evidence contracts."""

from __future__ import annotations

import math
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BeforeValidator, Field, field_validator, model_validator

from nexus_contracts.canonical_json import canonical_model_sha256
from nexus_contracts.document import StrictBaseModel
from nexus_contracts.identity import Sha256Digest
from nexus_contracts.servable_corpus_manifest import (
    BoundedVersion,
    ChunkIdentifier,
    ChunkLocator,
    GitCommit,
    RepositoryName,
    require_aware_datetime,
)


def _finite_number(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("score must be a finite number")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("score must be a finite number")
    return parsed


FiniteNonNegative = Annotated[float, BeforeValidator(_finite_number), Field(ge=0)]
FiniteRatio = Annotated[float, BeforeValidator(_finite_number), Field(ge=0, le=1)]


class RetrievalGoldenQueryV1(StrictBaseModel):
    id: BoundedVersion
    query: str = Field(min_length=1, max_length=2_000)
    intent: Literal["remediation", "revision", "exercise", "program", "exam_prep", "context"]
    relevant_chunk_ids: list[ChunkIdentifier] = Field(min_length=1)
    graded_relevance: dict[ChunkIdentifier, FiniteNonNegative]
    must_not_return: list[ChunkIdentifier]

    @model_validator(mode="after")
    def validate_judgments(self) -> "RetrievalGoldenQueryV1":
        relevant = self.relevant_chunk_ids
        forbidden = self.must_not_return
        if len(relevant) != len(set(relevant)) or len(forbidden) != len(set(forbidden)):
            raise ValueError("chunk judgments must be unique")
        positive = {
            chunk_id for chunk_id, score in self.graded_relevance.items() if score > 0
        }
        if positive != set(relevant):
            raise ValueError("positive graded relevance must equal relevant_chunk_ids")
        if set(relevant).intersection(forbidden):
            raise ValueError("relevant and forbidden chunks must be disjoint")
        return self


class RetrievalGoldenSuitePayloadV1(StrictBaseModel):
    protocol_version: Literal["1"]
    suite_id: BoundedVersion
    manifest_sha256: Sha256Digest
    corpus_id: BoundedVersion
    corpus_version_id: BoundedVersion
    human_review_status: Literal["PENDING_HUMAN_REVIEW"]
    queries: list[RetrievalGoldenQueryV1] = Field(min_length=1)

    @field_validator("queries")
    @classmethod
    def validate_unique_query_ids(
        cls,
        values: list[RetrievalGoldenQueryV1],
    ) -> list[RetrievalGoldenQueryV1]:
        ids = [value.id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("query ids must be unique")
        return values


class RetrievalGoldenSuiteV1(RetrievalGoldenSuitePayloadV1):
    suite_sha256: Sha256Digest

    def compute_sha256(self) -> str:
        return canonical_model_sha256(self, exclude={"suite_sha256"})

    @model_validator(mode="after")
    def validate_suite_sha256(self) -> "RetrievalGoldenSuiteV1":
        if self.suite_sha256 != self.compute_sha256():
            raise ValueError("suite_sha256 does not match canonical payload")
        return self


def seal_retrieval_golden_suite(
    payload: RetrievalGoldenSuitePayloadV1,
) -> RetrievalGoldenSuiteV1:
    return RetrievalGoldenSuiteV1(
        **payload.model_dump(mode="python"),
        suite_sha256=canonical_model_sha256(payload),
    )


class RetrievalEvaluationConfigurationV1(StrictBaseModel):
    top_k: int = Field(ge=1, le=50)
    hybrid: bool
    rerank: bool
    embedding_model: str = Field(min_length=1, max_length=200)
    reranker_model: str = Field(min_length=1, max_length=200)


class RetrievalEvaluationMetricsV1(StrictBaseModel):
    recall_at_5: FiniteRatio
    recall_at_10: FiniteRatio
    recall_at_20: FiniteRatio
    ndcg_at_10: FiniteRatio
    mrr: FiniteRatio
    filter_leak_rate: FiniteRatio
    citation_support: FiniteRatio
    empty_answer_rate: FiniteRatio
    latency_ms_p95: FiniteNonNegative


class RetrievalEvaluationHitV1(StrictBaseModel):
    resource_id: UUID
    resource_version_id: UUID
    content_sha256: Sha256Digest
    chunk_id: ChunkIdentifier
    locator: ChunkLocator


class RetrievalEvaluationQueryResultV1(StrictBaseModel):
    query_id: BoundedVersion
    latency_ms: FiniteNonNegative
    hits: list[RetrievalEvaluationHitV1]


class RetrievalEvaluationEvidencePayloadV1(StrictBaseModel):
    protocol_version: Literal["1"]
    producer_repository: RepositoryName
    producer_commit: GitCommit
    generated_at: datetime
    index_sha256: Sha256Digest
    manifest_sha256: Sha256Digest
    manifest_version: BoundedVersion
    resource_registry_sha256: Sha256Digest
    corpus_id: BoundedVersion
    corpus_version_id: BoundedVersion
    scope_id: BoundedVersion
    scope_sha256: Sha256Digest
    golden_suite_sha256: Sha256Digest
    retrieval_configuration: RetrievalEvaluationConfigurationV1
    metrics: RetrievalEvaluationMetricsV1
    query_results: list[RetrievalEvaluationQueryResultV1] = Field(min_length=1)
    automated_gate_pass: bool
    human_review_status: Literal["PENDING_HUMAN_REVIEW"]
    promotion_status: Literal["BLOCKED_PENDING_HUMAN_REVIEW"]

    _validate_generated_at = field_validator("generated_at")(require_aware_datetime)

    @field_validator("query_results")
    @classmethod
    def validate_unique_query_results(
        cls,
        values: list[RetrievalEvaluationQueryResultV1],
    ) -> list[RetrievalEvaluationQueryResultV1]:
        ids = [value.query_id for value in values]
        if len(ids) != len(set(ids)):
            raise ValueError("query result ids must be unique")
        return values


class RetrievalEvaluationEvidenceV1(RetrievalEvaluationEvidencePayloadV1):
    evidence_sha256: Sha256Digest

    def compute_sha256(self) -> str:
        return canonical_model_sha256(self, exclude={"evidence_sha256"})

    @model_validator(mode="after")
    def validate_evidence_sha256(self) -> "RetrievalEvaluationEvidenceV1":
        if self.evidence_sha256 != self.compute_sha256():
            raise ValueError("evidence_sha256 does not match canonical payload")
        return self


def seal_retrieval_evaluation_evidence(
    payload: RetrievalEvaluationEvidencePayloadV1,
) -> RetrievalEvaluationEvidenceV1:
    return RetrievalEvaluationEvidenceV1(
        **payload.model_dump(mode="python"),
        evidence_sha256=canonical_model_sha256(payload),
    )


__all__ = [
    "RetrievalEvaluationEvidencePayloadV1",
    "RetrievalEvaluationEvidenceV1",
    "RetrievalEvaluationHitV1",
    "RetrievalEvaluationMetricsV1",
    "RetrievalEvaluationQueryResultV1",
    "RetrievalGoldenQueryV1",
    "RetrievalGoldenSuitePayloadV1",
    "RetrievalGoldenSuiteV1",
    "seal_retrieval_evaluation_evidence",
    "seal_retrieval_golden_suite",
]
