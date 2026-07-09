"""Tests for retrieval v2 FastAPI endpoint (FE-01).

Tests the gate behavior, response format, and collection listing
WITHOUT needing a live pgvector or model loading.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import HTTPException

from ingestor.retrieval_v2_endpoint import (
    SearchV2Request,
    _check_retrievable,
    list_retrievable_collections,
)

# --- Fixtures ---

FULL_CFG = {
    "version": 2,
    "collections": {
        "rag_nexus_nsi_terminale_specialite": {
            "matiere": "nsi", "niveau": "terminale", "statut": "specialite",
            "domain": "education", "instanciee": True,
        },
        "rag_nexus_nsi_premiere_specialite": {
            "matiere": "nsi", "niveau": "premiere", "statut": "specialite",
            "domain": "education", "instanciee": True,
        },
        "rag_nexus_quarantine": {
            "matiere": None, "niveau": None, "statut": None,
            "domain": "quarantine", "instanciee": True,
        },
        "rag_nexus_maths_seconde_tc": {
            "matiere": "maths", "niveau": "seconde", "statut": "tronc_commun",
            "domain": "education", "instanciee": False,
        },
    },
    "domains": {
        "education": {"audiences": ["tous"], "retrievable": True},
        "quarantine": {"retrievable": False},
    },
}


class TestGateHTTP:
    """Gate retrievable via HTTP exceptions (endpoint-level)."""

    def test_quarantine_403(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            _check_retrievable("rag_nexus_quarantine", FULL_CFG)
        assert exc_info.value.status_code == 403
        assert "not retrievable" in exc_info.value.detail

    def test_education_passes(self) -> None:
        defn = _check_retrievable("rag_nexus_nsi_terminale_specialite", FULL_CFG)
        assert defn["matiere"] == "nsi"
        assert defn["domain"] == "education"

    def test_missing_domain_403(self) -> None:
        cfg = {
            **FULL_CFG,
            "collections": {
                **FULL_CFG["collections"],
                "col_no_domain": {"matiere": "test", "instanciee": True},
            },
        }
        with pytest.raises(HTTPException) as exc_info:
            _check_retrievable("col_no_domain", cfg)
        assert exc_info.value.status_code == 403

    def test_domains_section_malformed_500(self) -> None:
        cfg = {**FULL_CFG, "domains": "not_a_dict"}
        with pytest.raises(HTTPException) as exc_info:
            _check_retrievable("rag_nexus_nsi_terminale_specialite", cfg)
        assert exc_info.value.status_code == 500


class TestListRetrievable:
    """GET /collections/v2 returns only instanciee+retrievable."""

    @patch("ingestor.retrieval_v2_endpoint.load_collection_config", return_value=FULL_CFG)
    def test_list_excludes_quarantine(self, _mock: MagicMock) -> None:
        result = list_retrievable_collections()
        names = [c["name"] for c in result["collections"]]
        # NSI collections are instanciee:true + domain education (retrievable:true)
        assert "rag_nexus_nsi_terminale_specialite" in names
        assert "rag_nexus_nsi_premiere_specialite" in names
        # Quarantine is instanciee:true but domain quarantine (retrievable:false)
        assert "rag_nexus_quarantine" not in names
        # Maths is instanciee:false
        assert "rag_nexus_maths_seconde_tc" not in names

    @patch("ingestor.retrieval_v2_endpoint.load_collection_config", return_value=FULL_CFG)
    def test_list_includes_metadata(self, _mock: MagicMock) -> None:
        result = list_retrievable_collections()
        nsi_tle = next(c for c in result["collections"] if c["name"] == "rag_nexus_nsi_terminale_specialite")
        assert nsi_tle["matiere"] == "nsi"
        assert nsi_tle["niveau"] == "terminale"
        assert nsi_tle["statut"] == "specialite"
        assert nsi_tle["domain"] == "education"


class TestSearchV2Request:
    """Pydantic validation for SearchV2Request."""

    def test_valid_request(self) -> None:
        req = SearchV2Request(q="arbre binaire", collection="rag_nexus_nsi_terminale_specialite", k=5)
        assert req.q == "arbre binaire"
        assert req.k == 5

    def test_empty_query_rejected(self) -> None:
        with pytest.raises(ValueError):
            SearchV2Request(q="", collection="test")

    def test_k_bounds(self) -> None:
        with pytest.raises(ValueError):
            SearchV2Request(q="test", collection="test", k=0)
        with pytest.raises(ValueError):
            SearchV2Request(q="test", collection="test", k=51)


class TestResponseFormat:
    """Verify SearchV2Response has answer_generation_allowed=false."""

    def test_answer_generation_always_false(self) -> None:
        from ingestor.retrieval_v2_endpoint import SearchV2Response
        resp = SearchV2Response(
            query="test", collection="test", seuil=1.90, returned=0, hits=[]
        )
        assert resp.answer_generation_allowed is False

    def test_hit_exposes_review_status(self) -> None:
        """SCALE-04: review_status in each hit for agent layer."""
        from ingestor.retrieval_v2_endpoint import SearchV2Hit
        hit = SearchV2Hit(
            chunk_id="c1", doc_id="d1", source_label="s.pdf", source_uri="u",
            rights="usage_interne", type_doc="cours", review_status="reviewed",
            preview="text", rerank_score=5.0, dense_sim=0.85,
        )
        assert hit.review_status == "reviewed"

        hit_nr = SearchV2Hit(
            chunk_id="c2", doc_id="d2", source_label="s2.pdf", source_uri="u2",
            rights="usage_interne", type_doc="cours", review_status="needs_review",
            preview="text", rerank_score=3.0, dense_sim=0.80,
        )
        assert hit_nr.review_status == "needs_review"


class TestCacheGateInvariant:
    """Invariant C: cache never serves a chunk that became non-review.

    The gate (resolve_collection_v2 + domain retrievable) is checked BEFORE
    the cache lookup. The cache is keyed by (query, collection, k) and only
    stores results from retrievable collections. A quarantined collection
    always hits the gate FIRST and is refused with 403.

    Additionally:
    - TTL ensures stale entries expire (default 5 min)
    - invalidate_cache() purges all entries on review_status change
    - SQL WHERE review_status = 'reviewed' excludes non-review statuses
    """

    def test_gate_before_cache(self) -> None:
        """Quarantine is refused by the gate BEFORE cache is even checked."""
        import os

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ingestor.retrieval_v2_endpoint import (
            _cache_key,
            _cache_put,
            router,
        )

        os.environ.setdefault("INGESTOR_API_TOKEN", "test-inv-c")

        test_app = FastAPI()
        test_app.include_router(router)
        test_client = TestClient(test_app)
        h = {"Authorization": "Bearer test-inv-c"}

        # Even if we artificially stuff the cache with quarantine results,
        # the gate refuses BEFORE the cache is consulted.
        fake_key = _cache_key("test query", "rag_nexus_quarantine", 5)
        _cache_put(fake_key, [{"chunk_id": "fake", "doc_id": "fake",
                               "source_label": "fake", "source_uri": "fake",
                               "rights": "fake", "type_doc": "fake",
                               "review_status": "quarantined", "preview": "fake",
                               "rerank_score": 9.0, "dense_sim": 0.99}])

        resp = test_client.post("/search/v2", json={
            "q": "test query", "collection": "rag_nexus_quarantine", "k": 5,
        }, headers=h)
        assert resp.status_code == 403, "Gate must refuse quarantine even with cache populated"

    def test_invalidation_purges_cache(self) -> None:
        """invalidate_cache() removes all entries."""
        from ingestor.retrieval_v2_endpoint import (
            _cache_get,
            _cache_key,
            _cache_put,
            invalidate_cache,
        )

        key = _cache_key("test", "test_col", 5)
        _cache_put(key, [{"test": "data"}])
        assert _cache_get(key) is not None

        invalidate_cache()
        assert _cache_get(key) is None, "Cache must be empty after invalidation"

    def test_ttl_expires_entries(self) -> None:
        """Entries expire after TTL seconds."""
        import time
        from unittest.mock import patch

        from ingestor.retrieval_v2_endpoint import (
            _cache_get,
            _cache_key,
            _cache_put,
        )

        key = _cache_key("ttl-test", "col", 5)
        _cache_put(key, [{"test": "data"}])
        assert _cache_get(key) is not None

        # Simulate TTL expiration by patching time.monotonic
        with patch("ingestor.retrieval_v2_endpoint.time.monotonic",
                    return_value=time.monotonic() + 999):
            assert _cache_get(key) is None, "Entry must expire after TTL"

    def test_sql_excludes_quarantined(self) -> None:
        """SQL WHERE clause never returns quarantined chunks."""
        import inspect

        from ingestor.retrieval_v2_endpoint import search_v2
        source = inspect.getsource(search_v2)
        assert "review_status = 'reviewed'" in source, "Search must filter to reviewed only"
