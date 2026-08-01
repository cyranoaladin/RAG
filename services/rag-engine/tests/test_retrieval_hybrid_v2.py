from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import FrozenInstanceError, fields
from fractions import Fraction

import pytest
from nexus_contracts.embedding_utils import format_query as canonical_format_query

import ingestor.retrieval_hybrid_v2 as hybrid
from ingestor.retrieval_hybrid_v2 import (
    CHANNEL_LIMIT,
    EMBED_DIMENSION,
    EMBED_MODEL,
    MMR_LAMBDA,
    RERANK_MODEL,
    RERANK_THRESHOLD,
    RRF_DENSE_WEIGHT,
    RRF_K,
    RRF_LEXICAL_WEIGHT,
    CandidateStore,
    Embedder,
    HybridHit,
    RankedCandidate,
    Reranker,
    RetrievalCandidate,
    RetrievalPipelineError,
    RetrieveFunction,
    reciprocal_rank_fusion,
    rerank_candidates,
    retrieve_hybrid,
    select_mmr,
)

VECTOR = (1.0,) + (0.0,) * (EMBED_DIMENSION - 1)
ORTHOGONAL_VECTOR = (0.0, 1.0) + (0.0,) * (EMBED_DIMENSION - 2)


def candidate(**overrides: object) -> RetrievalCandidate:
    values: dict[str, object] = {
        "chunk_id": "chunk-A",
        "doc_id": "doc-A",
        "source_label": "Référentiel officiel",
        "source_uri": "https://example.test/source",
        "rights": "CC-BY-4.0",
        "type_doc": "cours",
        "text": "Un passage pédagogique substantiel.",
        "page_start": 3,
        "vector": VECTOR,
        "review_status": "reviewed",
        "dense_score": 0.8,
        "lexical_score": None,
    }
    values.update(overrides)
    return RetrievalCandidate(**values)  # type: ignore[arg-type]


def named_candidate(chunk_id: str, **overrides: object) -> RetrievalCandidate:
    values: dict[str, object] = {
        "chunk_id": chunk_id,
        "doc_id": f"doc-{chunk_id}",
        "text": f"Passage {chunk_id}",
    }
    values.update(overrides)
    return candidate(**values)


def ranked_candidate(
    chunk_id: str,
    *,
    vector: tuple[float, ...] = VECTOR,
    doc_id: str | None = None,
    rrf_score: Fraction = Fraction(1, 50),
    rerank_score: float | None = None,
) -> RankedCandidate:
    return RankedCandidate(
        candidate=named_candidate(
            chunk_id,
            doc_id=doc_id if doc_id is not None else f"doc-{chunk_id}",
            vector=vector,
        ),
        dense_rank=1,
        lexical_rank=1,
        rrf_score=rrf_score,
        rerank_score=rerank_score,
    )


class RecordingStore:
    def __init__(
        self,
        *,
        dense: Sequence[RetrievalCandidate] = (),
        lexical: Sequence[RetrievalCandidate] = (),
        error_stage: str | None = None,
        events: list[str] | None = None,
    ) -> None:
        self.dense_result = dense
        self.lexical_result = lexical
        self.error_stage = error_stage
        self.events = events if events is not None else []
        self.dense_calls: list[tuple[Sequence[float], str, int]] = []
        self.lexical_calls: list[tuple[str, str, int]] = []

    def dense(
        self, *, query_vector: Sequence[float], collection: str, limit: int
    ) -> Sequence[RetrievalCandidate]:
        self.events.append("dense")
        self.dense_calls.append((query_vector, collection, limit))
        if self.error_stage == "dense":
            raise RuntimeError("SECRET_DSN dense source text")
        return self.dense_result

    def lexical(
        self, *, raw_query: str, collection: str, limit: int
    ) -> Sequence[RetrievalCandidate]:
        self.events.append("lexical")
        self.lexical_calls.append((raw_query, collection, limit))
        if self.error_stage == "lexical":
            raise RuntimeError("SECRET_DSN lexical source text")
        return self.lexical_result


class RecordingEmbedder:
    def __init__(
        self,
        vector: Sequence[float] = VECTOR,
        *,
        fail: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self.vector = vector
        self.fail = fail
        self.events = events if events is not None else []
        self.calls: list[tuple[str, bool]] = []

    def encode(self, text: str, *, normalize_embeddings: bool) -> Sequence[float]:
        self.events.append("embed")
        self.calls.append((text, normalize_embeddings))
        if self.fail:
            raise RuntimeError("SECRET_DSN embed source text")
        return self.vector


class RecordingReranker:
    def __init__(
        self,
        scores: Sequence[float] = (),
        *,
        fail: bool = False,
        events: list[str] | None = None,
    ) -> None:
        self.scores = scores
        self.fail = fail
        self.events = events if events is not None else []
        self.calls: list[Sequence[tuple[str, str]]] = []

    def predict(self, pairs: Sequence[tuple[str, str]]) -> Sequence[float]:
        self.events.append("rerank")
        self.calls.append(pairs)
        if self.fail:
            raise RuntimeError("SECRET_DSN rerank source text")
        return self.scores


def test_hybrid_types_have_the_exact_frozen_field_contract() -> None:
    assert [field.name for field in fields(RetrievalCandidate)] == [
        "chunk_id",
        "doc_id",
        "source_label",
        "source_uri",
        "rights",
        "type_doc",
        "text",
        "page_start",
        "vector",
        "review_status",
        "dense_score",
        "lexical_score",
    ]
    assert [field.name for field in fields(RankedCandidate)] == [
        "candidate",
        "dense_rank",
        "lexical_rank",
        "rrf_score",
        "rerank_score",
    ]
    assert [field.name for field in fields(HybridHit)] == [
        "candidate",
        "dense_rank",
        "lexical_rank",
        "rrf_score",
        "rerank_score",
        "mmr_score",
        "score_final",
    ]

    item = candidate()
    with pytest.raises(FrozenInstanceError):
        item.text = "mutation interdite"  # type: ignore[misc]


def test_hybrid_constants_are_fixed_by_the_lot40_design() -> None:
    assert CHANNEL_LIMIT == 50
    assert RRF_DENSE_WEIGHT == Fraction(7, 10)
    assert RRF_LEXICAL_WEIGHT == Fraction(3, 10)
    assert RRF_K == 60
    assert RERANK_THRESHOLD == 1.90
    assert MMR_LAMBDA == 0.7
    assert EMBED_MODEL == "intfloat/multilingual-e5-large"
    assert RERANK_MODEL == "cross-encoder/ms-marco-MiniLM-L-6-v2"
    assert EMBED_DIMENSION == 1024
    assert issubclass(RetrievalPipelineError, ValueError)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("chunk_id", "  "),
        ("doc_id", ""),
        ("source_label", "\t"),
        ("source_uri", "\n"),
        ("rights", " "),
        ("text", ""),
        ("review_status", "pending"),
        ("page_start", 0),
        ("page_start", -1),
        ("vector", VECTOR[:-1]),
        ("vector", (math.nan,) + VECTOR[1:]),
        ("vector", (math.inf,) + VECTOR[1:]),
        ("vector", (0.0,) * EMBED_DIMENSION),
        ("dense_score", math.nan),
        ("dense_score", math.inf),
        ("lexical_score", -math.inf),
    ],
)
def test_candidate_rejects_invalid_substance(field: str, value: object) -> None:
    with pytest.raises(RetrievalPipelineError):
        candidate(**{field: value})


def test_candidate_accepts_blank_type_doc_and_unknown_page() -> None:
    item = candidate(type_doc="", page_start=None, dense_score=None, lexical_score=0.0)

    assert item.type_doc == ""
    assert item.page_start is None


@pytest.mark.parametrize("rank", [0, -1])
def test_ranked_candidate_rejects_non_positive_ranks(rank: int) -> None:
    with pytest.raises(RetrievalPipelineError):
        RankedCandidate(
            candidate=candidate(),
            dense_rank=rank,
            lexical_rank=None,
            rrf_score=Fraction(1, 61),
        )


def test_ranked_candidate_rejects_non_finite_rerank_score() -> None:
    with pytest.raises(RetrievalPipelineError):
        RankedCandidate(
            candidate=candidate(),
            dense_rank=1,
            lexical_rank=None,
            rrf_score=Fraction(1, 61),
            rerank_score=math.nan,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("dense_rank", 0),
        ("lexical_rank", -1),
        ("rrf_score", math.nan),
        ("rerank_score", math.inf),
        ("mmr_score", math.nan),
        ("score_final", -0.01),
        ("score_final", 1.01),
    ],
)
def test_hybrid_hit_rejects_invalid_scores_and_ranks(field: str, value: object) -> None:
    values: dict[str, object] = {
        "candidate": candidate(),
        "dense_rank": 1,
        "lexical_rank": 2,
        "rrf_score": 0.02,
        "rerank_score": 2.0,
        "mmr_score": 0.6,
        "score_final": 0.7,
    }
    values[field] = value
    with pytest.raises(RetrievalPipelineError):
        HybridHit(**values)  # type: ignore[arg-type]


def test_rrf_uses_exact_fractions_and_stable_reference_order() -> None:
    dense = [
        named_candidate("A", dense_score=0.91),
        named_candidate("B", dense_score=0.81),
        named_candidate("C", dense_score=0.71),
    ]
    lexical = [
        named_candidate("B", dense_score=None, lexical_score=0.61),
        named_candidate("D", dense_score=None, lexical_score=0.51),
        named_candidate("A", dense_score=None, lexical_score=0.41),
    ]

    fused = reciprocal_rank_fusion(dense, lexical)
    scores = {item.candidate.chunk_id: item.rrf_score for item in fused}

    assert scores["A"] == Fraction(7, 10) / 61 + Fraction(3, 10) / 63
    assert scores["B"] == Fraction(7, 10) / 62 + Fraction(3, 10) / 61
    assert scores["C"] == Fraction(7, 10) / 63
    assert scores["D"] == Fraction(3, 10) / 62
    assert [item.candidate.chunk_id for item in fused] == ["A", "B", "C", "D"]

    by_id = {item.candidate.chunk_id: item for item in fused}
    assert by_id["A"].dense_rank == 1
    assert by_id["A"].lexical_rank == 3
    assert by_id["A"].candidate.dense_score == 0.91
    assert by_id["A"].candidate.lexical_score == 0.41
    assert by_id["D"].dense_rank is None
    assert by_id["D"].lexical_rank == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("doc_id", "doc-other"),
        ("source_label", "Autre source"),
        ("source_uri", "https://example.test/other"),
        ("rights", "Etalab-2.0"),
        ("type_doc", "exercice"),
        ("text", "Autre texte"),
        ("page_start", 4),
        ("vector", (0.0, 1.0) + (0.0,) * (EMBED_DIMENSION - 2)),
        ("review_status", "pending"),
    ],
)
def test_rrf_rejects_substantive_cross_channel_divergence(
    field: str, value: object
) -> None:
    dense_item = named_candidate("A", dense_score=0.8)
    lexical_item = named_candidate("A", dense_score=None, lexical_score=0.7)
    if field == "review_status":
        object.__setattr__(lexical_item, field, value)
    else:
        lexical_item = named_candidate(
            "A", dense_score=None, lexical_score=0.7, **{field: value}
        )

    with pytest.raises(RetrievalPipelineError, match="channel candidate mismatch"):
        reciprocal_rank_fusion([dense_item], [lexical_item])


@pytest.mark.parametrize("channel", ["dense", "lexical"])
def test_rrf_rejects_duplicate_chunk_ids_inside_a_channel(channel: str) -> None:
    item = named_candidate("A")
    dense = [item, item] if channel == "dense" else []
    lexical = [item, item] if channel == "lexical" else []

    with pytest.raises(RetrievalPipelineError, match="duplicate channel candidate"):
        reciprocal_rank_fusion(dense, lexical)


def test_rrf_breaks_exact_score_ties_by_chunk_id() -> None:
    dense = [named_candidate(f"dense-{rank}") for rank in range(1, 21)]
    lexical = [named_candidate(f"lexical-{rank}") for rank in range(1, 21)]
    dense[3] = named_candidate("A")
    dense[9] = named_candidate("B")
    lexical[3] = named_candidate("B")
    lexical[19] = named_candidate("A")

    fused = reciprocal_rank_fusion(dense, lexical)
    by_id = {item.candidate.chunk_id: item for item in fused}

    assert by_id["A"].rrf_score == by_id["B"].rrf_score == Fraction(47, 3200)
    assert [item.candidate.chunk_id for item in fused].index("A") < [
        item.candidate.chunk_id for item in fused
    ].index("B")


def test_rerank_requires_exact_cardinality_and_finite_logits() -> None:
    ranked = [ranked_candidate("A"), ranked_candidate("B")]

    with pytest.raises(RetrievalPipelineError, match="reranker cardinality"):
        rerank_candidates(ranked, [2.0])
    with pytest.raises(RetrievalPipelineError, match="invalid reranker score"):
        rerank_candidates(ranked, [2.0, math.nan])
    with pytest.raises(RetrievalPipelineError, match="invalid reranker score"):
        rerank_candidates(ranked, [2.0, math.inf])


def test_rerank_threshold_is_inclusive_and_order_is_total() -> None:
    ranked = [
        ranked_candidate("C", rrf_score=Fraction(3, 100)),
        ranked_candidate("B", rrf_score=Fraction(2, 100)),
        ranked_candidate("A", rrf_score=Fraction(2, 100)),
        ranked_candidate("discarded", rrf_score=Fraction(1, 100)),
    ]

    result = rerank_candidates(ranked, [2.0, 2.0, 2.0, 1.899999])

    assert [item.candidate.chunk_id for item in result] == ["C", "A", "B"]
    assert all(item.rerank_score == 2.0 for item in result)
    assert rerank_candidates([ranked_candidate("threshold")], [1.90])[0].rerank_score == 1.90


def test_mmr_matches_the_reference_formula_and_order() -> None:
    ranked = [
        ranked_candidate("A", rerank_score=2.0),
        ranked_candidate("B", rerank_score=2.0),
        ranked_candidate("C", vector=ORTHOGONAL_VECTOR, rerank_score=1.9),
    ]

    hits = select_mmr(ranked, top_k=3)

    assert [hit.candidate.chunk_id for hit in hits] == ["A", "C", "B"]
    relevance_a = 1.0 / (1.0 + math.exp(-2.0))
    raw_a = MMR_LAMBDA * relevance_a
    assert hits[0].mmr_score == pytest.approx(raw_a)
    assert hits[0].score_final == pytest.approx((raw_a + 0.3) / 1.3)
    relevance_c = 1.0 / (1.0 + math.exp(-1.9))
    assert hits[1].mmr_score == pytest.approx(MMR_LAMBDA * relevance_c)
    assert hits[2].mmr_score == pytest.approx(MMR_LAMBDA * relevance_a - 0.3)
    assert all(0.0 <= hit.score_final <= 1.0 for hit in hits)


def test_mmr_removes_document_siblings_before_the_next_iteration() -> None:
    without_sibling = [
        ranked_candidate("A1", doc_id="doc-X", rrf_score=Fraction(4, 100), rerank_score=2.2),
        ranked_candidate("B", doc_id="doc-Y", rrf_score=Fraction(3, 100), rerank_score=2.0),
        ranked_candidate(
            "C",
            doc_id="doc-Z",
            vector=ORTHOGONAL_VECTOR,
            rrf_score=Fraction(2, 100),
            rerank_score=1.9,
        ),
    ]
    with_sibling = [
        without_sibling[0],
        ranked_candidate("A2", doc_id="doc-X", rrf_score=Fraction(35, 1000), rerank_score=2.1),
        *without_sibling[1:],
    ]

    baseline = select_mmr(without_sibling, top_k=3)
    hits = select_mmr(with_sibling, top_k=3)

    assert [hit.candidate.chunk_id for hit in hits] == [
        hit.candidate.chunk_id for hit in baseline
    ]
    assert [hit.mmr_score for hit in hits] == pytest.approx(
        [hit.mmr_score for hit in baseline]
    )
    assert len({hit.candidate.doc_id for hit in hits}) == 3
    assert "A2" not in {hit.candidate.chunk_id for hit in hits}


def test_mmr_breaks_complete_ties_by_chunk_id() -> None:
    hits = select_mmr(
        [
            ranked_candidate("B", rerank_score=2.0),
            ranked_candidate("A", rerank_score=2.0),
        ],
        top_k=1,
    )

    assert [hit.candidate.chunk_id for hit in hits] == ["A"]


def test_mmr_uses_a_numerically_stable_sigmoid() -> None:
    hits = select_mmr([ranked_candidate("A", rerank_score=1000.0)], top_k=1)

    assert hits[0].mmr_score == pytest.approx(MMR_LAMBDA)
    assert math.isfinite(hits[0].score_final)


def test_pipeline_protocols_expose_the_injected_boundaries() -> None:
    assert {"dense", "lexical"} <= set(CandidateStore.__dict__)
    assert "encode" in Embedder.__dict__
    assert "predict" in Reranker.__dict__
    assert "__call__" in RetrieveFunction.__dict__


def test_pipeline_uses_one_prefixed_embedding_and_raw_query_elsewhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []
    raw_query = "  Définir la photosynthèse ?  "
    format_calls: list[str] = []

    def record_format_query(text: str) -> str:
        events.append("format")
        format_calls.append(text)
        return canonical_format_query(text)

    monkeypatch.setattr(hybrid, "format_query", record_format_query)
    store = RecordingStore(
        dense=[named_candidate("A", dense_score=0.9), named_candidate("C", dense_score=0.8)],
        lexical=[
            named_candidate("B", vector=ORTHOGONAL_VECTOR, dense_score=None, lexical_score=0.7),
            named_candidate("A", dense_score=None, lexical_score=0.6),
        ],
        events=events,
    )
    embedder = RecordingEmbedder(events=events)
    reranker = RecordingReranker([2.2, 1.8, 1.9], events=events)

    hits = retrieve_hybrid(
        raw_query,
        "libre_terminale",
        2,
        store=store,
        embedder=embedder,
        reranker=reranker,
    )

    assert events == ["format", "embed", "dense", "lexical", "rerank"]
    assert format_calls == [raw_query]
    assert embedder.calls == [(f"query: {raw_query}", True)]
    assert store.dense_calls == [(VECTOR, "libre_terminale", CHANNEL_LIMIT)]
    assert store.lexical_calls == [(raw_query, "libre_terminale", CHANNEL_LIMIT)]
    assert reranker.calls == [
        [
            (raw_query, "Passage A"),
            (raw_query, "Passage C"),
            (raw_query, "Passage B"),
        ]
    ]
    assert [hit.candidate.chunk_id for hit in hits] == ["A", "B"]
    assert len(embedder.calls) == 1


@pytest.mark.parametrize(
    ("query", "collection", "top_k"),
    [
        ("", "libre_terminale", 1),
        ("   ", "libre_terminale", 1),
        ("question", "", 1),
        ("question", "\t", 1),
        ("question", "libre_terminale", 0),
        ("question", "libre_terminale", 51),
        ("question", "libre_terminale", True),
    ],
)
def test_pipeline_rejects_invalid_public_inputs_before_work(
    query: str, collection: str, top_k: int
) -> None:
    events: list[str] = []

    with pytest.raises(RetrievalPipelineError):
        retrieve_hybrid(
            query,
            collection,
            top_k,
            store=RecordingStore(events=events),
            embedder=RecordingEmbedder(events=events),
            reranker=RecordingReranker(events=events),
        )

    assert events == []


@pytest.mark.parametrize(
    "vector",
    [
        VECTOR[:-1],
        (math.nan,) + VECTOR[1:],
        (math.inf,) + VECTOR[1:],
        (0.0,) * EMBED_DIMENSION,
    ],
)
def test_pipeline_rejects_an_invalid_query_embedding(vector: Sequence[float]) -> None:
    store = RecordingStore()

    with pytest.raises(RetrievalPipelineError, match="hybrid retrieval failed"):
        retrieve_hybrid(
            "question",
            "libre_terminale",
            1,
            store=store,
            embedder=RecordingEmbedder(vector),
            reranker=RecordingReranker(),
        )

    assert store.dense_calls == []
    assert store.lexical_calls == []


def test_pipeline_returns_empty_without_calling_the_reranker() -> None:
    reranker = RecordingReranker(fail=True)

    hits = retrieve_hybrid(
        "question",
        "libre_terminale",
        3,
        store=RecordingStore(),
        embedder=RecordingEmbedder(),
        reranker=reranker,
    )

    assert hits == []
    assert reranker.calls == []


@pytest.mark.parametrize("empty_channel", ["dense", "lexical"])
def test_pipeline_accepts_one_successful_empty_channel(empty_channel: str) -> None:
    item = named_candidate("A", dense_score=0.8, lexical_score=None)
    store = RecordingStore(
        dense=[] if empty_channel == "dense" else [item],
        lexical=[item] if empty_channel == "dense" else [],
    )

    hits = retrieve_hybrid(
        "question",
        "libre_terminale",
        1,
        store=store,
        embedder=RecordingEmbedder(),
        reranker=RecordingReranker([1.90]),
    )

    assert [hit.candidate.chunk_id for hit in hits] == ["A"]


@pytest.mark.parametrize("stage", ["embed", "dense", "lexical", "rerank"])
def test_pipeline_closes_every_external_failure_without_leaking_details(stage: str) -> None:
    item = named_candidate("A")
    store = RecordingStore(dense=[item], lexical=[], error_stage=stage)
    embedder = RecordingEmbedder(fail=stage == "embed")
    reranker = RecordingReranker([2.0], fail=stage == "rerank")

    with pytest.raises(RetrievalPipelineError) as caught:
        retrieve_hybrid(
            "question très secrète",
            "libre_terminale",
            1,
            store=store,
            embedder=embedder,
            reranker=reranker,
        )

    assert str(caught.value) == "hybrid retrieval failed"
    assert "SECRET_DSN" not in str(caught.value)
    if stage in {"embed", "dense", "lexical"}:
        assert reranker.calls == []
    else:
        assert len(reranker.calls) == 1


def test_pipeline_sanitizes_reranker_cardinality_errors() -> None:
    item = named_candidate("A")

    with pytest.raises(RetrievalPipelineError) as caught:
        retrieve_hybrid(
            "question",
            "libre_terminale",
            1,
            store=RecordingStore(dense=[item]),
            embedder=RecordingEmbedder(),
            reranker=RecordingReranker([]),
        )

    assert str(caught.value) == "hybrid retrieval failed"


def test_pipeline_rejects_a_noncanonical_query_prefix_before_embedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(hybrid, "format_query", lambda _text: "passage: wrong")
    embedder = RecordingEmbedder()

    with pytest.raises(RetrievalPipelineError, match="hybrid retrieval failed"):
        retrieve_hybrid(
            "question",
            "libre_terminale",
            1,
            store=RecordingStore(),
            embedder=embedder,
            reranker=RecordingReranker(),
        )

    assert embedder.calls == []
