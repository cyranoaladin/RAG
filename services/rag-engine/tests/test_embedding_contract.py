"""Fail-closed contract tests for the RAG v2 1024d embedding pipeline."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.ingestor.embedding_contract import (
    CANONICAL_EMBED_DIM,
    CANONICAL_EMBED_MODEL,
    EmbeddingContractError,
    embedding_contract_health,
    load_embedding_model,
    validate_embedding_contract,
    verify_configured_embedding_artifact,
    verify_embedding_artifact,
)

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
COMPOSE = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"
CONFIG = ENGINE_ROOT / "configs" / "rag_collections.yml"
API = ENGINE_ROOT / "src" / "ingestor" / "api_v2.py"
TASKS = ENGINE_ROOT / "src" / "ingestor" / "tasks.py"
SMOKE = REPO_ROOT / "scripts" / "e2e" / "smoke-embedding-contract.sh"


def _write_embedding_artifact(
    root: Path,
    *,
    model_id: str = CANONICAL_EMBED_MODEL,
    canonical_dim: int = CANONICAL_EMBED_DIM,
) -> None:
    root.mkdir()
    files = {
        "config.json": '{"architectures":["BertModel"]}\n',
        "manifest.json": json.dumps(
            {"model_id": model_id, "canonical_dim": canonical_dim}
        )
        + "\n",
        "model.safetensors": "fake deterministic weights\n",
    }
    for relative_path, content in files.items():
        (root / relative_path).write_text(content, encoding="utf-8")
    checksums = "".join(
        f"{hashlib.sha256(content.encode()).hexdigest()}  {relative_path}\n"
        for relative_path, content in sorted(files.items())
    )
    (root / "SHA256SUMS").write_text(checksums, encoding="utf-8")


def test_canonical_embedding_contract_is_e5_large_1024() -> None:
    assert CANONICAL_EMBED_MODEL == "intfloat/multilingual-e5-large"
    assert CANONICAL_EMBED_DIM == 1024


def test_v2_catalogue_and_compose_declare_1024_without_nomic_fallback() -> None:
    catalogue = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    compose = COMPOSE.read_text(encoding="utf-8")

    assert catalogue["physical_backend"]["vector_dim"] == 1024
    assert 'EMBED_DIM: "1024"' in compose
    assert "${EMBED_DIM" not in compose
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


def test_embedding_artifact_contract_accepts_only_the_canonical_inventory(
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "embedding"
    _write_embedding_artifact(artifact)

    assert verify_embedding_artifact(artifact) == artifact.resolve()


@pytest.mark.parametrize(
    "tampering",
    ("model_id", "dimension", "checksum", "missing_weight", "unlisted", "symlink"),
)
def test_embedding_artifact_contract_rejects_substitution(
    tmp_path: Path,
    tampering: str,
) -> None:
    artifact = tmp_path / "embedding"
    _write_embedding_artifact(
        artifact,
        model_id="attacker/model" if tampering == "model_id" else CANONICAL_EMBED_MODEL,
        canonical_dim=768 if tampering == "dimension" else CANONICAL_EMBED_DIM,
    )
    if tampering == "checksum":
        (artifact / "config.json").write_text("substituted\n", encoding="utf-8")
    elif tampering == "missing_weight":
        (artifact / "model.safetensors").unlink()
    elif tampering == "unlisted":
        (artifact / "unlisted.bin").write_bytes(b"substituted")
    elif tampering == "symlink":
        (artifact / "linked-config.json").symlink_to(artifact / "config.json")

    with pytest.raises(EmbeddingContractError):
        verify_embedding_artifact(artifact)


def test_embedding_artifact_must_be_explicitly_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAG_EMBEDDING_MODEL_CACHE_DIR", raising=False)

    with pytest.raises(
        EmbeddingContractError,
        match="EMBEDDING_MODEL_ARTIFACT_PATH_REQUIRED",
    ):
        verify_configured_embedding_artifact()


def test_embedding_loader_verifies_before_offline_load(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "embedding"
    _write_embedding_artifact(artifact)
    calls: list[tuple[str, dict[str, object]]] = []

    def sentence_transformer(path: str, **kwargs: object) -> object:
        calls.append((path, kwargs))
        return object()

    monkeypatch.setenv("RAG_EMBEDDING_MODEL_CACHE_DIR", str(artifact))
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=sentence_transformer),
    )

    load_embedding_model()

    assert calls == [(str(artifact.resolve()), {"local_files_only": True})]


def test_public_health_uses_the_embedding_contract_payload() -> None:
    source = API.read_text(encoding="utf-8")

    for field in (
        "embedding_model",
        "embedding_dim_declared",
        "pgvector_dim",
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
