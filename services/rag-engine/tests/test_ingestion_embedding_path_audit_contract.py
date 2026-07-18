"""Audit tests documenting the current ingestion embedding path state.

These tests prove the existence of gaps identified in the LOT 27 P3 audit.
Tests marked xfail document known debt tracked by LOT_27_P3_AD.
Non-xfail tests document the current correct state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "services" / "rag-engine" / "src" / "ingestor"


class TestIngestionPathCurrentState:
    """Document the current state of the ingestion embedding path."""

    def test_embedding_service_uses_ollama(self) -> None:
        """EmbeddingService still calls Ollama /api/embeddings."""
        content = (SRC / "embedding_service.py").read_text()
        assert "/api/embeddings" in content
        assert "ollama_url" in content

    def test_tasks_uses_embedding_service(self) -> None:
        """tasks.py imports and uses EmbeddingService."""
        content = (SRC / "tasks.py").read_text()
        assert "from embedding_service import EmbeddingService" in content
        assert "embed_svc = EmbeddingService(" in content

    def test_retrieval_v2_uses_load_embedding_model(self) -> None:
        """retrieval_v2_endpoint.py uses the local contract model."""
        content = (SRC / "retrieval_v2_endpoint.py").read_text()
        assert "load_embedding_model" in content
        assert "format_query" in content

    def test_embedding_contract_enforces_canonical(self) -> None:
        """embedding_contract.py enforces intfloat/multilingual-e5-large and 1024."""
        content = (SRC / "embedding_contract.py").read_text()
        assert "intfloat/multilingual-e5-large" in content
        assert "1024" in content

    def test_embedding_service_ollama_path_still_active(self) -> None:
        """EMBEDDING_SERVICE_OLLAMA_PATH_STILL_ACTIVE: the ingestion path
        still depends on Ollama HTTP calls for embedding generation."""
        content = (SRC / "embedding_service.py").read_text()
        # Ollama HTTP endpoint
        assert "self.ollama_url" in content
        assert "/api/embeddings" in content
        # Ollama model availability check
        assert "/api/tags" in content


class TestIngestionPathGaps:
    """Document known gaps — xfail with explicit tracking."""

    @pytest.mark.xfail(
        reason="EmbeddingService/Ollama migration tracked by LOT_27_P3_AD",
        strict=True,
    )
    def test_ingestion_does_not_use_ollama(self) -> None:
        """Once migrated, EmbeddingService should not call Ollama."""
        content = (SRC / "embedding_service.py").read_text()
        assert "/api/embeddings" not in content

    @pytest.mark.xfail(
        reason="EmbeddingService/Ollama migration tracked by LOT_27_P3_AD",
        strict=True,
    )
    def test_ingestion_applies_format_passage(self) -> None:
        """Once migrated, ingestion must apply format_passage to every chunk."""
        tasks_content = (SRC / "tasks.py").read_text()
        embed_content = (SRC / "embedding_service.py").read_text()
        combined = tasks_content + embed_content
        assert "format_passage" in combined

    @pytest.mark.xfail(
        reason="EmbeddingService/Ollama migration tracked by LOT_27_P3_AD",
        strict=True,
    )
    def test_cache_key_includes_prefix_marker(self) -> None:
        """Once migrated, cache key must include E5 prefix marker."""
        content = (SRC / "embedding_service.py").read_text()
        assert "passage" in content.split("_cache_key")[1].split("def ")[0]


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
