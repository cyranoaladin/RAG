"""Contrats d'audit du runtime v2 lecture/revue et de la dette legacy."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "services" / "rag-engine" / "src" / "ingestor"


class TestActiveRuntimeV2Path:
    """Le runtime certifié ne publie aucun chemin d'écriture vectorielle."""

    def test_image_and_compose_start_only_api_v2(self) -> None:
        dockerfile = (REPO_ROOT / "services" / "rag-engine" / "infra" / "Dockerfile.ingestor-v2").read_text()
        compose = (REPO_ROOT / "services" / "rag-engine" / "infra" / "docker-compose.v2.yml").read_text()

        assert "api_v2:app" in dockerfile
        assert "api_v2:app" in compose
        assert "api:app" not in compose

    def test_minimal_api_does_not_import_ingestion_modules(self) -> None:
        content = (SRC / "api_v2.py").read_text()

        assert "ingest_v2" not in content
        assert "ingest_v2_endpoint" not in content
        assert "tasks" not in content

    def test_retrieval_v2_uses_load_embedding_model(self) -> None:
        """retrieval_v2_endpoint.py uses the same local contract model loader."""
        content = (SRC / "retrieval_v2_endpoint.py").read_text()

        assert "load_embedding_model()" in content


class TestLegacyWorkerDebt:
    """Keep the remaining Celery/Ollama embedding path visible as legacy debt."""

    def test_legacy_worker_ollama_path_still_active(self) -> None:
        """Le code historique reste identifié, sans être démarré par Compose v2."""
        tasks_content = (SRC / "tasks.py").read_text()
        service_content = (SRC / "embedding_service.py").read_text()
        compose = (REPO_ROOT / "services" / "rag-engine" / "infra" / "docker-compose.v2.yml").read_text()

        assert "EmbeddingService" in tasks_content
        assert "/api/tags" in service_content
        assert "/api/embeddings" in service_content
        assert "celery -A tasks" not in compose


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
