"""Deterministic hybrid retrieval primitives for the v2 pgvector path."""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from fractions import Fraction
from numbers import Real
from typing import Literal, Protocol

from nexus_contracts.embedding_utils import format_query

CHANNEL_LIMIT = 50
RRF_DENSE_WEIGHT = Fraction(7, 10)
RRF_LEXICAL_WEIGHT = Fraction(3, 10)
RRF_K = 60
RERANK_THRESHOLD = 1.90
MMR_LAMBDA = 0.7
EMBED_MODEL = "intfloat/multilingual-e5-large"
RERANK_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
EMBED_DIMENSION = 1024


class RetrievalPipelineError(ValueError):
    """Controlled, sanitizable failure in the hybrid retrieval pipeline."""


def _require_nonblank(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise RetrievalPipelineError(f"invalid {field_name}")


def _require_finite(value: object, field_name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, Real) or not math.isfinite(value):
        raise RetrievalPipelineError(f"invalid {field_name}")


def _require_rank(value: object, field_name: str) -> None:
    if value is None:
        return
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RetrievalPipelineError(f"invalid {field_name}")


def _require_vector(vector: object) -> None:
    if not isinstance(vector, tuple) or len(vector) != EMBED_DIMENSION:
        raise RetrievalPipelineError("invalid vector")
    for component in vector:
        _require_finite(component, "vector")
    norm = math.hypot(*vector)
    if not math.isfinite(norm) or norm == 0.0:
        raise RetrievalPipelineError("invalid vector")


@dataclass(frozen=True)
class RetrievalCandidate:
    chunk_id: str
    doc_id: str
    source_label: str
    source_uri: str
    rights: str
    type_doc: str
    text: str
    page_start: int | None
    vector: tuple[float, ...]
    review_status: Literal["reviewed"]
    dense_score: float | None = None
    lexical_score: float | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "chunk_id",
            "doc_id",
            "source_label",
            "source_uri",
            "rights",
            "text",
        ):
            _require_nonblank(getattr(self, field_name), field_name)
        if not isinstance(self.type_doc, str):
            raise RetrievalPipelineError("invalid type_doc")
        if self.review_status != "reviewed":
            raise RetrievalPipelineError("invalid review_status")
        if self.page_start is not None:
            if (
                isinstance(self.page_start, bool)
                or not isinstance(self.page_start, int)
                or self.page_start < 1
            ):
                raise RetrievalPipelineError("invalid page_start")
        _require_vector(self.vector)
        if self.dense_score is not None:
            _require_finite(self.dense_score, "dense_score")
        if self.lexical_score is not None:
            _require_finite(self.lexical_score, "lexical_score")


@dataclass(frozen=True)
class RankedCandidate:
    candidate: RetrievalCandidate
    dense_rank: int | None
    lexical_rank: int | None
    rrf_score: Fraction
    rerank_score: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, RetrievalCandidate):
            raise RetrievalPipelineError("invalid candidate")
        _require_rank(self.dense_rank, "dense_rank")
        _require_rank(self.lexical_rank, "lexical_rank")
        if not isinstance(self.rrf_score, Fraction) or self.rrf_score < 0:
            raise RetrievalPipelineError("invalid rrf_score")
        if self.rerank_score is not None:
            _require_finite(self.rerank_score, "rerank_score")


@dataclass(frozen=True)
class HybridHit:
    candidate: RetrievalCandidate
    dense_rank: int | None
    lexical_rank: int | None
    rrf_score: float
    rerank_score: float
    mmr_score: float
    score_final: float

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, RetrievalCandidate):
            raise RetrievalPipelineError("invalid candidate")
        _require_rank(self.dense_rank, "dense_rank")
        _require_rank(self.lexical_rank, "lexical_rank")
        for field_name in ("rrf_score", "rerank_score", "mmr_score", "score_final"):
            _require_finite(getattr(self, field_name), field_name)
        if self.rrf_score < 0:
            raise RetrievalPipelineError("invalid rrf_score")
        if not 0.0 <= self.score_final <= 1.0:
            raise RetrievalPipelineError("invalid score_final")


class CandidateStore(Protocol):
    def dense(
        self, *, query_vector: Sequence[float], collection: str, limit: int
    ) -> Sequence[RetrievalCandidate]:
        raise NotImplementedError

    def lexical(
        self, *, raw_query: str, collection: str, limit: int
    ) -> Sequence[RetrievalCandidate]:
        raise NotImplementedError


class Embedder(Protocol):
    def encode(self, text: str, *, normalize_embeddings: bool) -> Iterable[float]:
        raise NotImplementedError


class Reranker(Protocol):
    def predict(self, pairs: Sequence[tuple[str, str]]) -> Iterable[float]:
        raise NotImplementedError


class RetrieveFunction(Protocol):
    def __call__(
        self,
        query: str,
        collection: str,
        top_k: int,
        *,
        store: CandidateStore,
        embedder: Embedder,
        reranker: Reranker,
    ) -> list[HybridHit]:
        raise NotImplementedError


def _channel_ranks(
    candidates: Sequence[RetrievalCandidate], channel_name: str
) -> tuple[dict[str, int], dict[str, RetrievalCandidate]]:
    if len(candidates) > CHANNEL_LIMIT:
        raise RetrievalPipelineError(f"channel limit exceeded ({channel_name})")
    ranks: dict[str, int] = {}
    by_id: dict[str, RetrievalCandidate] = {}
    for rank, item in enumerate(candidates, start=1):
        if not isinstance(item, RetrievalCandidate):
            raise RetrievalPipelineError(f"invalid channel candidate ({channel_name})")
        local_score = getattr(item, f"{channel_name}_score")
        try:
            _require_finite(local_score, f"{channel_name} channel score")
        except RetrievalPipelineError as exc:
            raise RetrievalPipelineError(f"invalid {channel_name} channel score") from exc
        if item.chunk_id in ranks:
            raise RetrievalPipelineError(f"duplicate channel candidate ({channel_name})")
        ranks[item.chunk_id] = rank
        by_id[item.chunk_id] = item
    return ranks, by_id


def _substantive_fields(item: RetrievalCandidate) -> tuple[object, ...]:
    return (
        item.doc_id,
        item.source_label,
        item.source_uri,
        item.rights,
        item.type_doc,
        item.text,
        item.page_start,
        item.vector,
        item.review_status,
    )


def reciprocal_rank_fusion(
    dense: Sequence[RetrievalCandidate], lexical: Sequence[RetrievalCandidate]
) -> list[RankedCandidate]:
    """Merge deterministic channel ranks using exact rational arithmetic."""
    dense_ranks, dense_by_id = _channel_ranks(dense, "dense")
    lexical_ranks, lexical_by_id = _channel_ranks(lexical, "lexical")
    ranked: list[RankedCandidate] = []

    for chunk_id in dense_by_id.keys() | lexical_by_id.keys():
        dense_item = dense_by_id.get(chunk_id)
        lexical_item = lexical_by_id.get(chunk_id)
        if (
            dense_item is not None
            and lexical_item is not None
            and _substantive_fields(dense_item) != _substantive_fields(lexical_item)
        ):
            raise RetrievalPipelineError("channel candidate mismatch")

        base = dense_item if dense_item is not None else lexical_item
        if base is None:  # pragma: no cover - impossible for a key from the union
            raise RetrievalPipelineError("invalid channel candidate")
        merged = replace(
            base,
            dense_score=dense_item.dense_score if dense_item is not None else None,
            lexical_score=lexical_item.lexical_score if lexical_item is not None else None,
        )
        dense_rank = dense_ranks.get(chunk_id)
        lexical_rank = lexical_ranks.get(chunk_id)
        score = Fraction(0)
        if dense_rank is not None:
            score += RRF_DENSE_WEIGHT / (RRF_K + dense_rank)
        if lexical_rank is not None:
            score += RRF_LEXICAL_WEIGHT / (RRF_K + lexical_rank)
        ranked.append(
            RankedCandidate(
                candidate=merged,
                dense_rank=dense_rank,
                lexical_rank=lexical_rank,
                rrf_score=score,
            )
        )

    return sorted(ranked, key=lambda item: (-item.rrf_score, item.candidate.chunk_id))


def rerank_candidates(
    candidates: Sequence[RankedCandidate], logits: Sequence[float]
) -> list[RankedCandidate]:
    """Attach finite reranker logits, apply the inclusive threshold and sort."""
    if len(logits) != len(candidates):
        raise RetrievalPipelineError("reranker cardinality mismatch")
    reranked: list[RankedCandidate] = []
    for item, logit in zip(candidates, logits, strict=True):
        try:
            _require_finite(logit, "reranker score")
        except RetrievalPipelineError as exc:
            raise RetrievalPipelineError("invalid reranker score") from exc
        if logit >= RERANK_THRESHOLD:
            reranked.append(replace(item, rerank_score=float(logit)))
    return sorted(
        reranked,
        key=lambda item: (
            -float(item.rerank_score) if item.rerank_score is not None else math.inf,
            -item.rrf_score,
            item.candidate.chunk_id,
        ),
    )


def _stable_sigmoid(value: float) -> float:
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    exponential = math.exp(value)
    return exponential / (1.0 + exponential)


def _vector_norm(vector: tuple[float, ...]) -> float:
    norm = math.hypot(*vector)
    if norm == 0.0 or not math.isfinite(norm):
        raise RetrievalPipelineError("invalid MMR vector")
    return norm


def _cosine(
    left: tuple[float, ...],
    right: tuple[float, ...],
    left_norm: float,
    right_norm: float,
) -> float:
    try:
        similarity = math.fsum(
            (left_value / left_norm) * (right_value / right_norm)
            for left_value, right_value in zip(left, right, strict=True)
        )
    except (OverflowError, ValueError) as exc:
        raise RetrievalPipelineError("invalid MMR similarity") from exc
    if not math.isfinite(similarity):
        raise RetrievalPipelineError("invalid MMR similarity")
    return min(1.0, max(-1.0, similarity))


def select_mmr(candidates: Sequence[RankedCandidate], top_k: int) -> list[HybridHit]:
    """Select unique documents with deterministic MMR over stored vectors."""
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= CHANNEL_LIMIT:
        raise RetrievalPipelineError("invalid top_k")
    remaining = list(candidates)
    if len({item.candidate.chunk_id for item in remaining}) != len(remaining):
        raise RetrievalPipelineError("duplicate MMR candidate")
    for item in remaining:
        if item.rerank_score is None or item.rerank_score < RERANK_THRESHOLD:
            raise RetrievalPipelineError("invalid MMR candidate")

    norms = {
        item.candidate.chunk_id: _vector_norm(item.candidate.vector) for item in remaining
    }
    max_cosines: dict[str, float] = {}
    hits: list[HybridHit] = []
    while remaining and len(hits) < top_k:
        scored: list[
            tuple[tuple[float, float, float, str], RankedCandidate, float, float]
        ] = []
        for item in remaining:
            logit = item.rerank_score
            if logit is None:  # pragma: no cover - guarded above
                raise RetrievalPipelineError("invalid MMR candidate")
            relevance = _stable_sigmoid(logit)
            max_cosine = max_cosines.get(item.candidate.chunk_id, 0.0)
            raw_score = MMR_LAMBDA * relevance - 0.3 * max_cosine
            score_final = (raw_score + 0.3) / 1.3
            if not math.isfinite(raw_score) or not math.isfinite(score_final):
                raise RetrievalPipelineError("invalid MMR score")
            key = (-raw_score, -logit, -float(item.rrf_score), item.candidate.chunk_id)
            scored.append((key, item, raw_score, score_final))

        _, winner, raw_score, score_final = min(scored, key=lambda scored_item: scored_item[0])
        logit = winner.rerank_score
        if logit is None:  # pragma: no cover - guarded above
            raise RetrievalPipelineError("invalid MMR candidate")
        hits.append(
            HybridHit(
                candidate=winner.candidate,
                dense_rank=winner.dense_rank,
                lexical_rank=winner.lexical_rank,
                rrf_score=float(winner.rrf_score),
                rerank_score=logit,
                mmr_score=raw_score,
                score_final=score_final,
            )
        )
        remaining = [
            item for item in remaining if item.candidate.doc_id != winner.candidate.doc_id
        ]
        if len(hits) >= top_k or not remaining:
            break
        winner_norm = norms[winner.candidate.chunk_id]
        for item in remaining:
            chunk_id = item.candidate.chunk_id
            similarity = _cosine(
                item.candidate.vector,
                winner.candidate.vector,
                norms[chunk_id],
                winner_norm,
            )
            if chunk_id in max_cosines:
                max_cosines[chunk_id] = max(max_cosines[chunk_id], similarity)
            else:
                max_cosines[chunk_id] = similarity

    return hits


def retrieve_hybrid(
    query: str,
    collection: str,
    top_k: int,
    *,
    store: CandidateStore,
    embedder: Embedder,
    reranker: Reranker,
) -> list[HybridHit]:
    """Run the canonical fail-closed hybrid retrieval sequence."""
    _require_nonblank(query, "query")
    _require_nonblank(collection, "collection")
    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= CHANNEL_LIMIT:
        raise RetrievalPipelineError("invalid top_k")

    try:
        formatted_query = format_query(query)
        if formatted_query != f"query: {query}":
            raise RetrievalPipelineError("invalid query prefix")
        encoded = embedder.encode(formatted_query, normalize_embeddings=True)
        query_vector = tuple(float(component) for component in encoded)
        _require_vector(query_vector)

        dense = list(
            store.dense(
                query_vector=query_vector,
                collection=collection,
                limit=CHANNEL_LIMIT,
            )
        )
        lexical = list(
            store.lexical(
                raw_query=query,
                collection=collection,
                limit=CHANNEL_LIMIT,
            )
        )
        fused = reciprocal_rank_fusion(dense, lexical)
        if not fused:
            return []

        pairs = [(query, item.candidate.text) for item in fused]
        logits = [float(score) for score in reranker.predict(pairs)]
        reranked = rerank_candidates(fused, logits)
        return select_mmr(reranked, top_k)
    except Exception as exc:
        raise RetrievalPipelineError("hybrid retrieval failed") from exc
