"""Contract tests for the 1024d embedding model artifact preflight.

These tests verify structural properties of scripts, Dockerfiles, and Compose
configuration. They do NOT download or load any model.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]

PREPARE_SCRIPT = REPO_ROOT / "scripts" / "e2e" / "prepare-embedding-model-artifact.sh"
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "e2e" / "verify-embedding-model-artifact.sh"
COMPOSE = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"
DOCKERFILE = ENGINE_ROOT / "infra" / "Dockerfile.ingestor-v2"
EMBEDDING_CONTRACT = ENGINE_ROOT / "src" / "ingestor" / "embedding_contract.py"
RETRIEVAL_V2 = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"


# -- Prepare script guards --


class TestPrepareScript:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.source = PREPARE_SCRIPT.read_text(encoding="utf-8")

    def test_script_exists(self) -> None:
        assert PREPARE_SCRIPT.is_file()

    def test_refuses_empty_model_artifact_dir(self) -> None:
        assert "MODEL_ARTIFACT_DIR" in self.source
        assert 'MODEL_ARTIFACT_DIR:-}' in self.source or "MODEL_ARTIFACT_DIR" in self.source

    def test_requires_embedding_model_revision(self) -> None:
        assert "EMBEDDING_MODEL_REVISION" in self.source

    def test_refuses_artifact_inside_git_repo(self) -> None:
        assert "REAL_REPO" in self.source or "REPO_ROOT" in self.source

    def test_refuses_production_environment(self) -> None:
        assert "production" in self.source

    def test_generates_manifest(self) -> None:
        assert "manifest.json" in self.source

    def test_generates_checksums(self) -> None:
        assert "SHA256SUMS" in self.source

    def test_does_not_touch_docker_production(self) -> None:
        assert "docker push" not in self.source
        assert "docker-compose up" not in self.source

    def test_does_not_launch_ingestion(self) -> None:
        assert "/ingest/" not in self.source
        assert "POST " not in self.source.upper()


# -- Verify script guards --


class TestVerifyScript:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.source = VERIFY_SCRIPT.read_text(encoding="utf-8")

    def test_script_exists(self) -> None:
        assert VERIFY_SCRIPT.is_file()

    def test_requires_model_artifact_dir(self) -> None:
        assert "MODEL_ARTIFACT_DIR" in self.source

    def test_checks_manifest(self) -> None:
        assert "manifest.json" in self.source

    def test_checks_checksums(self) -> None:
        assert "SHA256SUMS" in self.source
        assert "sha256sum" in self.source

    def test_verifies_canonical_model(self) -> None:
        assert "intfloat/multilingual-e5-large" in self.source

    def test_verifies_canonical_dimension(self) -> None:
        assert "1024" in self.source

    def test_detects_nomic_fallback(self) -> None:
        assert "nomic" in self.source.lower()

    def test_uses_offline_mode(self) -> None:
        assert "local_files_only" in self.source
        assert "HF_HUB_OFFLINE" in self.source

    def test_does_not_download(self) -> None:
        assert "snapshot_download" not in self.source
        assert "hf_hub_download" not in self.source


# -- Runtime guards: no uncontrolled downloads --


class TestRuntimeNoDownload:
    def test_embedding_contract_uses_local_files_only(self) -> None:
        source = EMBEDDING_CONTRACT.read_text(encoding="utf-8")
        assert "local_files_only=True" in source

    def test_embedding_contract_has_no_snapshot_download(self) -> None:
        source = EMBEDDING_CONTRACT.read_text(encoding="utf-8")
        assert "snapshot_download" not in source

    def test_retrieval_v2_has_no_snapshot_download(self) -> None:
        source = RETRIEVAL_V2.read_text(encoding="utf-8")
        assert "snapshot_download" not in source

    def test_dockerfile_does_not_auto_download_model(self) -> None:
        source = DOCKERFILE.read_text(encoding="utf-8")
        assert "snapshot_download" not in source
        assert "huggingface-cli download" not in source
        # No RUN command that fetches the embedding model
        assert "intfloat/multilingual-e5-large" not in source


# -- No Nomic fallback in active config --


class TestNoNomicFallback:
    def test_compose_has_no_nomic_default(self) -> None:
        source = COMPOSE.read_text(encoding="utf-8")
        assert "nomic-embed-text:v1.5" not in source
        assert "${EMBED_DIM:-768}" not in source

    def test_embedding_contract_canonical_is_e5_large(self) -> None:
        from src.ingestor.embedding_contract import (
            CANONICAL_EMBED_DIM,
            CANONICAL_EMBED_MODEL,
        )

        assert CANONICAL_EMBED_MODEL == "intfloat/multilingual-e5-large"
        assert CANONICAL_EMBED_DIM == 1024


# -- Compose model mount support --


class TestComposeModelMount:
    @pytest.fixture(autouse=True)
    def _load(self) -> None:
        self.source = COMPOSE.read_text(encoding="utf-8")

    def test_ingestor_has_model_cache_volume(self) -> None:
        assert "RAG_EMBEDDING_MODEL_CACHE_DIR" in self.source

    def test_worker_has_model_cache_volume(self) -> None:
        # Both ingestor and worker should support the mount
        lines = self.source.split("\n")
        in_worker = False
        worker_has_mount = False
        for line in lines:
            if "worker:" in line and not line.strip().startswith("#"):
                in_worker = True
            elif in_worker and "RAG_EMBEDDING_MODEL_CACHE_DIR" in line:
                worker_has_mount = True
                break
            elif in_worker and line.strip() and not line.startswith(" ") and ":" in line:
                break
        assert worker_has_mount, "worker service should reference RAG_EMBEDDING_MODEL_CACHE_DIR"


# -- No test downloads model --


class TestNoTestDownloads:
    def test_this_file_does_not_import_download_apis(self) -> None:
        """Ensure this test file never calls download or model-loading APIs."""
        import ast

        tree = ast.parse(Path(__file__).read_text(encoding="utf-8"))
        called_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                called_names.add(node.func.attr)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                called_names.add(node.func.id)
        assert "snapshot_download" not in called_names
        assert "SentenceTransformer" not in called_names
