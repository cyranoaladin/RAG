"""Tests for retrieval v2 FastAPI endpoint (FE-01).

Tests the gate behavior, response format, and collection listing
WITHOUT needing a live pgvector or model loading.
"""
from __future__ import annotations

import copy
import inspect
import socket
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, call, patch

import pytest
from pydantic import ValidationError

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import HTTPException

from ingestor.retrieval_v2_endpoint import (
    SearchV2Request,
    _build_launch_readiness,
    _check_retrievable,
)
from ingestor.retrieval_v2_endpoint import (
    _list_retrievable_collections as list_retrievable_collections,
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


def _hybrid_hit(
    *,
    chunk_id: str = "chunk-1",
    doc_id: str = "doc-1",
    dense_score: float | None = 0.81,
    lexical_score: float | None = 0.42,
    page: int | None = 3,
):
    from ingestor.retrieval_hybrid_v2 import HybridHit, RetrievalCandidate

    return HybridHit(
        candidate=RetrievalCandidate(
            chunk_id=chunk_id,
            doc_id=doc_id,
            source_label="Programme NSI",
            source_uri=f"https://example.edu/{doc_id}",
            rights="official_public_administrative",
            type_doc="programme",
            text="Une ressource validée et substantielle.",
            page_start=page,
            vector=(1.0,) + (0.0,) * 1023,
            review_status="reviewed",
            dense_score=dense_score,
            lexical_score=lexical_score,
        ),
        dense_rank=1 if dense_score is not None else None,
        lexical_rank=1 if lexical_score is not None else None,
        rrf_score=0.016,
        rerank_score=2.75,
        mmr_score=0.612,
        score_final=0.884,
    )


def _api_client(monkeypatch: pytest.MonkeyPatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ingestor import retrieval_v2_endpoint as endpoint

    monkeypatch.setenv("RAG_STUDENT_TOKEN", "student-token")
    monkeypatch.setenv("RAG_ADMIN_TOKEN", "admin-token")
    monkeypatch.setattr(endpoint, "load_collection_config", lambda: FULL_CFG)
    app = FastAPI()
    app.include_router(endpoint.router)
    return endpoint, TestClient(app)


def _seed_cache(
    endpoint: object,
    key: str,
    hits: list[dict[str, object]],
    *,
    timestamp: float | None = None,
) -> None:
    with endpoint._cache_lock:
        endpoint._cache[key] = (
            copy.deepcopy(hits),
            time.monotonic() if timestamp is None else timestamp,
        )


def _cache_snapshot(endpoint: object) -> dict[str, tuple[list, float]]:
    with endpoint._cache_lock:
        return copy.deepcopy(endpoint._cache)


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
            page=7, preview="text", dense_score=0.85, lexical_score=None,
            rrf_score=0.01, rerank_score=5.0, mmr_score=0.6, score_final=0.9,
        )
        assert hit.review_status == "reviewed"
        assert hit.page == 7
        assert hit.dense_score == 0.85
        assert hit.lexical_score is None
        assert hit.rrf_score == 0.01
        assert hit.score_final == 0.9

        assert hit.dense_sim == hit.dense_score
        assert hit.model_dump()["dense_sim"] == hit.dense_score
        serialization_schema = SearchV2Hit.model_json_schema(mode="serialization")
        assert serialization_schema["properties"]["dense_sim"]["readOnly"] is True
        assert serialization_schema["properties"]["dense_sim"]["deprecated"] is True

        no_dense_hit = SearchV2Hit(
            **{**hit.model_dump(exclude={"dense_sim"}), "dense_score": None}
        )
        assert no_dense_hit.dense_sim is None
        assert no_dense_hit.model_dump()["dense_sim"] is None

        cockpit_route = (
            Path(__file__).resolve().parents[2]
            / "cockpit"
            / "src"
            / "app"
            / "api"
            / "search"
            / "route.ts"
        ).read_text(encoding="utf-8")
        assert "hit.dense_sim" in cockpit_route

        with pytest.raises(ValidationError):
            SearchV2Hit(
                chunk_id="c2", doc_id="d2", source_label="s2.pdf", source_uri="u2",
                rights="usage_interne", type_doc="cours", review_status="needs_review",
                page=None, preview="text", dense_score=None, lexical_score=0.7,
                rrf_score=0.01, rerank_score=3.0, mmr_score=0.5,
                score_final=0.8,
            )

    def test_mapping_hybrid_hit_to_contract_preserves_provenance_and_scores(self) -> None:
        from ingestor.retrieval_hybrid_v2 import HybridHit, RetrievalCandidate
        from ingestor.retrieval_v2_endpoint import _to_retrieval_result, _to_search_hit

        candidate = RetrievalCandidate(
            chunk_id="chunk-1",
            doc_id="doc-1",
            source_label="Programme NSI",
            source_uri="https://example.edu/nsi",
            rights="official_public_administrative",
            type_doc="programme",
            text="  Une ressource validée et substantielle.  ",
            page_start=11,
            vector=(1.0,) + (0.0,) * 1023,
            review_status="reviewed",
            dense_score=None,
            lexical_score=0.42,
        )
        hybrid_hit = HybridHit(
            candidate=candidate,
            dense_rank=None,
            lexical_rank=1,
            rrf_score=0.004918,
            rerank_score=2.75,
            mmr_score=0.612,
            score_final=0.884,
        )

        hit = _to_search_hit(hybrid_hit)
        result = _to_retrieval_result(hit, "rag_nexus_nsi_terminale_specialite")

        assert hit.page == 11
        assert hit.preview == "Une ressource validée et substantielle."
        assert hit.dense_score is None
        assert hit.lexical_score == 0.42
        assert hit.rrf_score == hybrid_hit.rrf_score
        assert hit.rerank_score == hybrid_hit.rerank_score
        assert hit.mmr_score == hybrid_hit.mmr_score
        assert hit.score_final == hybrid_hit.score_final
        assert result.score == hybrid_hit.score_final
        assert result.citation is not None
        assert result.citation.model_dump() == {
            "source_label": "Programme NSI",
            "page": 11,
            "source_uri": "https://example.edu/nsi",
            "rights": "official_public_administrative",
        }
        assert result.metadata == {
            "collection": "rag_nexus_nsi_terminale_specialite",
            "type_doc": "programme",
            "review_status": "reviewed",
            "dense_score": None,
            "lexical_score": 0.42,
            "rrf_score": 0.004918,
            "rerank_score": 2.75,
            "mmr_score": 0.612,
        }

    def test_mapping_refuses_blank_provenance_and_preview(self) -> None:
        from ingestor.retrieval_v2_endpoint import SearchV2Hit

        common = {
            "chunk_id": "chunk-1",
            "doc_id": "doc-1",
            "source_label": "Programme",
            "source_uri": "https://example.edu/source",
            "rights": "official",
            "type_doc": "programme",
            "review_status": "reviewed",
            "page": None,
            "preview": "contenu",
            "dense_score": None,
            "lexical_score": 0.4,
            "rrf_score": 0.01,
            "rerank_score": 2.0,
            "mmr_score": 0.5,
            "score_final": 0.8,
        }
        for field_name in ("source_label", "source_uri", "rights", "preview"):
            with pytest.raises(ValidationError) as exc_info:
                SearchV2Hit(**{**common, field_name: "   "})
            assert (field_name,) in {
                tuple(error["loc"]) for error in exc_info.value.errors()
            }

    def test_constants_are_canonical_and_not_environment_overrides(self) -> None:
        from ingestor import retrieval_hybrid_v2 as core
        from ingestor import retrieval_v2_endpoint as endpoint

        assert endpoint.EMBED_MODEL == core.EMBED_MODEL
        assert endpoint.RERANK_MODEL == core.RERANK_MODEL
        assert endpoint.RERANK_SCORE_THRESHOLD == core.RERANK_THRESHOLD == 1.90
        assert endpoint.RERANK_CANDIDATES == core.CHANNEL_LIMIT == 50
        assert endpoint.RRF_K == core.RRF_K == 60
        assert endpoint.MMR_LAMBDA == core.MMR_LAMBDA == 0.7
        source = inspect.getsource(endpoint)
        assert 'os.environ.get("RERANK_SCORE_THRESHOLD"' not in source
        assert 'os.environ.get("RERANK_CANDIDATES"' not in source
        assert "seuil=RERANK_THRESHOLD" in inspect.getsource(endpoint.search_v2)


class TestLaunchReadiness:
    """The public launch is closed until every declared collection is ready."""

    def test_all_declared_collections_must_be_substantive_and_retrievable(self) -> None:
        readiness = _build_launch_readiness(
            FULL_CFG,
            {
                "rag_nexus_nsi_terminale_specialite": 3,
                "rag_nexus_nsi_premiere_specialite": 3,
                "rag_nexus_quarantine": 3,
                "rag_nexus_maths_seconde_tc": 0,
            },
            min_chunks=3,
        )

        assert readiness["total_collections"] == 4
        assert readiness["launch_ready"] is False
        assert readiness["ready_collections"] == 2
        maths = next(
            item
            for item in readiness["collections"]
            if item["name"] == "rag_nexus_maths_seconde_tc"
        )
        assert maths["ready"] is False
        assert "collection non instanciée" in maths["reasons"]


class TestHybridSearchDelegation:
    def test_search_delegates_raw_parameters_after_gate_and_ignores_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = _api_client(monkeypatch)
        events: list[object] = []

        def check(collection: str, _cfg: dict) -> dict:
            events.append(("gate", collection))
            return {"domain": "education"}

        def retrieve(query: str, collection: str, top_k: int):
            events.append(("retrieve", query, collection, top_k))
            return [_hybrid_hit()]

        monkeypatch.setattr(endpoint, "_check_retrievable", check)
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve, raising=False)
        assert "_cache" not in inspect.getsource(endpoint.search_v2)
        monkeypatch.setattr(
            endpoint.psycopg,
            "connect",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("direct retrieval connection")
            ),
        )

        response = client.post(
            "/search/v2",
            headers={"Authorization": "Bearer student-token"},
            json={
                "q": "  requête brute ?  ",
                "collection": "rag_nexus_nsi_terminale_specialite",
                "k": 4,
            },
        )

        assert response.status_code == 200
        assert events == [
            ("gate", "rag_nexus_nsi_terminale_specialite"),
            (
                "retrieve",
                "  requête brute ?  ",
                "rag_nexus_nsi_terminale_specialite",
                4,
            ),
        ]
        assert response.json() == {
            "query": "  requête brute ?  ",
            "collection": "rag_nexus_nsi_terminale_specialite",
            "seuil": 1.9,
            "returned": 1,
            "answer_generation_allowed": False,
            "hits": [endpoint._to_search_hit(_hybrid_hit()).model_dump()],
        }

    def test_search_empty_hybrid_result_is_success(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = _api_client(monkeypatch)
        monkeypatch.setattr(endpoint, "_check_retrievable", lambda *_args: {})
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", lambda *_args: [], raising=False)

        response = client.post(
            "/search/v2",
            headers={"Authorization": "Bearer student-token"},
            json={
                "q": "aucun résultat",
                "collection": "rag_nexus_nsi_terminale_specialite",
                "k": 5,
            },
        )

        assert response.status_code == 200
        assert response.json()["hits"] == []
        assert response.json()["returned"] == 0

    @pytest.mark.parametrize(
        "stage",
        ["pool", "dense", "lexical", "embedding", "rerank", "mmr"],
    )
    def test_search_sanitizes_every_pipeline_failure(
        self,
        stage: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = _api_client(monkeypatch)
        monkeypatch.setattr(endpoint, "_check_retrievable", lambda *_args: {})

        def fail(*_args: object) -> list[object]:
            raise RuntimeError(
                f"{stage}: SENSITIVE_DSN_SENTINEL SENSITIVE_QUERY_SENTINEL"
            )

        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", fail, raising=False)
        response = client.post(
            "/search/v2",
            headers={"Authorization": "Bearer student-token"},
            json={
                "q": "texte très secret",
                "collection": "rag_nexus_nsi_terminale_specialite",
                "k": 5,
            },
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "retrieval unavailable"}
        serialized = response.text
        assert stage not in serialized
        assert "SENSITIVE_DSN_SENTINEL" not in serialized
        assert "SENSITIVE_QUERY_SENTINEL" not in serialized
        assert "texte très secret" not in serialized

    def test_hybrid_factory_composes_pool_store_and_canonical_models(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ingestor import retrieval_v2_endpoint as endpoint

        factory = getattr(endpoint, "_retrieve_hybrid_hits", None)
        assert callable(factory)

        settings = object()
        connection = object()
        embedder = object()
        reranker = object()
        captured: dict[str, object] = {}

        @contextmanager
        def connection_provider(received_settings: object):
            captured["pool_settings"] = received_settings
            yield connection

        class Store:
            def __init__(self, provider) -> None:
                self.provider = provider

        def retrieve(query, collection, top_k, *, store, embedder, reranker):
            captured.update({
                "query": query,
                "collection": collection,
                "top_k": top_k,
                "store": store,
                "embedder": embedder,
                "reranker": reranker,
            })
            with store.provider() as received_connection:
                captured["connection"] = received_connection
            return [_hybrid_hit()]

        monkeypatch.setattr(
            endpoint,
            "PoolSettings",
            SimpleNamespace(from_env=lambda: settings),
            raising=False,
        )
        monkeypatch.setattr(endpoint, "pool_connection", connection_provider, raising=False)
        monkeypatch.setattr(endpoint, "PgCandidateStore", Store, raising=False)
        monkeypatch.setattr(endpoint, "_get_embed_model", lambda: embedder)
        monkeypatch.setattr(endpoint, "_get_reranker", lambda: reranker)
        monkeypatch.setattr(endpoint, "retrieve_hybrid", retrieve, raising=False)

        result = factory("question brute", "collection", 3)

        assert result == [_hybrid_hit()]
        assert captured == {
            "query": "question brute",
            "collection": "collection",
            "top_k": 3,
            "store": captured["store"],
            "embedder": embedder,
            "reranker": reranker,
            "pool_settings": settings,
            "connection": connection,
        }

    def test_search_sanitizes_failure_through_real_core_and_pg_store(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = _api_client(monkeypatch)
        monkeypatch.setattr(endpoint, "_check_retrievable", lambda *_args: {})
        executed_sql: list[str] = []

        class Cursor:
            def __enter__(self):
                return self

            def __exit__(self, *_args: object) -> None:
                return None

            def execute(self, sql: str, _params: object = None) -> None:
                executed_sql.append(sql)
                if "WITH hnsw_candidates AS MATERIALIZED" in sql:
                    raise RuntimeError(
                        "SENSITIVE_DSN_SENTINEL SENSITIVE_QUERY_SENTINEL"
                    )

        class Connection:
            def cursor(self) -> Cursor:
                return Cursor()

        class Embedder:
            def encode(self, _text: str, *, normalize_embeddings: bool):
                assert normalize_embeddings is True
                return (1.0,) + (0.0,) * 1023

        @contextmanager
        def connection_provider(_settings: object):
            yield Connection()

        monkeypatch.setattr(
            endpoint,
            "PoolSettings",
            SimpleNamespace(from_env=lambda: object()),
        )
        monkeypatch.setattr(endpoint, "pool_connection", connection_provider)
        monkeypatch.setattr(endpoint, "_get_embed_model", lambda: Embedder())
        monkeypatch.setattr(endpoint, "_get_reranker", lambda: object())

        response = client.post(
            "/search/v2",
            headers={"Authorization": "Bearer student-token"},
            json={
                "q": "requête extrêmement sensible",
                "collection": "rag_nexus_nsi_terminale_specialite",
                "k": 5,
            },
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "retrieval unavailable"}
        assert len(executed_sql) == 3
        assert "SELECT %s::vector IS NOT NULL" in executed_sql[0]
        assert executed_sql[1].strip() == (
            "SET LOCAL hnsw.iterative_scan = 'strict_order'"
        )
        assert "WITH hnsw_candidates AS MATERIALIZED" in executed_sql[2]
        assert executed_sql[2].count("FROM rag_chunks") == 1
        assert "ranked_pool.chunk_id ASC" in executed_sql[2]
        assert "SENSITIVE_DSN_SENTINEL" not in response.text
        assert "SENSITIVE_QUERY_SENTINEL" not in response.text
        assert "requête extrêmement sensible" not in response.text


class TestCitedChat:
    @pytest.mark.parametrize(
        ("hybrid_hits", "include_retrieval", "expected_retrieval_count"),
        [
            ([], True, 0),
            ([_hybrid_hit()], True, 1),
            ([_hybrid_hit()], False, 0),
        ],
    )
    def test_chat_is_hard_locked_after_successful_retrieval(
        self,
        hybrid_hits: list[object],
        include_retrieval: bool,
        expected_retrieval_count: int,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """No provider credential or evidence count can lift generation."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ingestor import retrieval_v2_endpoint as endpoint

        monkeypatch.setenv("RAG_STUDENT_TOKEN", "chat-test-token")
        monkeypatch.setenv("OPENROUTER_API_KEY", "configured-but-locked")
        monkeypatch.setattr(endpoint, "load_collection_config", lambda: FULL_CFG)
        retrieve = MagicMock(return_value=hybrid_hits)
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)
        monkeypatch.setattr(
            socket,
            "create_connection",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("network generation must remain locked")
            ),
        )
        app = FastAPI()
        app.include_router(endpoint.router)

        response = TestClient(app).post(
            "/chat",
            headers={"Authorization": "Bearer chat-test-token"},
            json={
                "student_profile": {
                    "niveau": "terminale",
                    "voie": "generale",
                    "matieres": ["nsi"],
                    "statut_enseignement": "specialite",
                    "candidat": "individuel",
                    "school_year": "2026-2027",
                    "zone": "france",
                },
                "query": "Explique la récursivité",
                "collections": ["rag_nexus_nsi_terminale_specialite"],
                "top_k": 4,
                "include_retrieval": include_retrieval,
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["grounded"] is False
        assert body["citations"] == []
        assert body["refusal_reason"] == "answer_generation_locked"
        assert body["warnings"] == ["answer_generation_locked"]
        assert len(body["retrieval_hits"]) == expected_retrieval_count
        retrieve.assert_called_once_with(
            "Explique la récursivité",
            "rag_nexus_nsi_terminale_specialite",
            4,
        )

    def test_chat_checks_every_collection_gate_before_any_retrieval(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from fastapi import FastAPI, HTTPException
        from fastapi.testclient import TestClient

        from ingestor import retrieval_v2_endpoint as endpoint

        monkeypatch.setenv("RAG_STUDENT_TOKEN", "chat-test-token")
        monkeypatch.setattr(endpoint, "load_collection_config", lambda: FULL_CFG)
        events: list[tuple[str, str]] = []

        def gate(collection: str, _cfg: dict) -> dict:
            events.append(("gate", collection))
            if collection == "rag_nexus_nsi_premiere_specialite":
                raise HTTPException(status_code=403, detail="closed")
            return {}

        def retrieve(_query: str, collection: str, _k: int) -> list[object]:
            events.append(("retrieve", collection))
            return []

        monkeypatch.setattr(endpoint, "_check_retrievable", gate)
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)
        app = FastAPI()
        app.include_router(endpoint.router)

        response = TestClient(app).post(
            "/chat",
            headers={"Authorization": "Bearer chat-test-token"},
            json={
                "student_profile": {
                    "niveau": "terminale",
                    "voie": "generale",
                    "matieres": ["nsi"],
                    "statut_enseignement": "specialite",
                    "candidat": "individuel",
                    "school_year": "2026-2027",
                    "zone": "france",
                },
                "query": "Explique",
                "collections": [
                    "rag_nexus_nsi_terminale_specialite",
                    "rag_nexus_nsi_premiere_specialite",
                ],
            },
        )

        assert response.status_code == 403
        assert events == [
            ("gate", "rag_nexus_nsi_terminale_specialite"),
            ("gate", "rag_nexus_nsi_premiere_specialite"),
        ]


class TestCacheGateInvariant:
    """Invariant C: cache never serves a chunk that became non-review.

    The gate (resolve_collection_v2 + domain retrievable) is checked BEFORE
    the cache lookup. The cache is keyed by (query, collection, k) and only
    stores results from retrievable collections. A quarantined collection
    always hits the gate FIRST and is refused with 403.

    Additionally, invalidate_cache() purges all entries on review_status
    change and advances a generation barrier before any warmup publication.
    """

    def test_gate_before_cache(self) -> None:
        """Quarantine is refused by the gate BEFORE cache is even checked."""
        import os

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ingestor import retrieval_v2_endpoint as endpoint

        os.environ.setdefault("RAG_STUDENT_TOKEN", "test-inv-c")

        test_app = FastAPI()
        test_app.include_router(endpoint.router)
        test_client = TestClient(test_app)
        h = {"Authorization": "Bearer test-inv-c"}

        # Even if we artificially stuff the cache with quarantine results,
        # the gate refuses BEFORE the cache is consulted.
        fake_key = endpoint._cache_key("test query", "rag_nexus_quarantine", 5)
        _seed_cache(endpoint, fake_key, [{"chunk_id": "fake"}])

        resp = test_client.post("/search/v2", json={
            "q": "test query", "collection": "rag_nexus_quarantine", "k": 5,
        }, headers=h)
        assert resp.status_code == 403, "Gate must refuse quarantine even with cache populated"

    def test_invalidation_purges_cache(self) -> None:
        """invalidate_cache() removes all entries."""
        from ingestor import retrieval_v2_endpoint as endpoint

        key = endpoint._cache_key("test", "test_col", 5)
        _seed_cache(endpoint, key, [{"test": "data"}])
        generation_before = endpoint._cache_generation

        endpoint.invalidate_cache()
        assert _cache_snapshot(endpoint) == {}
        assert endpoint._cache_generation == generation_before + 1

    def test_stats_describe_only_the_administrative_warmup_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = _api_client(monkeypatch)
        endpoint.invalidate_cache()
        key = endpoint._cache_key("stats", "col", 5)
        _seed_cache(endpoint, key, [{"test": "data"}])

        response = client.get(
            "/cache/v2/stats",
            headers={"Authorization": "Bearer student-token"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "enabled": endpoint.CACHE_ENABLED,
            "ttl_s": endpoint.CACHE_TTL_S,
            "entries": 1,
            "generation": endpoint._cache_generation,
            "public_serving": False,
        }

    def test_public_search_contains_no_direct_sql(self) -> None:
        """Public search contains no direct SQL and delegates after its gate."""
        import inspect

        from ingestor.retrieval_v2_endpoint import search_v2
        source = inspect.getsource(search_v2)
        assert "_retrieve_endpoint_hits" in source
        assert "psycopg" not in source
        assert "SELECT" not in source


class TestAtomicHybridWarmup:
    def _prepare(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ):
        endpoint, client = _api_client(monkeypatch)
        endpoint.invalidate_cache()
        monkeypatch.setattr(
            endpoint,
            "list_instanciated_collections",
            lambda _cfg: ["rag_nexus_nsi_terminale_specialite"],
        )
        return endpoint, client

    def test_warmup_stages_then_publishes_one_atomic_batch(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = self._prepare(monkeypatch)
        generation_before = endpoint._cache_generation
        retrieve = MagicMock(return_value=[_hybrid_hit()])
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve, raising=False)

        response = client.post(
            "/cache/v2/warmup",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "warmed": len(endpoint.WARMUP_QUERIES),
            "collections": 1,
            "queries": len(endpoint.WARMUP_QUERIES),
        }
        assert retrieve.call_args_list == [
            call(query, "rag_nexus_nsi_terminale_specialite", 5)
            for query in endpoint.WARMUP_QUERIES
        ]
        assert endpoint._cache_generation == generation_before
        with endpoint._cache_lock:
            assert len(endpoint._cache) == len(endpoint.WARMUP_QUERIES)
            timestamps = {timestamp for _, timestamp in endpoint._cache.values()}
            assert len(timestamps) == 1
            assert all(
                cached_hits == [endpoint._to_search_hit(_hybrid_hit()).model_dump()]
                for cached_hits, _timestamp in endpoint._cache.values()
            )

    @pytest.mark.parametrize(
        "stage",
        ["pool", "dense", "lexical", "embedding", "rerank", "mmr"],
    )
    def test_warmup_failure_keeps_prior_cache_bit_for_bit(
        self,
        stage: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = self._prepare(monkeypatch)
        prior_key = endpoint._cache_key("déjà valide", "collection-prior", 5)
        _seed_cache(endpoint, prior_key, [{"prior": ["unchanged"]}])
        before = _cache_snapshot(endpoint)
        attempts = 0

        def retrieve(*_args: object):
            nonlocal attempts
            attempts += 1
            if attempts == 2:
                raise RuntimeError(
                    f"{stage}: SENSITIVE_DSN_SENTINEL SENSITIVE_QUERY_SENTINEL"
                )
            return [_hybrid_hit()]

        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve, raising=False)

        response = client.post(
            "/cache/v2/warmup",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "retrieval unavailable"}
        assert "SENSITIVE_DSN_SENTINEL" not in response.text
        assert "SENSITIVE_QUERY_SENTINEL" not in response.text
        assert stage not in response.text
        assert attempts == 2
        assert _cache_snapshot(endpoint) == before

    def test_warmup_recomputes_and_replaces_every_target_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = self._prepare(monkeypatch)
        first_query = endpoint.WARMUP_QUERIES[0]
        key = endpoint._cache_key(
            first_query,
            "rag_nexus_nsi_terminale_specialite",
            5,
        )
        _seed_cache(endpoint, key, [{"existing": True}])
        retrieve = MagicMock(return_value=[])
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve, raising=False)

        response = client.post(
            "/cache/v2/warmup",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert response.status_code == 200
        assert call(
            first_query,
            "rag_nexus_nsi_terminale_specialite",
            5,
        ) in retrieve.call_args_list
        assert key not in _cache_snapshot(endpoint)

    def test_invalidation_during_warmup_prevents_stale_republication(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = self._prepare(monkeypatch)
        prior_key = endpoint._cache_key("prior", "prior-collection", 5)
        _seed_cache(endpoint, prior_key, [{"stale": True}])
        generation_before = endpoint._cache_generation
        started = threading.Event()
        release = threading.Event()
        responses: list[object] = []

        def retrieve(*_args: object):
            if not started.is_set():
                started.set()
                assert release.wait(timeout=5)
            return [_hybrid_hit()]

        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve, raising=False)

        worker = threading.Thread(
            target=lambda: responses.append(
                client.post(
                    "/cache/v2/warmup",
                    headers={"Authorization": "Bearer admin-token"},
                )
            )
        )
        worker.start()
        assert started.wait(timeout=5)
        assert endpoint.invalidate_cache() == 1
        assert endpoint._cache_generation == generation_before + 1
        release.set()
        worker.join(timeout=10)

        assert not worker.is_alive()
        assert len(responses) == 1
        assert responses[0].status_code == 503
        assert responses[0].json() == {"detail": "retrieval unavailable"}
        assert _cache_snapshot(endpoint) == {}

    def test_warmup_fails_closed_on_unresolvable_instantiated_collection(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = self._prepare(monkeypatch)
        prior_key = endpoint._cache_key("prior", "prior-collection", 5)
        _seed_cache(endpoint, prior_key, [{"unchanged": True}])
        before = _cache_snapshot(endpoint)
        monkeypatch.setattr(
            endpoint,
            "resolve_collection_v2",
            lambda *_args: (_ for _ in ()).throw(
                RuntimeError("SENSITIVE_CONFIG_SENTINEL")
            ),
        )
        retrieve = MagicMock()
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)

        response = client.post(
            "/cache/v2/warmup",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "retrieval unavailable"}
        assert "SENSITIVE_CONFIG_SENTINEL" not in response.text
        assert _cache_snapshot(endpoint) == before
        retrieve.assert_not_called()
