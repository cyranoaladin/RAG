"""Tests de visibilité review_status pour `/search/v2` (LOT 26.2 + LOT 26.3)."""

from __future__ import annotations

import inspect
import os
import sys
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.retrieval_v2_endpoint import (  # noqa: E402
    _cache_get,
    _cache_key,
    _cache_put,
    invalidate_cache,
    router,
    search_v2,
)


def _base_cfg() -> dict:
    return {
        "collections": {
            "rag_nexus_nsi_terminale_specialite": {
                "matiere": "nsi",
                "niveau": "terminale",
                "statut": "specialite",
                "domain": "education",
                "instanciee": True,
            }
        },
        "domains": {
            "education": {"retrievable": True},
        },
    }


def _build_fake_pg_conn(candidates: list[tuple]) -> MagicMock:
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cursor
    cursor.fetchall.return_value = candidates
    return conn


@pytest.fixture(autouse=True)
def clear_cache_between_tests() -> Iterator[None]:
    invalidate_cache()
    try:
        yield
    finally:
        invalidate_cache()


def _setup_app() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _nexus_contracts_modules() -> tuple[object, object]:
    contracts = __import__("types").ModuleType("nexus_contracts")
    embedding = __import__("types").ModuleType("nexus_contracts.embedding_utils")
    embedding.format_query = lambda text: text  # type: ignore[attr-defined]
    contracts.embedding_utils = embedding  # type: ignore[attr-defined]
    return contracts, embedding


def _set_search_tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_ADMIN_TOKEN", "admin-token")
    monkeypatch.setenv("RAG_REVIEWER_TOKEN", "reviewer-token")
    monkeypatch.setenv("RAG_TEACHER_TOKEN", "teacher-token")
    monkeypatch.setenv("RAG_INGEST_AGENT_TOKEN", "ingest-agent-token")
    monkeypatch.setenv("RAG_STUDENT_TOKEN", "student-token")


def test_search_token_setup_is_reverted_after_monkeypatch_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAG_STUDENT_TOKEN", raising=False)

    with monkeypatch.context() as token_environment:
        _set_search_tokens(token_environment)
        assert os.environ["RAG_STUDENT_TOKEN"] == "student-token"

    assert "RAG_STUDENT_TOKEN" not in os.environ


def test_search_v2_source_filters_reviewed_only() -> None:
    source = inspect.getsource(search_v2)
    assert "review_status = 'reviewed'" in source
    assert "review_status IN ('reviewed', 'needs_review')" not in source


def test_search_v2_fails_closed_without_shared_query_formatter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_search_tokens(monkeypatch)
    client = _setup_app()

    contracts = __import__("types").ModuleType("nexus_contracts")
    embedding = __import__("types").ModuleType("nexus_contracts.embedding_utils")
    contracts.embedding_utils = embedding  # type: ignore[attr-defined]

    with (
        patch.dict(
            sys.modules,
            {
                "nexus_contracts": contracts,
                "nexus_contracts.embedding_utils": embedding,
            },
        ),
        patch("ingestor.retrieval_v2_endpoint.load_collection_config", return_value=_base_cfg()),
        patch(
            "ingestor.retrieval_v2_endpoint._check_retrievable",
            return_value={"domain": "education"},
        ),
        patch("ingestor.retrieval_v2_endpoint._get_pg_dsn", return_value="postgresql://x"),
        patch("ingestor.retrieval_v2_endpoint._get_embed_model") as m_embed,
        patch(
            "ingestor.retrieval_v2_endpoint.psycopg.connect",
            return_value=_build_fake_pg_conn([]),
        ),
    ):
        m_embed.return_value = MagicMock(encode=lambda *args, **kwargs: [0.1])

        response = client.post(
            "/search/v2",
            json={
                "q": "algo",
                "collection": "rag_nexus_nsi_terminale_specialite",
                "k": 5,
            },
            headers={"Authorization": "Bearer student-token"},
        )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "/search/v2: embedding query formatter unavailable"
    }
    m_embed.assert_not_called()


def test_all_roles_only_return_reviewed_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_search_tokens(monkeypatch)
    client = _setup_app()

    fake_payload = [
        ("c1", "d1", "l1", "u1", "rights", "cours", "chunk reviewed", 0.99, "reviewed"),
        ("c2", "d2", "l2", "u2", "rights", "cours", "chunk needs", 0.98, "needs_review"),
        ("c3", "d3", "l3", "u3", "rights", "cours", "chunk rejected", 0.97, "rejected"),
        ("c4", "d4", "l4", "u4", "rights", "cours", "chunk quarantined", 0.96, "quarantined"),
    ]

    contracts, embedding = _nexus_contracts_modules()

    actor_tokens = [
        "admin-token",
        "reviewer-token",
        "teacher-token",
        "ingest-agent-token",
        "student-token",
    ]

    for token in actor_tokens:
        with (
            patch.dict(sys.modules, {"nexus_contracts": contracts, "nexus_contracts.embedding_utils": embedding}),
            patch("ingestor.retrieval_v2_endpoint.load_collection_config", return_value=_base_cfg()),
            patch("ingestor.retrieval_v2_endpoint._check_retrievable", return_value={"domain": "education"}),
            patch("ingestor.retrieval_v2_endpoint._get_pg_dsn", return_value="postgresql://x"),
            patch("ingestor.retrieval_v2_endpoint._get_embed_model") as m_embed,
            patch("ingestor.retrieval_v2_endpoint._get_reranker") as m_rerank,
            patch("ingestor.retrieval_v2_endpoint.psycopg.connect", return_value=_build_fake_pg_conn(fake_payload)),
        ):

            m_embed.return_value = MagicMock(encode=lambda *args, **kwargs: [0.1])
            m_rerank.return_value = MagicMock(predict=lambda pairs: [2.4, 2.1, 2.05, 2.0])

            response = client.post(
                "/search/v2",
                json={"q": "algo", "collection": "rag_nexus_nsi_terminale_specialite", "k": 5},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        body = response.json()
        assert body["returned"] == 1
        assert len(body["hits"]) == 1
        assert body["hits"][0]["chunk_id"] == "c1"
        assert {hit["review_status"] for hit in body["hits"]} == {"reviewed"}


def test_search_v2_cache_stale_status_is_not_returned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If cache contains non-reviewed hits, fail-closed path must recompute."""

    _set_search_tokens(monkeypatch)
    client = _setup_app()

    cache_key = _cache_key("query", "rag_nexus_nsi_terminale_specialite", 5)
    _cache_put(cache_key, [
        {
            "chunk_id": "cached_nr",
            "doc_id": "cached-d1",
            "source_label": "src",
            "source_uri": "uri",
            "rights": "rights",
            "type_doc": "cours",
            "review_status": "needs_review",
            "preview": "preview",
            "rerank_score": 1.0,
            "dense_sim": 0.8,
        }
    ])

    db_candidates = [
        ("c1", "d1", "l1", "u1", "rights", "cours", "chunk reviewed", 0.99, "reviewed"),
        ("c2", "d2", "l2", "u2", "rights", "cours", "chunk needs", 0.98, "needs_review"),
        ("c3", "d3", "l3", "u3", "rights", "cours", "chunk rejected", 0.97, "rejected"),
        ("c4", "d4", "l4", "u4", "rights", "cours", "chunk quarantined", 0.96, "quarantined"),
    ]

    contracts, embedding = _nexus_contracts_modules()

    with (
        patch.dict(sys.modules, {"nexus_contracts": contracts, "nexus_contracts.embedding_utils": embedding}),
        patch("ingestor.retrieval_v2_endpoint.load_collection_config", return_value=_base_cfg()),
        patch("ingestor.retrieval_v2_endpoint._check_retrievable", return_value={"domain": "education"}),
        patch("ingestor.retrieval_v2_endpoint._get_pg_dsn", return_value="postgresql://x"),
        patch("ingestor.retrieval_v2_endpoint._get_embed_model") as m_embed,
        patch("ingestor.retrieval_v2_endpoint._get_reranker") as m_rerank,
        patch("ingestor.retrieval_v2_endpoint.psycopg.connect", return_value=_build_fake_pg_conn(db_candidates)),
    ):

        m_embed.return_value = MagicMock(encode=lambda *args, **kwargs: [0.1])
        m_rerank.return_value = MagicMock(predict=lambda pairs: [2.4, 2.1, 2.05, 2.0])

        response = client.post(
            "/search/v2",
            json={"q": "query", "collection": "rag_nexus_nsi_terminale_specialite", "k": 5},
            headers={"Authorization": "Bearer student-token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["returned"] == 1
    assert body["hits"][0]["chunk_id"] == "c1"
    assert body["hits"][0]["review_status"] == "reviewed"


def test_search_v2_does_not_serve_reviewed_cache_without_current_db_review(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cache hits are ignored when DB has no current reviewed chunk."""

    _set_search_tokens(monkeypatch)
    client = _setup_app()

    cache_key = _cache_key("query", "rag_nexus_nsi_terminale_specialite", 5)
    _cache_put(cache_key, [
        {
            "chunk_id": "cached_reviewed",
            "doc_id": "cached-d",
            "source_label": "cached-src",
            "source_uri": "cached-uri",
            "rights": "rights",
            "type_doc": "cours",
            "review_status": "reviewed",
            "preview": "cached preview",
            "rerank_score": 2.5,
            "dense_sim": 0.9,
        }
    ])

    db_candidates = [
        ("c1", "d1", "l1", "u1", "rights", "cours", "needs review", 0.99, "needs_review"),
        ("c2", "d2", "l2", "u2", "rights", "cours", "rejected", 0.98, "rejected"),
        ("c3", "d3", "l3", "u3", "rights", "cours", "quarantined", 0.97, "quarantined"),
    ]

    contracts, embedding = _nexus_contracts_modules()

    with (
        patch.dict(sys.modules, {"nexus_contracts": contracts, "nexus_contracts.embedding_utils": embedding}),
        patch("ingestor.retrieval_v2_endpoint.load_collection_config", return_value=_base_cfg()),
        patch("ingestor.retrieval_v2_endpoint._check_retrievable", return_value={"domain": "education"}),
        patch("ingestor.retrieval_v2_endpoint._get_pg_dsn", return_value="postgresql://x"),
        patch("ingestor.retrieval_v2_endpoint._get_embed_model") as m_embed,
        patch("ingestor.retrieval_v2_endpoint._get_reranker") as m_rerank,
        patch("ingestor.retrieval_v2_endpoint.psycopg.connect", return_value=_build_fake_pg_conn(db_candidates)),
    ):

        m_embed.return_value = MagicMock(encode=lambda *args, **kwargs: [0.1])
        m_rerank.return_value = MagicMock(predict=lambda pairs: [2.2, 2.1, 2.0])

        response = client.post(
            "/search/v2",
            json={"q": "query", "collection": "rag_nexus_nsi_terminale_specialite", "k": 5},
            headers={"Authorization": "Bearer teacher-token"},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["returned"] == 0
    assert body["hits"] == []


def test_cache_warmup_ignores_non_reviewed_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Warmup must never cache non-reviewed candidates."""

    _set_search_tokens(monkeypatch)
    client = _setup_app()

    fake_payload = [
        ("c1", "d1", "l1", "u1", "rights", "cours", "chunk reviewed", 0.99, "reviewed"),
        ("c2", "d2", "l2", "u2", "rights", "cours", "chunk needs", 0.98, "needs_review"),
        ("c3", "d3", "l3", "u3", "rights", "cours", "chunk rejected", 0.97, "rejected"),
        ("c4", "d4", "l4", "u4", "rights", "cours", "chunk quarantined", 0.96, "quarantined"),
    ]

    contracts, embedding = _nexus_contracts_modules()

    with (
        patch.dict(sys.modules, {"nexus_contracts": contracts, "nexus_contracts.embedding_utils": embedding}),
        patch("ingestor.retrieval_v2_endpoint.load_collection_config", return_value=_base_cfg()),
        patch("ingestor.retrieval_v2_endpoint._get_pg_dsn", return_value="postgresql://x"),
        patch("ingestor.retrieval_v2_endpoint._get_embed_model") as m_embed,
        patch("ingestor.retrieval_v2_endpoint._get_reranker") as m_rerank,
        patch("ingestor.retrieval_v2_endpoint.psycopg.connect", return_value=_build_fake_pg_conn(fake_payload)),
    ):

        m_embed.return_value = MagicMock(encode=lambda *args, **kwargs: [0.1])
        m_rerank.return_value = MagicMock(predict=lambda pairs: [2.4, 2.1, 2.05, 2.0])

        response = client.post(
            "/cache/v2/warmup",
            headers={"Authorization": "Bearer admin-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["warmed"] == payload["queries"]

    cached = _cache_get(_cache_key(
        "Comment fonctionne une boucle while en Python ?",
        "rag_nexus_nsi_terminale_specialite",
        5,
    ))
    assert cached is not None
    assert all(item["review_status"] == "reviewed" for item in cached)
