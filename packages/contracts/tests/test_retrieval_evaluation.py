from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from nexus_contracts import (
    RetrievalEvaluationEvidencePayloadV1,
    RetrievalGoldenSuitePayloadV1,
    seal_retrieval_evaluation_evidence,
    seal_retrieval_golden_suite,
)

SHA_A = "a" * 64
SHA_B = "b" * 64


def _suite_payload(**changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "protocol_version": "1",
        "suite_id": "aria-retrieval-corpus-qualification-v1",
        "manifest_sha256": SHA_A,
        "corpus_id": "aria-maths-terminale",
        "corpus_version_id": "2026-08-30.1",
        "human_review_status": "PENDING_HUMAN_REVIEW",
        "queries": [
            {
                "id": "Q001",
                "query": "Quelle est la définition d'une suite géométrique ?",
                "intent": "context",
                "relevant_chunk_ids": ["chunk-001"],
                "graded_relevance": {"chunk-001": 2.0},
                "must_not_return": ["chunk-cross-scope"],
            }
        ],
    }
    payload.update(changes)
    return payload


def _evidence_payload(suite_sha256: str, **changes: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "protocol_version": "1",
        "producer_repository": "cyranoaladin/RAG",
        "producer_commit": SHA_A[:40],
        "generated_at": datetime(2026, 8, 30, 12, tzinfo=UTC),
        "index_sha256": SHA_A,
        "manifest_sha256": SHA_A,
        "manifest_version": "aria-servable-corpus-v1",
        "resource_registry_sha256": SHA_B,
        "corpus_id": "aria-maths-terminale",
        "corpus_version_id": "2026-08-30.1",
        "scope_id": "scope-maths-terminale-v1",
        "scope_sha256": SHA_B,
        "golden_suite_sha256": suite_sha256,
        "retrieval_configuration": {
            "top_k": 20,
            "hybrid": True,
            "rerank": True,
            "embedding_model": "intfloat/multilingual-e5-large",
            "reranker_model": "cross-encoder/ms-marco-MiniLM-L-6-v2",
        },
        "metrics": {
            "recall_at_5": 1.0,
            "recall_at_10": 1.0,
            "recall_at_20": 1.0,
            "ndcg_at_10": 1.0,
            "mrr": 1.0,
            "filter_leak_rate": 0.0,
            "citation_support": 1.0,
            "empty_answer_rate": 0.0,
            "latency_ms_p95": 10.0,
        },
        "query_results": [
            {
                "query_id": "Q001",
                "latency_ms": 10.0,
                "hits": [
                    {
                        "resource_id": "11111111-1111-4111-8111-111111111111",
                        "resource_version_id": "22222222-2222-4222-8222-222222222222",
                        "content_sha256": SHA_A,
                        "chunk_id": "chunk-001",
                        "locator": {"page": 1},
                    }
                ],
            }
        ],
        "automated_gate_pass": True,
        "human_review_status": "PENDING_HUMAN_REVIEW",
        "promotion_status": "BLOCKED_PENDING_HUMAN_REVIEW",
    }
    payload.update(changes)
    return payload


def test_golden_suite_is_strict_digest_sealed_and_manifest_bound() -> None:
    suite = seal_retrieval_golden_suite(
        RetrievalGoldenSuitePayloadV1.model_validate(_suite_payload())
    )
    assert suite.suite_sha256 == suite.compute_sha256()
    assert suite.corpus_id == "aria-maths-terminale"

    with pytest.raises(ValidationError):
        RetrievalGoldenSuitePayloadV1.model_validate(
            _suite_payload(collection="legacy_collection")
        )


@pytest.mark.parametrize(
    "query_changes",
    [
        {"graded_relevance": {"chunk-001": -1.0}},
        {"graded_relevance": {"chunk-001": float("inf")}},
        {"graded_relevance": {"chunk-001": True}},
        {"graded_relevance": {"other": 1.0}},
        {"must_not_return": ["chunk-001"]},
    ],
)
def test_golden_query_refuses_invalid_or_incoherent_judgments(
    query_changes: dict[str, object],
) -> None:
    query = dict(_suite_payload()["queries"][0])  # type: ignore[index]
    query.update(query_changes)
    with pytest.raises(ValidationError):
        RetrievalGoldenSuitePayloadV1.model_validate(_suite_payload(queries=[query]))


def test_golden_suite_refuses_duplicate_ids_and_any_approval_claim() -> None:
    query = _suite_payload()["queries"][0]  # type: ignore[index]
    with pytest.raises(ValidationError, match="unique"):
        RetrievalGoldenSuitePayloadV1.model_validate(
            _suite_payload(queries=[query, query])
        )
    with pytest.raises(ValidationError):
        RetrievalGoldenSuitePayloadV1.model_validate(
            _suite_payload(human_review_status="APPROVED")
        )


def test_evidence_is_sealed_and_automated_pass_never_authorizes_promotion() -> None:
    suite = seal_retrieval_golden_suite(
        RetrievalGoldenSuitePayloadV1.model_validate(_suite_payload())
    )
    evidence = seal_retrieval_evaluation_evidence(
        RetrievalEvaluationEvidencePayloadV1.model_validate(
            _evidence_payload(suite.suite_sha256)
        )
    )
    assert evidence.evidence_sha256 == evidence.compute_sha256()
    assert evidence.automated_gate_pass is True
    assert evidence.promotion_status == "BLOCKED_PENDING_HUMAN_REVIEW"

    for changes in (
        {"promotion_status": "APPROVED"},
        {"human_review_status": "APPROVED"},
        {"unknown": True},
    ):
        with pytest.raises(ValidationError):
            RetrievalEvaluationEvidencePayloadV1.model_validate(
                _evidence_payload(suite.suite_sha256, **changes)
            )
