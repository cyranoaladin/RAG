"""Visibilité reviewed-only sur le pipeline hybride public LOT40."""

from __future__ import annotations

import inspect
import os
import sys
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nexus_contracts import Rights

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor import retrieval_v2_endpoint as endpoint  # noqa: E402
from ingestor.retrieval_hybrid_v2 import (  # noqa: E402
    HybridHit,
    RetrievalCandidate,
)
from ingestor.retrieval_scope_v2 import ServerRetrievalScope  # noqa: E402

COLLECTION = "rag_nexus_nsi_terminale_specialite"
SCOPE = ServerRetrievalScope(
    tenant="libre_terminale",
    niveau="terminale",
    voie="generale",
    matiere="nsi",
    statut_enseignement="specialite",
    candidat="individuel",
    audiences=("libre", "tous"),
    rights=(Rights.officiel_public, Rights.public_allowed),
    visibilities=("public",),
    school_year="2026-2027",
    collection=COLLECTION,
    programme_version="BOEN_special_8_2019-07-25",
    scope_id="lot41_test_scope",
    scope_digest="a" * 64,
    source_sha256="b" * 64,
)


def _payload(query: str, *, k: int = 5) -> dict[str, object]:
    return {
        "student_profile": {
            "niveau": "terminale",
            "voie": "generale",
            "matieres": ["nsi"],
            "statut_enseignement": "specialite",
            "candidat": "individuel",
            "status_detail": "candidat_libre",
            "school_year": "2026-2027",
            "zone": "libre",
        },
        "need": {"intent": "context", "query": query},
        "retrieval": {
            "k": k,
            "hybrid": True,
            "rerank": True,
            "include_citations": True,
        },
    }


def _base_cfg() -> dict:
    return {
        "collections": {
            COLLECTION: {
                "matiere": "nsi",
                "niveau": "terminale",
                "statut": "specialite",
                "domain": "education",
                "instanciee": True,
            }
        },
        "domains": {"education": {"retrievable": True}},
    }


def _reviewed_hit() -> HybridHit:
    return HybridHit(
        candidate=RetrievalCandidate(
            chunk_id="chunk-reviewed",
            doc_id="doc-reviewed",
            source_label="Programme officiel",
            source_uri="https://example.edu/programme",
            rights="official_public_administrative",
            type_doc="programme",
            text="Une preuve revue et substantielle.",
            page_start=4,
            vector=(1.0,) + (0.0,) * 1023,
            review_status="reviewed",
            dense_score=0.91,
            lexical_score=0.52,
        ),
        dense_rank=1,
        lexical_rank=1,
        rrf_score=0.016,
        rerank_score=2.8,
        mmr_score=0.61,
        score_final=0.88,
    )


@pytest.fixture(autouse=True)
def clear_cache_between_tests() -> Iterator[None]:
    endpoint.invalidate_cache()
    try:
        yield
    finally:
        endpoint.invalidate_cache()


def _setup_app() -> TestClient:
    app = FastAPI()
    app.include_router(endpoint.router)
    return TestClient(app)


def _set_search_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("RAG_REVIEWER_TOKEN", "reviewer-token")
    monkeypatch.setenv("RAG_TEACHER_TOKEN", "teacher-token")
    monkeypatch.setenv("RAG_INGEST_AGENT_TOKEN", "ingest-agent-token")
    monkeypatch.setenv("RAG_STUDENT_TOKEN", "student-token")
    monkeypatch.setattr(
        endpoint,
        "_require_retrieval_identity",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        endpoint,
        "build_server_retrieval_scope",
        lambda *_args, **_kwargs: SCOPE,
    )
    monkeypatch.setattr(
        endpoint,
        "_collection_for_retrieval_request",
        lambda *_args, **_kwargs: COLLECTION,
    )


def test_search_token_setup_is_reverted_after_monkeypatch_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAG_STUDENT_TOKEN", raising=False)

    with monkeypatch.context() as token_environment:
        _set_search_tokens(token_environment)
        assert os.environ["RAG_STUDENT_TOKEN"] == "student-token"

    assert "RAG_STUDENT_TOKEN" not in os.environ


def test_search_v2_has_no_direct_visibility_or_database_pipeline() -> None:
    source = inspect.getsource(endpoint.search_v2)
    assert "_check_retrievable" in source
    assert "_retrieve_endpoint_hits" in source
    assert "psycopg" not in source
    assert "review_status IN ('reviewed', 'needs_review')" not in source


@pytest.mark.parametrize(
    "token",
    [
        "admin-token",
        "reviewer-token",
        "teacher-token",
        "ingest-agent-token",
        "student-token",
    ],
)
def test_all_roles_only_receive_reviewed_hybrid_hits(
    token: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_search_tokens(monkeypatch)
    monkeypatch.setattr(endpoint, "load_collection_config", _base_cfg)
    monkeypatch.setattr(endpoint, "_check_retrievable", lambda *_args: {})
    retrieve = MagicMock(return_value=[_reviewed_hit()])
    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)

    response = _setup_app().post(
        "/search/v2",
        json=_payload("algo"),
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1
    assert body["results"][0]["chunk_id"] == "chunk-reviewed"
    assert body["results"][0]["metadata"]["review_status"] == "reviewed"
    assert retrieve.call_count == 1
    called = retrieve.call_args
    assert called.args == ("algo", COLLECTION, 5, SCOPE)
    # Aucun filtre pédagogique demandé : le prédicat de placement décide seul.
    assert called.kwargs["metadata_filters"].is_empty


def test_public_search_ignores_even_reviewed_cache_and_requeries_pipeline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_search_tokens(monkeypatch)
    monkeypatch.setattr(endpoint, "load_collection_config", _base_cfg)
    monkeypatch.setattr(endpoint, "_check_retrievable", lambda *_args: {})
    key = endpoint._cache_key("query", COLLECTION, 5)
    with endpoint._cache_lock:
        endpoint._cache[key] = ([{"chunk_id": "stale-reviewed"}], time.monotonic())
    retrieve = MagicMock(return_value=[])
    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)
    assert "_cache" not in inspect.getsource(endpoint.search_v2)

    response = _setup_app().post(
        "/search/v2",
        json=_payload("query"),
        headers={"Authorization": "Bearer teacher-token"},
    )

    assert response.status_code == 200
    assert response.json()["results"] == []
    assert retrieve.call_count == 1
    called = retrieve.call_args
    assert called.args == ("query", COLLECTION, 5, SCOPE)
    # Aucun filtre pédagogique demandé : le prédicat de placement décide seul.
    assert called.kwargs["metadata_filters"].is_empty


def test_cache_warmup_is_disabled_and_never_serializes_unscoped_hits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_search_tokens(monkeypatch)
    monkeypatch.setattr(endpoint, "load_collection_config", _base_cfg)
    monkeypatch.setattr(
        endpoint,
        "list_instanciated_collections",
        lambda _cfg: [COLLECTION],
    )
    monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", lambda *_args: [_reviewed_hit()])

    response = _setup_app().post(
        "/cache/v2/warmup",
        headers={"Authorization": "Bearer admin-token"},
    )

    assert response.status_code == 200
    assert response.json() == {"warmed": 0, "collections": 0, "queries": 0}
    with endpoint._cache_lock:
        assert endpoint._cache == {}
