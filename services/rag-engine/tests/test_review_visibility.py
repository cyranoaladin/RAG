"""Tests de visibilité review_status pour `/search/v2` (LOT 26.2)."""

from __future__ import annotations

import os
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

import inspect

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ingestor.retrieval_v2_endpoint import (  # noqa: E402
    _cache_key,
    _cache_put,
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


def _setup_app() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _nexus_contracts_modules() -> tuple[types.ModuleType, types.ModuleType]:
    contracts = types.ModuleType("nexus_contracts")
    embedding = types.ModuleType("nexus_contracts.embedding_utils")
    embedding.format_query = lambda text: text  # type: ignore[attr-defined]
    contracts.embedding_utils = embedding  # type: ignore[attr-defined]
    return contracts, embedding


def test_search_v2_source_filters_reviewed_only() -> None:
    source = inspect.getsource(search_v2)
    assert "review_status = 'reviewed'" in source
    assert "review_status IN ('reviewed', 'needs_review')" not in source


def test_student_search_does_not_return_non_reviewed() -> None:
    """Search must return only reviewed status payload for `/search/v2`."""

    os.environ["INGESTOR_API_TOKEN"] = "test-token"
    client = _setup_app()

    fake_payload = [
        ("c1", "d1", "l1", "u1", "rights", "cours", "chunk reviewed", 0.99, "reviewed"),
        ("c2", "d2", "l2", "u2", "rights", "cours", "chunk pending", 0.98, "needs_review"),
        ("c3", "d3", "l3", "u3", "rights", "cours", "chunk quarantined", 0.97, "quarantined"),
    ]

    contracts, embedding = _nexus_contracts_modules()

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
        m_rerank.return_value = MagicMock(predict=lambda pairs: [2.0, 1.8, 1.7])

        resp = client.post(
            "/search/v2",
            json={"q": "algo", "collection": "rag_nexus_nsi_terminale_specialite", "k": 5},
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["returned"] == 1
    assert len(body["hits"]) == 1
    assert body["hits"][0]["chunk_id"] == "c1"
    assert body["hits"][0]["review_status"] == "reviewed"


def test_search_v2_cache_stale_status_is_not_returned() -> None:
    """If cache contains non-reviewed hits, fail-closed path must recompute."""

    os.environ["INGESTOR_API_TOKEN"] = "test-token"
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
        m_rerank.return_value = MagicMock(predict=lambda pairs: [2.0])

        resp = client.post(
            "/search/v2",
            json={"q": "query", "collection": "rag_nexus_nsi_terminale_specialite", "k": 5},
            headers={"Authorization": "Bearer test-token"},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["returned"] == 1
    assert body["hits"][0]["chunk_id"] == "c1"
    assert body["hits"][0]["review_status"] == "reviewed"
