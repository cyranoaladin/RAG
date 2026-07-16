"""Fail-closed contract tests for the RAG v2 1024d embedding pipeline."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.ingestor.embedding_contract import (
    CANONICAL_EMBED_DIM,
    CANONICAL_EMBED_MODEL,
    EmbeddingContractError,
    embedding_contract_health,
    validate_embedding_contract,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
COMPOSE = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"
CONFIG = ENGINE_ROOT / "configs" / "rag_collections.yml"
API = ENGINE_ROOT / "src" / "ingestor" / "api.py"
TASKS = ENGINE_ROOT / "src" / "ingestor" / "tasks.py"
SMOKE = REPO_ROOT / "scripts" / "e2e" / "smoke-embedding-contract.sh"


def test_canonical_embedding_contract_is_e5_large_1024() -> None:
    assert CANONICAL_EMBED_MODEL == "intfloat/multilingual-e5-large"
    assert CANONICAL_EMBED_DIM == 1024


def test_v2_catalogue_and_compose_declare_1024_without_nomic_fallback() -> None:
    catalogue = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    compose = COMPOSE.read_text(encoding="utf-8")

    assert catalogue["physical_backend"]["vector_dim"] == 1024
    assert '${EMBED_DIM:-1024}' in compose
    assert "${EMBED_DIM:-768}" not in compose
    assert "nomic-embed-text:v1.5" not in compose
    assert "intfloat/multilingual-e5-large" in compose


@pytest.mark.parametrize(
    ("declared_dim", "runtime_dim", "pgvector_dim"),
    [
        (768, 768, 1024),
        (1024, 768, 1024),
        (1024, 1024, 768),
    ],
)
def test_contract_rejects_any_dimension_mismatch(
    declared_dim: int,
    runtime_dim: int,
    pgvector_dim: int,
) -> None:
    with pytest.raises(EmbeddingContractError):
        validate_embedding_contract(
            model=CANONICAL_EMBED_MODEL,
            declared_dim=declared_dim,
            runtime_dim=runtime_dim,
            pgvector_dim=pgvector_dim,
        )


def test_contract_rejects_a_noncanonical_768_model_without_padding_or_truncation() -> None:
    with pytest.raises(EmbeddingContractError):
        validate_embedding_contract(
            model="nomic-embed-text:v1.5",
            declared_dim=1024,
            runtime_dim=768,
            pgvector_dim=1024,
        )


def test_health_payload_exposes_only_non_sensitive_embedding_contract_fields() -> None:
    payload = embedding_contract_health(
        model=CANONICAL_EMBED_MODEL,
        declared_dim=1024,
        runtime_dim=1024,
        pgvector_dim=1024,
    )

    assert payload == {
        "embedding_model": "intfloat/multilingual-e5-large",
        "embedding_dim_declared": 1024,
        "embedding_dim_runtime": 1024,
        "pgvector_dim": 1024,
        "embedding_contract_ok": True,
    }


def test_public_health_uses_the_embedding_contract_payload() -> None:
    source = API.read_text(encoding="utf-8")

    for field in (
        "embedding_model",
        "embedding_dim_declared",
        "embedding_dim_runtime",
        "pgvector_dim",
        "embedding_contract_ok",
    ):
        assert field in source


def test_worker_checks_the_v2_contract_before_any_legacy_write_path() -> None:
    source = TASKS.read_text(encoding="utf-8")

    assert "validate_runtime_embedding_contract" in source
    assert "load_embedding_model" in source


def test_smoke_script_is_present_and_read_only() -> None:
    source = SMOKE.read_text(encoding="utf-8")

    assert SMOKE.is_file()
    assert "INSERT" not in source.upper()
    assert "/ingest/" not in source
    assert "POST " not in source.upper()
    assert "EMBED_DIM" in source
    assert "vector" in source


def test_smoke_imports_embedding_contract_from_compose_and_repo_contexts() -> None:
    source = SMOKE.read_text(encoding="utf-8")

    assert "from embedding_contract import" in source
    assert "from src.ingestor.embedding_contract import" in source
    assert 'error.name != "embedding_contract"' in source
