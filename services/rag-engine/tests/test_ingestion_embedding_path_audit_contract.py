"""Audit contracts for active v2 and legacy ingestion embedding paths.

These static tests do not execute an ingestion. They keep the routed
``/ingest/v2`` path separate from the legacy Celery/Ollama worker debt.
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "services" / "rag-engine" / "src" / "ingestor"


class TestActiveRoutedIngestV2Path:
    """Document the certified embedding behavior of routed ``/ingest/v2``."""

    def test_api_routes_ingest_v2_to_ingest_document(self) -> None:
        """api.py mounts the v2 router whose implemented routes call ingest_document."""
        api_content = (SRC / "api.py").read_text()
        endpoint_content = (SRC / "ingest_v2_endpoint.py").read_text()

        assert "app.include_router(_ingest_v2_module.router)" in api_content
        assert 'APIRouter(prefix="/ingest/v2"' in endpoint_content
        assert "ingest_document(" in endpoint_content

    def test_active_ingest_v2_applies_passage_embedding_contract(self) -> None:
        """The pgvector write path formats and normalizes passage embeddings."""
        content = (SRC / "ingest_v2.py").read_text()

        assert "format_passage" in content
        assert "encode(" in content
        assert "normalize_embeddings=True" in content
        assert "validate_runtime_embedding_contract" in content

    def test_retrieval_v2_uses_load_embedding_model(self) -> None:
        """retrieval_v2_endpoint.py uses the same local contract model loader."""
        content = (SRC / "retrieval_v2_endpoint.py").read_text()

        assert "load_embedding_model()" in content


class TestLegacyWorkerDebt:
    """Keep the remaining Celery/Ollama embedding path visible as legacy debt."""

    def test_legacy_worker_ollama_path_still_active(self) -> None:
        """The registered Celery worker still delegates embeddings to Ollama."""
        tasks_content = (SRC / "tasks.py").read_text()
        service_content = (SRC / "embedding_service.py").read_text()

        assert "EmbeddingService" in tasks_content
        assert "/api/tags" in service_content
        assert "/api/embeddings" in service_content


class TestEmbeddingContract:
    """Document the canonical embedding contract shared by v2 paths."""

    def test_embedding_contract_enforces_canonical(self) -> None:
        """embedding_contract.py enforces intfloat/multilingual-e5-large and 1024."""
        content = (SRC / "embedding_contract.py").read_text()

        assert "intfloat/multilingual-e5-large" in content
        assert "1024" in content


class TestContractsPackage:
    """Verify the contracts package provides required E5 utilities."""

    def test_format_passage_exists(self) -> None:
        path = REPO_ROOT / "packages" / "contracts" / "src" / "nexus_contracts" / "embedding_utils.py"
        content = path.read_text()
        assert "def format_passage" in content
        assert 'passage: ' in content

    def test_format_query_exists(self) -> None:
        path = REPO_ROOT / "packages" / "contracts" / "src" / "nexus_contracts" / "embedding_utils.py"
        content = path.read_text()
        assert "def format_query" in content
        assert 'query: ' in content
