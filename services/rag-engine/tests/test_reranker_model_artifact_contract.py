"""Contrat hors-ligne de l'artefact reranker du runtime v2."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.ingestor import reranker_contract

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ENGINE_ROOT.parents[1]
COMPOSE = ENGINE_ROOT / "infra" / "docker-compose.v2.yml"
ENV_EXAMPLE = ENGINE_ROOT / "infra" / ".env.example"
ENDPOINT = ENGINE_ROOT / "src" / "ingestor" / "retrieval_v2_endpoint.py"
VERIFY_SCRIPT = REPOSITORY_ROOT / "scripts" / "e2e" / "verify-reranker-model-artifact.sh"


def _write_artifact(
    root: Path,
    *,
    model_id: str = reranker_contract.CANONICAL_RERANK_MODEL,
) -> None:
    root.mkdir()
    files = {
        "config.json": '{"architectures":["BertForSequenceClassification"]}\n',
        "manifest.json": json.dumps({"model_id": model_id}) + "\n",
        "model.safetensors": "fake deterministic weights\n",
    }
    for relative_path, content in files.items():
        (root / relative_path).write_text(content, encoding="utf-8")
    checksums = "".join(
        f"{hashlib.sha256(content.encode()).hexdigest()}  {relative_path}\n"
        for relative_path, content in sorted(files.items())
    )
    (root / "SHA256SUMS").write_text(checksums, encoding="utf-8")


def test_reranker_rejects_a_missing_configured_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    monkeypatch.setenv("RAG_RERANKER_MODEL_CACHE_DIR", str(missing))
    monkeypatch.setenv("RAG_RERANKER_MODEL_INVENTORY_SHA256", "0" * 64)

    with pytest.raises(
        reranker_contract.RerankerContractError,
        match="RERANKER_MODEL_ARTIFACT_PATH_MISSING",
    ):
        reranker_contract.load_reranker_model()


def test_reranker_load_is_offline_and_uses_the_read_only_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "reranker"
    _write_artifact(artifact)
    calls: list[tuple[str, dict[str, object]]] = []

    def cross_encoder(path: str, **kwargs: object) -> object:
        calls.append((path, kwargs))
        return object()

    monkeypatch.setenv("RAG_RERANKER_MODEL_CACHE_DIR", str(artifact))
    monkeypatch.setenv(
        "RAG_RERANKER_MODEL_INVENTORY_SHA256",
        hashlib.sha256((artifact / "SHA256SUMS").read_bytes()).hexdigest(),
    )
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(CrossEncoder=cross_encoder),
    )

    reranker_contract.load_reranker_model()

    assert calls == [
        (
            str(artifact),
            {"max_length": 512, "local_files_only": True},
        )
    ]


@pytest.mark.parametrize(
    "tampering", ("model_id", "checksum", "missing_weight", "unlisted", "symlink")
)
def test_reranker_rejects_every_substituted_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    tampering: str,
) -> None:
    artifact = tmp_path / "reranker"
    _write_artifact(
        artifact,
        model_id=(
            "attacker/model"
            if tampering == "model_id"
            else reranker_contract.CANONICAL_RERANK_MODEL
        ),
    )
    inventory_sha256 = hashlib.sha256((artifact / "SHA256SUMS").read_bytes()).hexdigest()
    if tampering == "checksum":
        (artifact / "config.json").write_text("substituted\n", encoding="utf-8")
    elif tampering == "missing_weight":
        (artifact / "model.safetensors").unlink()
    elif tampering == "unlisted":
        (artifact / "unlisted.bin").write_bytes(b"substituted")
    else:
        (artifact / "linked-config.json").symlink_to(artifact / "config.json")
    monkeypatch.setenv("RAG_RERANKER_MODEL_CACHE_DIR", str(artifact))
    monkeypatch.setenv("RAG_RERANKER_MODEL_INVENTORY_SHA256", inventory_sha256)
    calls: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(CrossEncoder=lambda path, **_kwargs: calls.append(path)),
    )

    with pytest.raises(reranker_contract.RerankerContractError):
        reranker_contract.load_reranker_model()
    assert calls == []


def test_reranker_rejects_an_unconfigured_artifact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("RAG_RERANKER_MODEL_CACHE_DIR", raising=False)
    monkeypatch.delenv("RAG_RERANKER_MODEL_INVENTORY_SHA256", raising=False)

    with pytest.raises(
        reranker_contract.RerankerContractError,
        match="RERANKER_MODEL_ARTIFACT_PATH_REQUIRED",
    ):
        reranker_contract.load_reranker_model()


def test_reranker_requires_an_external_inventory_trust_anchor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "reranker"
    _write_artifact(artifact)
    monkeypatch.setenv("RAG_RERANKER_MODEL_CACHE_DIR", str(artifact))
    monkeypatch.delenv("RAG_RERANKER_MODEL_INVENTORY_SHA256", raising=False)

    with pytest.raises(
        reranker_contract.RerankerContractError,
        match="RERANKER_MODEL_INVENTORY_SHA256_REQUIRED",
    ):
        reranker_contract.verify_configured_reranker_artifact()


def test_reranker_rejects_a_replaced_self_consistent_bundle(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    artifact = tmp_path / "reranker"
    _write_artifact(artifact)
    trusted_inventory_sha256 = hashlib.sha256(
        (artifact / "SHA256SUMS").read_bytes()
    ).hexdigest()
    (artifact / "model.safetensors").write_bytes(b"replacement weights")
    checksums = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
        for path in sorted(artifact.iterdir())
        if path.name != "SHA256SUMS"
    )
    (artifact / "SHA256SUMS").write_text(checksums, encoding="utf-8")
    monkeypatch.setenv("RAG_RERANKER_MODEL_CACHE_DIR", str(artifact))
    monkeypatch.setenv(
        "RAG_RERANKER_MODEL_INVENTORY_SHA256",
        trusted_inventory_sha256,
    )

    with pytest.raises(
        reranker_contract.RerankerContractError,
        match="RERANKER_MODEL_ARTIFACT_INVALID",
    ):
        reranker_contract.verify_configured_reranker_artifact()


def test_v2_compose_mounts_only_effective_reranker_configuration() -> None:
    compose = COMPOSE.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")

    for content in (compose, env_example):
        assert "RERANKER_MODEL=" not in content
        assert "RERANKER_TOP_N" not in content
    assert "RAG_RERANKER_MODEL_CACHE_DIR: /models/reranker" in compose
    assert "RAG_RERANKER_MODEL_INVENTORY_SHA256" in compose
    assert "RAG_RERANKER_MODEL_INVENTORY_SHA256=" in env_example
    assert "RAG_RERANKER_MODEL_ARTIFACT_HOST_DIR" in compose
    assert "/models/reranker:ro" in compose
    assert 'HF_HUB_OFFLINE: "1"' in compose
    assert 'TRANSFORMERS_OFFLINE: "1"' in compose


def test_retrieval_endpoint_delegates_reranker_loading_to_contract() -> None:
    source = ENDPOINT.read_text(encoding="utf-8")

    assert "load_reranker_model" in source
    assert "CrossEncoder(" not in source


def test_retrieval_uses_the_single_canonical_reranker_identifier() -> None:
    source = (
        ENGINE_ROOT / "src" / "ingestor" / "retrieval_hybrid_v2.py"
    ).read_text(encoding="utf-8")

    assert "RERANK_MODEL = CANONICAL_RERANK_MODEL" in source
    assert reranker_contract.CANONICAL_RERANK_MODEL not in source


def test_reranker_artifact_verifier_is_offline_and_checks_integrity() -> None:
    source = VERIFY_SCRIPT.read_text(encoding="utf-8")

    assert "verify_reranker_artifact" in source
    assert "local_files_only=True" in source
    assert "HF_HUB_OFFLINE" in source
    assert "MODEL_ARTIFACT_DIR" in source
