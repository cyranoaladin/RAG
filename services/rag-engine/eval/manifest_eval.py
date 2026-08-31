"""Manifest-bound retrieval evaluation with immutable evidence identities."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from datetime import datetime

from metrics import empty_answer_rate, mrr, ndcg_at_k, percentile, recall_at_k
from nexus_contracts import (
    RetrievalEvaluationEvidencePayloadV1,
    RetrievalEvaluationEvidenceV1,
    RetrievalGoldenQueryV1,
    RetrievalGoldenSuiteV1,
    RetrievalResponse,
    ServableCorpus,
    ServableCorpusManifest,
    seal_retrieval_evaluation_evidence,
)

MIN_RECALL_AT_20_PER_QUERY = 0.8


class ManifestEvaluationError(ValueError):
    """The suite, corpus or returned immutable evidence is inconsistent."""


RetrievalPort = Callable[[RetrievalGoldenQueryV1, ServableCorpus], RetrievalResponse]


def _resolve_suite_corpus(
    suite: RetrievalGoldenSuiteV1,
    manifest: ServableCorpusManifest,
) -> ServableCorpus:
    if suite.manifest_sha256 != manifest.manifest_sha256:
        raise ManifestEvaluationError("golden suite manifest differs")
    matches = [
        corpus
        for corpus in manifest.corpora
        if corpus.corpus_id == suite.corpus_id
        and corpus.corpus_version_id == suite.corpus_version_id
    ]
    if len(matches) != 1:
        raise ManifestEvaluationError("golden suite corpus is unavailable")
    corpus = matches[0]
    known_chunks = {
        chunk.chunk_id
        for resource in corpus.resources
        for chunk in resource.chunks
    }
    if any(
        not set(query.relevant_chunk_ids).issubset(known_chunks)
        for query in suite.queries
    ):
        raise ManifestEvaluationError("golden judgment is absent from corpus")
    return corpus


def _canonical_chunk_bindings(corpus: ServableCorpus) -> dict[str, tuple[object, ...]]:
    bindings: dict[str, tuple[object, ...]] = {}
    for resource in corpus.resources:
        for chunk in resource.chunks:
            if chunk.chunk_id in bindings:
                raise ManifestEvaluationError("manifest chunk identity is ambiguous")
            bindings[chunk.chunk_id] = (
                resource.resource_id,
                resource.resource_version_id,
                resource.content_sha256,
                chunk.locator,
            )
    return bindings


def evaluate_manifest_bound_suite(
    *,
    suite: RetrievalGoldenSuiteV1,
    manifest: ServableCorpusManifest,
    index_sha256: str,
    producer_commit: str,
    generated_at: datetime,
    retrieve: RetrievalPort,
    embedding_model: str,
    reranker_model: str,
    top_k: int,
    monotonic: Callable[[], float] = time.perf_counter,
) -> RetrievalEvaluationEvidenceV1:
    """Evaluate one exact corpus; automated success never promotes content."""

    if top_k < 20 or top_k > 50:
        raise ManifestEvaluationError("top_k must be between 20 and 50")
    corpus = _resolve_suite_corpus(suite, manifest)
    bindings = _canonical_chunk_bindings(corpus)
    recall_5: list[float] = []
    recall_10: list[float] = []
    recall_20: list[float] = []
    ndcg_10: list[float] = []
    reciprocal_ranks: list[float] = []
    latencies: list[float] = []
    result_counts: list[int] = []
    leaked = 0
    total_hits = 0
    supported_citations = 0
    query_results: list[dict[str, object]] = []

    for query in suite.queries:
        started = monotonic()
        response = retrieve(query, corpus)
        latency_ms = max(0.0, (monotonic() - started) * 1_000)
        hits: list[dict[str, object]] = []
        result_ids: list[str] = []
        for result in response.results[:top_k]:
            expected = bindings.get(result.chunk_id)
            actual = (
                result.resource_id,
                result.resource_version_id,
                result.content_sha256,
                result.locator,
            )
            if (
                expected is None
                or actual != expected
                or result.corpus_id != corpus.corpus_id
                or result.corpus_version_id != corpus.corpus_version_id
                or result.manifest_sha256 != manifest.manifest_sha256
            ):
                raise ManifestEvaluationError("retrieval result identity differs from manifest")
            result_ids.append(result.chunk_id)
            total_hits += 1
            leaked += int(result.chunk_id in query.must_not_return)
            supported_citations += int(result.citation is not None)
            hits.append(
                {
                    "resource_id": result.resource_id,
                    "resource_version_id": result.resource_version_id,
                    "content_sha256": result.content_sha256,
                    "chunk_id": result.chunk_id,
                    "locator": result.locator,
                }
            )
        result_counts.append(len(result_ids))
        latencies.append(latency_ms)
        recall_5.append(recall_at_k(result_ids, query.relevant_chunk_ids, 5))
        recall_10.append(recall_at_k(result_ids, query.relevant_chunk_ids, 10))
        recall_20.append(recall_at_k(result_ids, query.relevant_chunk_ids, 20))
        ndcg_10.append(ndcg_at_k(result_ids, query.graded_relevance, 10))
        reciprocal_ranks.append(mrr(result_ids, query.relevant_chunk_ids))
        query_results.append(
            {"query_id": query.id, "latency_ms": latency_ms, "hits": hits}
        )

    metrics = {
        "recall_at_5": statistics.fmean(recall_5),
        "recall_at_10": statistics.fmean(recall_10),
        "recall_at_20": statistics.fmean(recall_20),
        "ndcg_at_10": statistics.fmean(ndcg_10),
        "mrr": statistics.fmean(reciprocal_ranks),
        "filter_leak_rate": leaked / total_hits if total_hits else 0.0,
        "citation_support": supported_citations / total_hits if total_hits else 1.0,
        "empty_answer_rate": empty_answer_rate(result_counts),
        "latency_ms_p95": percentile(latencies, 0.95),
    }
    automated_gate_pass = bool(
        all(value >= MIN_RECALL_AT_20_PER_QUERY for value in recall_20)
        and metrics["filter_leak_rate"] == 0
        and metrics["citation_support"] == 1
        and metrics["empty_answer_rate"] == 0
    )
    payload = RetrievalEvaluationEvidencePayloadV1.model_validate(
        {
            "protocol_version": "1",
            "producer_repository": "cyranoaladin/RAG",
            "producer_commit": producer_commit,
            "generated_at": generated_at,
            "index_sha256": index_sha256,
            "manifest_sha256": manifest.manifest_sha256,
            "manifest_version": manifest.manifest_version,
            "resource_registry_sha256": manifest.resource_registry_sha256,
            "corpus_id": corpus.corpus_id,
            "corpus_version_id": corpus.corpus_version_id,
            "scope_id": corpus.scope_id,
            "scope_sha256": corpus.scope_sha256,
            "golden_suite_sha256": suite.suite_sha256,
            "retrieval_configuration": {
                "top_k": top_k,
                "hybrid": True,
                "rerank": True,
                "embedding_model": embedding_model,
                "reranker_model": reranker_model,
            },
            "metrics": metrics,
            "query_results": query_results,
            "automated_gate_pass": automated_gate_pass,
            "human_review_status": "PENDING_HUMAN_REVIEW",
            "promotion_status": "BLOCKED_PENDING_HUMAN_REVIEW",
        }
    )
    return seal_retrieval_evaluation_evidence(payload)


__all__ = ["ManifestEvaluationError", "RetrievalPort", "evaluate_manifest_bound_suite"]
