"""Tests for retrieval v2 FastAPI endpoint (FE-01).

Tests the gate behavior, response format, and collection listing
WITHOUT needing a live pgvector or model loading.
"""

from __future__ import annotations

import copy
import inspect
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from nexus_contracts import (
    RetrievalRequest,
    RetrievalResponse,
    RetrievalScopeArtifactV2,
    Rights,
    load_retrieval_scope_artifact,
)
from pydantic import ValidationError

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastapi import HTTPException

from ingestor.identity_v2 import VerifiedInternalIdentity
from ingestor.retrieval_scope_v2 import ServerRetrievalScope
from ingestor.retrieval_v2_endpoint import (
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
            "matiere": "nsi",
            "niveau": "terminale",
            "statut": "specialite",
            "domain": "education",
            "instanciee": True,
        },
        "rag_nexus_nsi_premiere_specialite": {
            "matiere": "nsi",
            "niveau": "premiere",
            "statut": "specialite",
            "domain": "education",
            "instanciee": True,
        },
        "rag_nexus_quarantine": {
            "matiere": None,
            "niveau": None,
            "statut": None,
            "domain": "quarantine",
            "instanciee": True,
        },
        "rag_nexus_maths_seconde_tc": {
            "matiere": "maths",
            "niveau": "seconde",
            "statut": "tronc_commun",
            "domain": "education",
            "instanciee": False,
        },
    },
    "domains": {
        "education": {"audiences": ["tous"], "retrievable": True},
        "quarantine": {"retrievable": False},
    },
}
BASE_SCOPE = ServerRetrievalScope(
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
    collection="rag_nexus_nsi_terminale_specialite",
    programme_version="BOEN_special_8_2019-07-25",
    scope_id="lot41_test_scope",
    scope_digest="a" * 64,
    source_sha256="b" * 64,
)


def _v2_gate_identity() -> VerifiedInternalIdentity:
    artifact = load_retrieval_scope_artifact("entree_seconde_maths_v1")
    assert isinstance(artifact, RetrievalScopeArtifactV2)
    return cast(VerifiedInternalIdentity, SimpleNamespace(artifact=artifact))


def _retrieval_payload(
    *,
    query: str = "arbre binaire",
    matiere: str = "nsi",
    k: int = 5,
) -> dict[str, object]:
    return {
        "student_profile": {
            "niveau": "terminale",
            "voie": "generale",
            "matieres": [matiere],
            "statut_enseignement": "specialite",
            "candidat": "individuel",
            "school_year": "2026-2027",
            "zone": "libre",
        },
        "need": {
            "intent": "context",
            "query": query,
        },
        "retrieval": {
            "k": k,
            "hybrid": True,
            "rerank": True,
            "include_citations": True,
        },
    }


def test_reviewed_chunk_counts_use_the_bounded_shared_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    settings = SimpleNamespace(timeout_s=5.0, statement_timeout_ms=3_000)
    executed: dict[str, object] = {}
    connection_calls = 0

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, sql: str, params: tuple[object, ...]) -> None:
            executed["sql"] = sql
            executed["params"] = params

        def fetchall(self) -> list[tuple[str, int]]:
            return [(BASE_SCOPE.collection, 12)]

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    @contextmanager
    def connection_provider(received_settings: object):
        nonlocal connection_calls
        connection_calls += 1
        executed["settings"] = received_settings
        yield Connection()

    monkeypatch.setattr(
        endpoint,
        "PoolSettings",
        SimpleNamespace(from_env=lambda: settings),
    )
    monkeypatch.setattr(endpoint, "pool_connection", connection_provider)
    endpoint.invalidate_cache()

    assert endpoint._get_reviewed_chunk_counts((BASE_SCOPE,)) == {
        BASE_SCOPE.collection: 12,
    }
    assert endpoint._get_reviewed_chunk_counts((BASE_SCOPE,)) == {
        BASE_SCOPE.collection: 12,
    }
    assert connection_calls == 1
    assert executed["settings"] is settings
    assert "SELECT %s::text AS collection, COUNT(*)" in str(executed["sql"])
    assert "FROM public.rag_chunks AS chunk" in str(executed["sql"])
    assert "public.rag_artifact_placements" in str(executed["sql"])
    assert BASE_SCOPE.tenant in executed["params"]


def _install_blocking_reviewed_counts_db(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[object, Event, Event, dict[str, int]]:
    from ingestor import retrieval_v2_endpoint as endpoint

    settings = SimpleNamespace(
        timeout_s=0.01,
        connect_timeout_s=1,
        statement_timeout_ms=1_000,
    )
    query_started = Event()
    release_query = Event()
    state = {"connection_calls": 0}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def execute(self, _sql: str, _params: tuple[object, ...]) -> None:
            query_started.set()
            assert release_query.wait(timeout=2.0)

        def fetchall(self) -> list[tuple[str, int]]:
            return [(BASE_SCOPE.collection, 12)]

    class Connection:
        def cursor(self) -> Cursor:
            return Cursor()

    @contextmanager
    def connection_provider(_received_settings: object):
        state["connection_calls"] += 1
        yield Connection()

    monkeypatch.setattr(
        endpoint,
        "PoolSettings",
        SimpleNamespace(from_env=lambda: settings),
    )
    monkeypatch.setattr(endpoint, "pool_connection", connection_provider)
    endpoint.invalidate_cache()
    return endpoint, query_started, release_query, state


def test_reviewed_chunk_counts_coalesce_concurrent_identical_queries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deux probes identiques partagent le même résultat SQL en cours."""
    endpoint, query_started, release_query, state = (
        _install_blocking_reviewed_counts_db(monkeypatch)
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(endpoint._get_reviewed_chunk_counts, (BASE_SCOPE,))
        assert query_started.wait(timeout=1.0)
        second = executor.submit(endpoint._get_reviewed_chunk_counts, (BASE_SCOPE,))
        time.sleep(0.05)
        release_query.set()

        expected = {BASE_SCOPE.collection: 12}
        assert first.result(timeout=1.0) == expected
        assert second.result(timeout=1.0) == expected

    assert state["connection_calls"] == 1


def test_reviewed_chunk_counts_fail_closed_when_review_invalidates_inflight_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Une décision de review interdit de publier ou partager le snapshot ancien."""
    endpoint, query_started, release_query, state = (
        _install_blocking_reviewed_counts_db(monkeypatch)
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(endpoint._get_reviewed_chunk_counts, (BASE_SCOPE,))
        assert query_started.wait(timeout=1.0)
        second = executor.submit(endpoint._get_reviewed_chunk_counts, (BASE_SCOPE,))
        endpoint.invalidate_cache()
        release_query.set()

        for future in (first, second):
            with pytest.raises(HTTPException) as exc_info:
                future.result(timeout=1.0)
            assert exc_info.value.status_code == 503

    assert endpoint._get_reviewed_chunk_counts((BASE_SCOPE,)) == {
        BASE_SCOPE.collection: 12,
    }
    assert state["connection_calls"] == 2


def test_cold_model_loads_reuse_startup_paths_and_are_serialized(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    embedding_root = (tmp_path / "embedding").resolve()
    reranker_root = (tmp_path / "reranker").resolve()
    embedding_root.mkdir()
    reranker_root.mkdir()
    calls: list[tuple[str, Path | None]] = []
    embedding_model = object()
    reranker_model = object()

    def load_embedding_model(*, verified_artifact_root: Path | None = None) -> object:
        calls.append(("embedding", verified_artifact_root))
        time.sleep(0.01)
        return embedding_model

    def load_reranker_model(*, verified_artifact_root: Path | None = None) -> object:
        calls.append(("reranker", verified_artifact_root))
        time.sleep(0.01)
        return reranker_model

    monkeypatch.setattr(endpoint, "load_embedding_model", load_embedding_model)
    monkeypatch.setattr(endpoint, "load_reranker_model", load_reranker_model)
    endpoint.reset_runtime_model_state()
    endpoint.configure_verified_model_artifacts(
        embedding_root=embedding_root,
        reranker_root=reranker_root,
    )
    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            embeddings = list(executor.map(lambda _index: endpoint._get_embed_model(), range(8)))
            rerankers = list(executor.map(lambda _index: endpoint._get_reranker(), range(8)))
    finally:
        endpoint.reset_runtime_model_state()

    assert embeddings == [embedding_model] * 8
    assert rerankers == [reranker_model] * 8
    assert calls == [
        ("embedding", embedding_root),
        ("reranker", reranker_root),
    ]


def test_preload_runtime_models_rejects_wrong_embedding_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint
    from ingestor.embedding_contract import EmbeddingContractError

    embedder = SimpleNamespace(get_sentence_embedding_dimension=lambda: 768)
    reranker_loaded = False

    def load_reranker() -> object:
        nonlocal reranker_loaded
        reranker_loaded = True
        return object()

    monkeypatch.setattr(endpoint, "_get_embed_model", lambda: embedder)
    monkeypatch.setattr(endpoint, "_get_reranker", load_reranker)

    with pytest.raises(EmbeddingContractError, match="EMBEDDING_RUNTIME_DIMENSION_MISMATCH"):
        endpoint.preload_runtime_models()

    assert reranker_loaded is False


def _mock_retrieval_identity(endpoint: object, monkeypatch: pytest.MonkeyPatch) -> None:
    verified = SimpleNamespace(
        artifact=SimpleNamespace(
            subjects=(
                SimpleNamespace(
                    matiere="nsi",
                    collection="rag_nexus_nsi_terminale_specialite",
                ),
            ),
        ),
    )
    monkeypatch.setattr(
        endpoint,
        "_require_retrieval_identity",
        lambda _request, *, endpoint, payload=None: verified,
    )
    monkeypatch.setattr(
        endpoint,
        "effective_signed_collections",
        lambda _verified: ("rag_nexus_nsi_terminale_specialite",),
    )
    monkeypatch.setattr(
        endpoint,
        "build_server_retrieval_scope",
        lambda _verified, *, collection, collection_config: replace(
            BASE_SCOPE,
            collection=collection,
            matiere=collection_config["collections"][collection].get("matiere") or "nsi",
        ),
    )


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
    _mock_retrieval_identity(endpoint, monkeypatch)
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
        nsi_tle = next(
            c for c in result["collections"] if c["name"] == "rag_nexus_nsi_terminale_specialite"
        )
        assert nsi_tle["matiere"] == "nsi"
        assert nsi_tle["niveau"] == "terminale"
        assert nsi_tle["statut"] == "specialite"
        assert nsi_tle["domain"] == "education"

    def test_signed_picker_preserves_artifact_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ingestor import retrieval_v2_endpoint as endpoint

        allowed = (
            "rag_nexus_nsi_terminale_specialite",
            "rag_nexus_nsi_premiere_specialite",
        )
        monkeypatch.setattr(
            endpoint, "_require_retrieval_identity", lambda *_args, **_kwargs: object()
        )
        monkeypatch.setattr(endpoint, "load_collection_config", lambda: FULL_CFG)
        monkeypatch.setattr(endpoint, "effective_signed_collections", lambda _verified: allowed)
        monkeypatch.setattr(
            endpoint, "build_server_retrieval_scope", lambda *_args, **_kwargs: BASE_SCOPE
        )

        result = endpoint.list_retrievable_collections(SimpleNamespace())

        assert [item["name"] for item in result["collections"]] == list(allowed)


class TestSearchV2Request:
    """La frontière HTTP utilise le contrat Nexus partagé."""

    def test_route_uses_versioned_retrieval_contract(self) -> None:
        from ingestor import retrieval_v2_endpoint as endpoint

        route = next(route for route in endpoint.router.routes if route.path == "/search/v2")

        assert route.body_field is not None
        assert route.body_field.field_info.annotation is RetrievalRequest
        assert route.response_model is RetrievalResponse

    def test_valid_request(self) -> None:
        req = RetrievalRequest.model_validate(_retrieval_payload())
        assert req.need.query == "arbre binaire"
        assert req.retrieval.k == 5

    def test_empty_query_rejected(self) -> None:
        with pytest.raises(ValueError):
            RetrievalRequest.model_validate(_retrieval_payload(query=""))

    def test_k_bounds(self) -> None:
        with pytest.raises(ValueError):
            RetrievalRequest.model_validate(_retrieval_payload(k=0))
        with pytest.raises(ValueError):
            RetrievalRequest.model_validate(_retrieval_payload(k=51))


class TestResponseFormat:
    """Vérifier la réponse contractuelle et les diagnostics internes."""

    def test_retrieval_response_contains_no_generated_answer(self) -> None:
        resp = RetrievalResponse(results=[], warnings=[], filters_applied={})
        assert "answer" not in resp.model_dump()

    def test_hit_exposes_review_status(self) -> None:
        """SCALE-04: review_status in each hit for agent layer."""
        from ingestor.retrieval_v2_endpoint import SearchV2Hit

        hit = SearchV2Hit(
            chunk_id="c1",
            doc_id="d1",
            source_label="s.pdf",
            source_uri="u",
            rights="usage_interne",
            type_doc="cours",
            review_status="reviewed",
            page=7,
            preview="text",
            dense_score=0.85,
            lexical_score=None,
            rrf_score=0.01,
            rerank_score=5.0,
            mmr_score=0.6,
            score_final=0.9,
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

        no_dense_hit = SearchV2Hit(**{**hit.model_dump(exclude={"dense_sim"}), "dense_score": None})
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
        assert "validateRetrievalResponse(result.payload)" in cockpit_route
        assert "hit.dense_sim" not in cockpit_route

        with pytest.raises(ValidationError):
            SearchV2Hit(
                chunk_id="c2",
                doc_id="d2",
                source_label="s2.pdf",
                source_uri="u2",
                rights="usage_interne",
                type_doc="cours",
                review_status="needs_review",
                page=None,
                preview="text",
                dense_score=None,
                lexical_score=0.7,
                rrf_score=0.01,
                rerank_score=3.0,
                mmr_score=0.5,
                score_final=0.8,
            )

    def test_mapping_hybrid_hit_to_contract_preserves_provenance_and_scores(self) -> None:
        from ingestor.retrieval_hybrid_v2 import HybridHit, RetrievalCandidate
        from ingestor.retrieval_v2_endpoint import _to_retrieval_result, _to_search_hit

        candidate = RetrievalCandidate(
            chunk_id="chunk-1",
            doc_id="a" * 64,
            source_label="Programme NSI",
            source_uri="https://example.edu/nsi",
            rights="official_public_administrative",
            type_doc="programme",
            text="  Une ressource validée et substantielle.  ",
            page_start=11,
            vector=(1.0,) + (0.0,) * 1023,
            review_status="reviewed",
            artifact_id="a" * 64,
            content_sha256="a" * 64,
            placement_id="b" * 64,
            placement_source_scope="01_EDUSCOL_OFFICIEL/terminale/philosophie",
            placement_source_id="eduscol:5793:terminale:philosophie",
            placement_source_path="01_EDUSCOL_OFFICIEL/philosophie/source.pdf",
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
            "dense_sim": None,
            "lexical_score": 0.42,
            "rrf_score": 0.004918,
            "rerank_score": 2.75,
            "mmr_score": 0.612,
            "score_final": 0.884,
            "artifact_id": "a" * 64,
            "content_sha256": "a" * 64,
            "placement_id": "b" * 64,
            "placement_source_scope": (
                "01_EDUSCOL_OFFICIEL/terminale/philosophie"
            ),
            "placement_source_id": "eduscol:5793:terminale:philosophie",
            "placement_source_path": (
                "01_EDUSCOL_OFFICIEL/philosophie/source.pdf"
            ),
        }

    def test_mapping_hybrid_hit_builds_a_query_relevant_short_preview(self) -> None:
        from ingestor.retrieval_hybrid_v2 import HybridHit, RetrievalCandidate
        from ingestor.retrieval_v2_endpoint import _to_search_hit

        candidate = RetrievalCandidate(
            chunk_id="chunk-query-preview",
            doc_id="a" * 64,
            source_label="Attendus de mathématiques",
            source_uri="https://example.edu/maths",
            rights="officiel_public",
            type_doc="attendus",
            text=(
                "Introduction générale sans le concept recherché. " * 8
                + "Calculer avec des fractions et des nombres relatifs."
            ),
            page_start=5,
            vector=(1.0,) + (0.0,) * 1023,
            review_status="reviewed",
            dense_score=0.8,
            lexical_score=None,
        )
        hybrid_hit = HybridHit(
            candidate=candidate,
            dense_rank=1,
            lexical_rank=None,
            rrf_score=0.01,
            rerank_score=3.2,
            mmr_score=0.7,
            score_final=0.9,
        )

        hit = _to_search_hit(
            hybrid_hit,
            query="Comment calculer des fractions avec des nombres relatifs ?",
        )

        assert len(hit.preview) <= 200
        assert "fractions" in hit.preview
        assert "nombres relatifs" in hit.preview

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
            assert (field_name,) in {tuple(error["loc"]) for error in exc_info.value.errors()}

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
        assert "response_model=RetrievalResponse" in inspect.getsource(endpoint)


class TestLaunchReadiness:
    """Le compteur de chunks ne peut jamais tenir lieu de preuve de substance."""

    def test_reviewed_chunk_floor_cannot_self_authorize_launch(self) -> None:
        readiness = _build_launch_readiness(
            FULL_CFG,
            {
                "rag_nexus_nsi_terminale_specialite": 3,
                "rag_nexus_nsi_premiere_specialite": 3,
                "rag_nexus_quarantine": 3,
                "rag_nexus_maths_seconde_tc": 0,
            },
            min_chunks=3,
            release_evidence_verified=False,
        )

        assert readiness["total_collections"] == 4
        assert readiness["launch_ready"] is False
        assert readiness["ready_collections"] == 0
        assert readiness["release_evidence_verified"] is False
        assert "preuve exhaustive de release absente" in readiness["blockers"]
        maths = next(
            item
            for item in readiness["collections"]
            if item["name"] == "rag_nexus_maths_seconde_tc"
        )
        assert maths["ready"] is False
        assert "collection non instanciée" in maths["reasons"]

    def test_readiness_is_limited_to_signed_collections(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ingestor import retrieval_v2_endpoint as endpoint

        verified = SimpleNamespace(
            envelope=SimpleNamespace(
                allowed_collections=("rag_nexus_nsi_terminale_specialite",),
            ),
        )
        events: list[object] = []
        monkeypatch.setattr(
            endpoint,
            "_require_retrieval_identity",
            lambda *_args, **_kwargs: events.append("identity") or verified,
        )
        monkeypatch.setattr(
            endpoint,
            "load_collection_config",
            lambda: events.append("config") or FULL_CFG,
        )
        monkeypatch.setattr(
            endpoint,
            "build_server_readiness_scope",
            lambda *_args, **_kwargs: BASE_SCOPE,
        )
        monkeypatch.setattr(
            endpoint,
            "effective_signed_collections",
            lambda _verified: (BASE_SCOPE.collection,),
        )

        def counts(scopes: object) -> dict[str, int]:
            resolved = tuple(scopes)
            events.append(("counts", resolved))
            assert resolved == (BASE_SCOPE,)
            return {BASE_SCOPE.collection: 12_000}

        monkeypatch.setattr(endpoint, "_get_reviewed_chunk_counts", counts)

        response = endpoint.get_collection_readiness(SimpleNamespace())

        assert response["total_collections"] == 1
        assert response["collections"][0]["name"] == BASE_SCOPE.collection
        assert response["launch_ready"] is False
        assert events[0:2] == ["identity", "config"]

    def test_readiness_preserves_artifact_order(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ingestor import retrieval_v2_endpoint as endpoint

        allowed = (
            "rag_nexus_nsi_terminale_specialite",
            "rag_nexus_maths_seconde_tc",
        )
        monkeypatch.setattr(
            endpoint, "_require_retrieval_identity", lambda *_args, **_kwargs: object()
        )
        monkeypatch.setattr(endpoint, "load_collection_config", lambda: FULL_CFG)
        monkeypatch.setattr(endpoint, "effective_signed_collections", lambda _verified: allowed)
        monkeypatch.setattr(
            endpoint,
            "build_server_readiness_scope",
            lambda _verified, *, collection, collection_config: replace(
                BASE_SCOPE,
                collection=collection,
                matiere=collection_config["collections"][collection]["matiere"],
            ),
        )
        monkeypatch.setattr(endpoint, "_get_reviewed_chunk_counts", lambda _scopes: {})

        response = endpoint.get_collection_readiness(SimpleNamespace())

        assert [item["name"] for item in response["collections"]] == list(allowed)

    def test_readiness_uses_exact_release_evidence_for_wave0(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from ingestor import retrieval_v2_endpoint as endpoint

        monkeypatch.setattr(
            endpoint, "_require_retrieval_identity", lambda *_args, **_kwargs: object()
        )
        monkeypatch.setattr(endpoint, "load_collection_config", lambda: FULL_CFG)
        monkeypatch.setattr(
            endpoint,
            "effective_signed_collections",
            lambda _verified: (BASE_SCOPE.collection,),
        )
        monkeypatch.setattr(
            endpoint,
            "build_server_readiness_scope",
            lambda *_args, **_kwargs: BASE_SCOPE,
        )
        monkeypatch.setattr(
            endpoint,
            "_get_reviewed_chunk_counts",
            lambda _scopes: {BASE_SCOPE.collection: 12_000},
        )
        monkeypatch.setattr(
            endpoint,
            "_release_evidence_for_collection",
            lambda collection: True if collection == BASE_SCOPE.collection else None,
        )

        response = endpoint.get_collection_readiness(SimpleNamespace())

        assert response["release_evidence_verified"] is True
        assert response["launch_ready"] is True

    def test_readiness_reports_release_evidence_per_collection(self) -> None:
        cfg = copy.deepcopy(FULL_CFG)
        collections = (
            "rag_nexus_nsi_terminale_specialite",
            "rag_nexus_nsi_premiere_specialite",
        )
        cfg["collections"] = {
            collection: cfg["collections"][collection] for collection in collections
        }

        readiness = _build_launch_readiness(
            cfg,
            {collection: 3 for collection in collections},
            min_chunks=3,
            release_evidence_verified={
                collections[0]: True,
                collections[1]: False,
            },
        )

        by_name = {item["name"]: item for item in readiness["collections"]}
        assert readiness["launch_ready"] is False
        assert readiness["release_evidence_verified"] is False
        assert readiness["ready_collections"] == 1
        assert by_name[collections[0]]["ready"] is True
        assert by_name[collections[1]]["ready"] is False
        assert "preuve exhaustive de release absente" in by_name[collections[1]]["reasons"]


def test_retrievable_gate_blocks_only_a_governed_unready_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    events: list[str] = []
    monkeypatch.setattr(
        endpoint,
        "_release_evidence_for_collection",
        lambda collection: events.append(collection) or False,
    )

    cfg = copy.deepcopy(FULL_CFG)
    collection = "rag_nexus_maths_troisieme_tc"
    cfg["collections"][collection] = {
        "matiere": "maths",
        "niveau": "troisieme",
        "statut": "tronc_commun",
        "domain": "education",
        "instanciee": True,
    }

    with pytest.raises(HTTPException) as exc_info:
        endpoint._check_retrievable(
            collection,
            cfg,
            verified=_v2_gate_identity(),
        )

    assert exc_info.value.status_code == 503
    assert events == [collection]


def test_instanciated_v2_collection_without_manifest_is_not_retrievable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    cfg = copy.deepcopy(FULL_CFG)
    collection = "rag_nexus_maths_troisieme_tc"
    cfg["collections"][collection] = {
        "matiere": "maths",
        "niveau": "troisieme",
        "statut": "tronc_commun",
        "domain": "education",
        "instanciee": True,
    }
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_PATH", raising=False)
    monkeypatch.delenv("RAG_RELEASE_MANIFEST_SHA256", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        endpoint._check_retrievable(
            collection,
            cfg,
            verified=_v2_gate_identity(),
        )

    assert exc_info.value.status_code == 503


def test_picker_keeps_historical_collection_and_hides_governed_unready_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from ingestor import retrieval_v2_endpoint as endpoint

    allowed = (
        "rag_nexus_nsi_terminale_specialite",
        "rag_nexus_nsi_premiere_specialite",
    )
    monkeypatch.setattr(
        endpoint, "_require_retrieval_identity", lambda *_args, **_kwargs: object()
    )
    monkeypatch.setattr(endpoint, "load_collection_config", lambda: FULL_CFG)
    monkeypatch.setattr(endpoint, "effective_signed_collections", lambda _verified: allowed)
    monkeypatch.setattr(endpoint, "build_server_retrieval_scope", lambda *_args, **_kwargs: BASE_SCOPE)
    monkeypatch.setattr(
        endpoint,
        "_release_evidence_for_collection",
        lambda collection: (
            False if collection == "rag_nexus_nsi_premiere_specialite" else None
        ),
    )

    response = endpoint.list_retrievable_collections(SimpleNamespace())

    assert [item["name"] for item in response["collections"]] == [
        "rag_nexus_nsi_terminale_specialite"
    ]


class TestHybridSearchDelegation:
    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("notions", ["récursivité"]),
            ("desired_doc_types", ["cours"]),
            ("difficulty_max", 3),
        ],
    )
    def test_search_rejects_unsupported_need_filters_before_retrieval(
        self,
        field: str,
        value: object,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = _api_client(monkeypatch)
        monkeypatch.setattr(endpoint, "_check_retrievable", lambda *_args: {})
        retrieve = MagicMock(return_value=[_hybrid_hit()])
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve, raising=False)
        payload = _retrieval_payload()
        need = payload["need"]
        assert isinstance(need, dict)
        need[field] = value

        response = client.post(
            "/search/v2",
            headers={"Authorization": "Bearer student-token"},
            json=payload,
        )

        assert response.status_code == 422
        assert response.json() == {"detail": "Unsupported retrieval filters"}
        retrieve.assert_not_called()

    def test_search_delegates_raw_parameters_after_gate_and_ignores_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = _api_client(monkeypatch)
        events: list[object] = []

        def check(collection: str, _cfg: dict, _verified: object) -> dict:
            events.append(("gate", collection))
            return {"domain": "education"}

        def retrieve(
            query: str,
            collection: str,
            top_k: int,
            scope: ServerRetrievalScope,
        ):
            assert scope.collection == collection
            events.append(("retrieve", query, collection, top_k))
            return [_hybrid_hit()]

        monkeypatch.setattr(endpoint, "_check_retrievable", check)
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve, raising=False)
        assert "_cache" not in inspect.getsource(endpoint.search_v2)
        assert not hasattr(endpoint, "psycopg")

        response = client.post(
            "/search/v2",
            headers={"Authorization": "Bearer student-token"},
            json=_retrieval_payload(query="  requête brute ?  ", k=4),
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
        body = response.json()
        assert [item["chunk_id"] for item in body["results"]] == ["chunk-1"]
        assert body["results"][0]["citation"]["source_label"] == "Programme NSI"
        assert body["filters_applied"]["collection"] == (
            "rag_nexus_nsi_terminale_specialite"
        )

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
            json=_retrieval_payload(query="aucun résultat", k=5),
        )

        assert response.status_code == 200
        assert response.json()["results"] == []

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
            raise RuntimeError(f"{stage}: SENSITIVE_DSN_SENTINEL SENSITIVE_QUERY_SENTINEL")

        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", fail, raising=False)
        response = client.post(
            "/search/v2",
            headers={"Authorization": "Bearer student-token"},
            json=_retrieval_payload(query="texte très secret", k=5),
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

        settings = SimpleNamespace(
            database_budget_ms=6_000,
            statement_timeout_ms=3_000,
        )
        connection = object()
        embedder = object()
        reranker = object()
        captured: dict[str, object] = {}

        @contextmanager
        def connection_provider(received_settings: object):
            captured["pool_settings"] = received_settings
            yield connection

        class Store:
            def __init__(self, provider, scope, *, statement_timeout_ms) -> None:
                self.provider = provider
                self.scope = scope
                self.statement_timeout_ms = statement_timeout_ms

        def retrieve(query, collection, top_k, *, store, embedder, reranker):
            captured.update(
                {
                    "query": query,
                    "collection": collection,
                    "top_k": top_k,
                    "store": store,
                    "embedder": embedder,
                    "reranker": reranker,
                }
            )
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

        result = factory("question brute", "collection", 3, BASE_SCOPE)

        assert result == [_hybrid_hit()]
        bounded_embedder = captured.pop("embedder")
        bounded_reranker = captured.pop("reranker")
        assert isinstance(bounded_embedder, endpoint.BoundedInferenceEmbedder)
        assert isinstance(bounded_reranker, endpoint.BoundedInferenceReranker)
        assert bounded_embedder._model is embedder
        assert bounded_reranker._model is reranker
        assert captured == {
            "query": "question brute",
            "collection": "collection",
            "top_k": 3,
            "store": captured["store"],
            "pool_settings": settings,
            "connection": connection,
        }
        assert captured["store"].statement_timeout_ms == 3_000

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
                    raise RuntimeError("SENSITIVE_DSN_SENTINEL SENSITIVE_QUERY_SENTINEL")

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
            SimpleNamespace(
                from_env=lambda: SimpleNamespace(
                    database_budget_ms=6_000,
                    statement_timeout_ms=3_000,
                )
            ),
        )
        monkeypatch.setattr(endpoint, "pool_connection", connection_provider)
        monkeypatch.setattr(endpoint, "_get_embed_model", lambda: Embedder())
        monkeypatch.setattr(endpoint, "_get_reranker", lambda: object())

        response = client.post(
            "/search/v2",
            headers={"Authorization": "Bearer student-token"},
            json=_retrieval_payload(query="requête extrêmement sensible", k=5),
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "retrieval unavailable"}
        assert len(executed_sql) == 6
        assert executed_sql[0::2] == [
            "SELECT set_config('statement_timeout', %s, true)",
        ] * 3
        assert "SELECT %s::vector IS NOT NULL" in executed_sql[1]
        assert executed_sql[3].strip() == ("SET LOCAL hnsw.iterative_scan = 'strict_order'")
        assert "WITH hnsw_candidates AS MATERIALIZED" in executed_sql[5]
        assert executed_sql[5].count("FROM public.rag_chunks") == 1
        assert "FROM rag_chunks" not in executed_sql[5]
        assert "ranked_pool.chunk_id ASC" in executed_sql[5]
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
        _mock_retrieval_identity(endpoint, monkeypatch)
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
                    "zone": "libre",
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
            BASE_SCOPE,
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
        _mock_retrieval_identity(endpoint, monkeypatch)
        events: list[tuple[str, str]] = []

        def gate(collection: str, _cfg: dict, _verified: object) -> dict:
            events.append(("gate", collection))
            if collection == "rag_nexus_nsi_premiere_specialite":
                raise HTTPException(status_code=403, detail="closed")
            return {}

        def retrieve(
            _query: str,
            collection: str,
            _k: int,
            _scope: ServerRetrievalScope,
        ) -> list[object]:
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

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("niveau", "premiere"),
            ("voie", "technologique"),
            ("matieres", ["maths"]),
            ("statut_enseignement", "tronc_commun"),
            ("candidat", "libre"),
            ("school_year", "2025-2026"),
            ("zone", "aefe"),
        ],
    )
    def test_chat_refuses_every_unsigned_profile_divergence_before_retrieval(
        self,
        monkeypatch: pytest.MonkeyPatch,
        field: str,
        value: object,
    ) -> None:
        endpoint, client = _api_client(monkeypatch)
        retrieve = MagicMock(side_effect=AssertionError("retrieval must stay closed"))
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)
        profile: dict[str, object] = {
            "niveau": "terminale",
            "voie": "generale",
            "matieres": ["nsi"],
            "statut_enseignement": "specialite",
            "candidat": "individuel",
            "school_year": "2026-2027",
            "zone": "libre",
        }
        profile[field] = value

        response = client.post(
            "/chat",
            headers={"Authorization": "Bearer student-token"},
            json={
                "student_profile": profile,
                "query": "Explique la récursivité",
                "collections": ["rag_nexus_nsi_terminale_specialite"],
                "top_k": 4,
                "include_retrieval": True,
            },
        )

        assert response.status_code == 403
        assert response.json() == {"detail": "Forbidden"}
        retrieve.assert_not_called()


class TestCacheGateInvariant:
    """Invariant C: cache never serves a chunk that became non-review.

    The gate (resolve_collection_v2 + domain retrievable) is checked BEFORE
    the cache lookup. The cache is keyed by (query, collection, k) and only
    stores results from retrievable collections. A quarantined collection
    always hits the gate FIRST and is refused with 403.

    Additionally, invalidate_cache() purges all entries on review_status
    change and advances a generation barrier before any warmup publication.
    """

    def test_legacy_search_payload_is_rejected_before_cache(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """L'ancien DTO local ne traverse plus la frontière contractuelle."""
        import os

        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from ingestor import retrieval_v2_endpoint as endpoint

        _mock_retrieval_identity(endpoint, monkeypatch)

        os.environ.setdefault("RAG_STUDENT_TOKEN", "test-inv-c")

        test_app = FastAPI()
        test_app.include_router(endpoint.router)
        test_client = TestClient(test_app)
        h = {"Authorization": "Bearer test-inv-c"}

        # Even if we artificially stuff the cache with quarantine results,
        # the gate refuses BEFORE the cache is consulted.
        fake_key = endpoint._cache_key("test query", "rag_nexus_quarantine", 5)
        _seed_cache(endpoint, fake_key, [{"chunk_id": "fake"}])

        resp = test_client.post(
            "/search/v2",
            json={
                "q": "test query",
                "collection": "rag_nexus_quarantine",
                "k": 5,
            },
            headers=h,
        )
        assert resp.status_code == 422

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

    def test_warmup_docstring_explains_the_disabled_cache_invariant(self) -> None:
        from ingestor import retrieval_v2_endpoint as endpoint

        assert endpoint.cache_warmup.__doc__ is not None
        normalized = " ".join(endpoint.cache_warmup.__doc__.split()).lower()
        assert "après authentification" in normalized
        assert "purge atomiquement" in normalized
        assert "avance la génération" in normalized
        assert "compteurs à zéro" in normalized
        assert "sans charger la configuration ni lancer le pipeline" in normalized

    def test_disabled_warmup_without_auth_preserves_cache_and_generation(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = self._prepare(monkeypatch)
        prior_key = endpoint._cache_key("prior", "prior-collection", 5)
        _seed_cache(endpoint, prior_key, [{"stale": True}])
        cache_before = _cache_snapshot(endpoint)
        generation_before = endpoint._cache_generation
        load_config = MagicMock(
            side_effect=AssertionError("unauthorized warmup must not load config")
        )
        retrieve = MagicMock(side_effect=AssertionError("unauthorized warmup must not retrieve"))
        monkeypatch.setattr(endpoint, "CACHE_ENABLED", False)
        monkeypatch.setattr(endpoint, "load_collection_config", load_config)
        monkeypatch.setattr(endpoint, "_retrieve_endpoint_hits", retrieve)

        response = client.post("/cache/v2/warmup")

        assert response.status_code == 401
        assert _cache_snapshot(endpoint) == cache_before
        assert endpoint._cache_generation == generation_before
        load_config.assert_not_called()
        retrieve.assert_not_called()

    def test_disabled_warmup_purges_without_loading_config_or_retrieval(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = self._prepare(monkeypatch)
        prior_key = endpoint._cache_key("prior", "prior-collection", 5)
        _seed_cache(endpoint, prior_key, [{"stale": True}])
        generation_before = endpoint._cache_generation
        load_config = MagicMock(
            side_effect=AssertionError("config must stay unloaded when cache is disabled")
        )
        retrieve = MagicMock(
            side_effect=AssertionError("retrieval must stay idle when cache is disabled")
        )
        monkeypatch.setattr(endpoint, "CACHE_ENABLED", False)
        monkeypatch.setattr(endpoint, "load_collection_config", load_config)
        monkeypatch.setattr(endpoint, "_retrieve_endpoint_hits", retrieve)

        response = client.post(
            "/cache/v2/warmup",
            headers={"Authorization": "Bearer admin-token"},
        )
        stats = client.get(
            "/cache/v2/stats",
            headers={"Authorization": "Bearer student-token"},
        )

        assert response.status_code == 200
        assert response.json() == {
            "warmed": 0,
            "collections": 0,
            "queries": 0,
        }
        assert _cache_snapshot(endpoint) == {}
        assert endpoint._cache_generation == generation_before + 1
        assert stats.status_code == 200
        assert stats.json() == {
            "enabled": False,
            "ttl_s": endpoint.CACHE_TTL_S,
            "entries": 0,
            "generation": generation_before + 1,
            "public_serving": False,
        }
        load_config.assert_not_called()
        retrieve.assert_not_called()

    def test_warmup_cannot_be_reenabled_into_an_unscoped_retrieval(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        endpoint, client = self._prepare(monkeypatch)
        retrieve = MagicMock(side_effect=AssertionError("unscoped warmup must never retrieve"))
        monkeypatch.setattr(endpoint, "CACHE_ENABLED", True)
        monkeypatch.setattr(endpoint, "_retrieve_hybrid_hits", retrieve)

        response = client.post(
            "/cache/v2/warmup",
            headers={"Authorization": "Bearer admin-token"},
        )

        assert response.status_code == 503
        assert response.json() == {"detail": "retrieval unavailable"}
        retrieve.assert_not_called()
