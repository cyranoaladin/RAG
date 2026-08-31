from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_contracts import (
    Citation,
    RetrievalGoldenSuitePayloadV1,
    RetrievalResponse,
    RetrievalResult,
    ServableCorpusManifestPayload,
    seal_retrieval_golden_suite,
    seal_servable_corpus_manifest,
)

EVAL_DIR = Path(__file__).resolve().parents[1] / "eval"
if str(EVAL_DIR) not in sys.path:
    sys.path.insert(0, str(EVAL_DIR))

from manifest_eval import (  # noqa: E402
    ManifestEvaluationError,
    evaluate_manifest_bound_suite,
)

NOW = datetime(2026, 8, 30, 12, tzinfo=UTC)
SHA_A = "a" * 64
SHA_B = "b" * 64
RESOURCE_ID = "11111111-1111-4111-8111-111111111111"
RESOURCE_VERSION_ID = "22222222-2222-4222-8222-222222222222"


def _manifest():
    return seal_servable_corpus_manifest(
        ServableCorpusManifestPayload.model_validate(
            {
                "protocol_version": "1",
                "manifest_version": "aria-servable-corpus-v1",
                "resource_registry_version": "aria-resource-registry-v1",
                "resource_registry_sha256": SHA_B,
                "producer_repository": "cyranoaladin/RAG",
                "producer_commit": SHA_A[:40],
                "generated_at": NOW,
                "corpora": [
                    {
                        "corpus_id": "aria-maths-terminale",
                        "corpus_version_id": "2026-08-30.1",
                        "academic_year": "2026-2027",
                        "curriculum_version": "fr-national-2026",
                        "physical_collection": "rag_nexus_maths_terminale_gen_specialite",
                        "retrieval_scope": {
                            "artifact_version": "3",
                            "scope_id": "aria_maths_terminale_v1",
                            "status": "eligible_for_promotion",
                            "source_sha256": SHA_A,
                            "target_policy": {
                                "tenant": "nexus", "niveau": "terminale",
                                "voie": "generale", "matiere": "mathematiques",
                                "statut_enseignement": "specialite",
                                "audiences": ["aefe", "libre"],
                                "candidates": ["scolarise", "aefe", "libre"],
                                "roles": ["student"],
                            },
                            "evidence_subject": {
                                "collection": "rag_nexus_maths_terminale_gen_specialite",
                                "tenant": "nexus", "niveau": "terminale",
                                "voie": "generale", "matiere": "mathematiques",
                                "statut_enseignement": "specialite",
                                "candidat": "scolarise", "audiences": ["aefe", "tous"],
                                "visibility": "public", "rights": ["officiel_public"],
                                "school_year": "2026-2027",
                                "programme_version": "fr-national-2026",
                            },
                        },
                        "resources": [
                            {
                                "resource_id": RESOURCE_ID,
                                "resource_version_id": RESOURCE_VERSION_ID,
                                "content_sha256": SHA_A,
                                "chunks": [
                                    {"chunk_id": "chunk-001", "locator": {"page": 1}},
                                    {"chunk_id": "chunk-002", "locator": {"page": 2}},
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    )


def _suite(**changes: object):
    manifest = _manifest()
    payload: dict[str, object] = {
        "protocol_version": "1",
        "suite_id": "aria-retrieval-corpus-qualification-v1",
        "manifest_sha256": manifest.manifest_sha256,
        "corpus_id": "aria-maths-terminale",
        "corpus_version_id": "2026-08-30.1",
        "human_review_status": "PENDING_HUMAN_REVIEW",
        "queries": [
            {
                "id": "Q001",
                "query": "Définir une suite géométrique",
                "intent": "context",
                "relevant_chunk_ids": ["chunk-001"],
                "graded_relevance": {"chunk-001": 2.0},
                "must_not_return": ["chunk-cross-scope"],
            }
        ],
    }
    payload.update(changes)
    return seal_retrieval_golden_suite(
        RetrievalGoldenSuitePayloadV1.model_validate(payload)
    )


def _response(**changes: object) -> RetrievalResponse:
    manifest = _manifest()
    values: dict[str, object] = {
        "chunk_id": "chunk-001",
        "doc_id": SHA_A,
        "score": 0.9,
        "excerpt": "Une suite géométrique...",
        "citation": Citation(
            source_label="Programme officiel",
            page=1,
            source_uri="https://eduscol.education.fr/programme.pdf",
            rights="officiel_public",
        ),
        "resource_id": RESOURCE_ID,
        "resource_version_id": RESOURCE_VERSION_ID,
        "content_sha256": SHA_A,
        "locator": {"page": 1},
        "corpus_id": "aria-maths-terminale",
        "corpus_version_id": "2026-08-30.1",
        "manifest_sha256": manifest.manifest_sha256,
    }
    values.update(changes)
    return RetrievalResponse(results=[RetrievalResult.model_validate(values)])


def test_manifest_bound_evaluation_uses_no_course_or_collection_mapping() -> None:
    manifest = _manifest()
    calls: list[str] = []

    evidence = evaluate_manifest_bound_suite(
        suite=_suite(),
        manifest=manifest,
        index_sha256=SHA_A,
        producer_commit=SHA_A[:40],
        generated_at=NOW,
        retrieve=lambda query, corpus: (calls.append(corpus.physical_collection), _response())[1],
        embedding_model="intfloat/multilingual-e5-large",
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        top_k=20,
    )

    assert calls == ["rag_nexus_maths_terminale_gen_specialite"]
    assert evidence.manifest_sha256 == manifest.manifest_sha256
    assert evidence.golden_suite_sha256 == _suite().suite_sha256
    assert evidence.automated_gate_pass is True
    assert evidence.promotion_status == "BLOCKED_PENDING_HUMAN_REVIEW"


def test_manifest_bound_evaluation_fails_when_any_query_misses_recall_threshold() -> None:
    first = _suite().queries[0].model_dump(mode="json")
    second = {**first, "id": "Q002", "query": "Expliquer la raison d'une suite"}
    suite = _suite(queries=[first, second])

    evidence = evaluate_manifest_bound_suite(
        suite=suite,
        manifest=_manifest(),
        index_sha256=SHA_A,
        producer_commit=SHA_A[:40],
        generated_at=NOW,
        retrieve=lambda query, _corpus: _response()
        if query.id == "Q001"
        else _response(chunk_id="chunk-002", locator={"page": 2}),
        embedding_model="intfloat/multilingual-e5-large",
        reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
        top_k=20,
    )

    assert evidence.metrics.recall_at_20 == pytest.approx(0.5)
    assert evidence.automated_gate_pass is False


@pytest.mark.parametrize(
    "changes",
    [
        {"manifest_sha256": SHA_B},
        {"corpus_id": "aria-nsi-terminale"},
        {"resource_version_id": "33333333-3333-4333-8333-333333333333"},
        {"content_sha256": SHA_B},
        {"locator": {"page": 2}},
    ],
)
def test_manifest_bound_evaluation_refuses_identity_drift(changes: dict[str, object]) -> None:
    manifest = _manifest()
    if "manifest_sha256" in changes or "corpus_id" in changes:
        suite = _suite(**changes)
        response = _response()
    else:
        suite = _suite()
        response = _response(**changes)

    with pytest.raises(ManifestEvaluationError):
        evaluate_manifest_bound_suite(
            suite=suite,
            manifest=manifest,
            index_sha256=SHA_A,
            producer_commit=SHA_A[:40],
            generated_at=NOW,
            retrieve=lambda _query, _corpus: response,
            embedding_model="intfloat/multilingual-e5-large",
            reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
            top_k=20,
        )


def test_manifest_bound_evaluation_rejects_unknown_relevant_chunk_before_retrieval() -> None:
    query = dict(_suite().queries[0].model_dump(mode="json"))
    query["relevant_chunk_ids"] = ["unknown"]
    query["graded_relevance"] = {"unknown": 1.0}
    suite = _suite(queries=[query])
    called = False

    def retrieve(_query, _corpus):
        nonlocal called
        called = True
        return _response()

    with pytest.raises(ManifestEvaluationError, match="judgment"):
        evaluate_manifest_bound_suite(
            suite=suite,
            manifest=_manifest(),
            index_sha256=SHA_A,
            producer_commit=SHA_A[:40],
            generated_at=NOW,
            retrieve=retrieve,
            embedding_model="intfloat/multilingual-e5-large",
            reranker_model="cross-encoder/ms-marco-MiniLM-L-6-v2",
            top_k=20,
        )
    assert called is False


def test_eval_sources_contain_no_level_to_collection_mapping() -> None:
    sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (EVAL_DIR / "run_eval.py", EVAL_DIR / "manifest_eval.py")
    )
    assert "COLLECTION_BY_NIVEAU" not in sources
