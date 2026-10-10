"""Le profil d'inférence CUDA refuse tout repli implicite sur CPU."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from src.ingestor import inference_runtime

ROOT = Path(__file__).resolve().parents[1]
INFRA = ROOT / "infra"


class _ModelWeights:
    def __init__(self, device: str) -> None:
        self.device = device

    def parameters(self):
        yield SimpleNamespace(device=self.device)

    def buffers(self):
        return iter(())

    def to(self, device: str) -> None:
        self.device = str(device)


def test_cross_encoder_weights_move_to_gpu_during_preload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_REQUIRE_CUDA", "true")
    monkeypatch.setattr(inference_runtime, "_cuda_is_available", lambda: True)
    embedding = _ModelWeights("cuda:0")
    reranker_weights = _ModelWeights("cpu")
    reranker = SimpleNamespace(model=reranker_weights, _target_device="cuda:0")

    inference_runtime.verify_required_inference_device(embedding, reranker)

    assert reranker_weights.device == "cuda:0"


def test_cuda_label_does_not_hide_cpu_weights(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_REQUIRE_CUDA", "true")
    monkeypatch.setattr(inference_runtime, "_cuda_is_available", lambda: True)
    embedding = _ModelWeights("cpu")
    embedding.device = "cuda:0"
    embedding.parameters = lambda: iter((SimpleNamespace(device="cpu"),))
    reranker = _ModelWeights("cuda:0")

    with pytest.raises(inference_runtime.InferenceRuntimeError, match="CUDA_INFERENCE_UNAVAILABLE"):
        inference_runtime.verify_required_inference_device(embedding, reranker)


@pytest.mark.parametrize(
    ("embedding_device", "reranker_device", "cuda_available"),
    [
        ("cpu", "cuda:0", True),
        ("cuda:0", "cpu", True),
        ("cuda:0", "cuda:0", False),
    ],
)
def test_required_cuda_rejects_cpu_models_or_unavailable_device(
    monkeypatch: pytest.MonkeyPatch,
    embedding_device: str,
    reranker_device: str,
    cuda_available: bool,
) -> None:
    monkeypatch.setenv("RAG_REQUIRE_CUDA", "true")
    monkeypatch.setattr(inference_runtime, "_cuda_is_available", lambda: cuda_available)

    with pytest.raises(inference_runtime.InferenceRuntimeError, match="CUDA_INFERENCE_UNAVAILABLE"):
        inference_runtime.verify_required_inference_device(
            _ModelWeights(embedding_device),
            _ModelWeights(reranker_device),
        )


def test_required_cuda_accepts_both_models_on_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_REQUIRE_CUDA", "true")
    monkeypatch.setattr(inference_runtime, "_cuda_is_available", lambda: True)

    inference_runtime.verify_required_inference_device(
        _ModelWeights("cuda:0"),
        _ModelWeights("cuda:0"),
    )


def test_cuda_requirement_refuses_ambiguous_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAG_REQUIRE_CUDA", "perhaps")
    with pytest.raises(inference_runtime.InferenceRuntimeError, match="CUDA_REQUIREMENT_INVALID"):
        inference_runtime.verify_required_inference_device(object(), object())


def test_cpu_runtime_remains_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RAG_REQUIRE_CUDA", raising=False)
    inference_runtime.verify_required_inference_device(object(), object())


def test_cuda_image_and_compose_require_gpu_without_changing_retrieval() -> None:
    dockerfile = (INFRA / "Dockerfile.ingestor-v2.cuda").read_text()
    cpu_dockerfile = (INFRA / "Dockerfile.ingestor-v2").read_text()
    requirements = (ROOT / "src/ingestor/requirements.runtime-v2.cuda.txt").read_text()
    cpu_requirements = (ROOT / "src/ingestor/requirements.runtime-v2.txt").read_text()
    override = yaml.safe_load((INFRA / "docker-compose.cuda-inference.override.yml").read_text())
    api = override["services"]["ingestor"]
    assert "torch==2.4.1+cu121" in requirements
    assert "torch==2.4.1+cpu" not in requirements
    assert {
        line for line in requirements.splitlines() if line and not line.startswith(("#", "--", "torch=="))
    } == {
        line for line in cpu_requirements.splitlines() if line and not line.startswith(("#", "--", "torch=="))
    }
    assert "requirements.runtime-v2.cuda.txt" in dockerfile
    assert "ENV RAG_REQUIRE_CUDA=true" in dockerfile
    assert dockerfile.split("\n", 1)[1].replace("ENV RAG_REQUIRE_CUDA=true\n", "").replace(
        "requirements.runtime-v2.cuda.txt", "requirements.runtime-v2.txt"
    ) == cpu_dockerfile
    assert "COPY services/rag-engine/src/ingestor/api_v2.py /app/api_v2.py" in dockerfile
    assert api["build"]["dockerfile"] == "services/rag-engine/infra/Dockerfile.ingestor-v2.cuda"
    assert api["environment"]["RAG_REQUIRE_CUDA"] == "true"
    assert api["deploy"]["resources"]["reservations"]["devices"] == [
        {"driver": "nvidia", "count": 1, "capabilities": ["gpu"]}
    ]
    assert api["command"] == "uvicorn api_v2:app --host 0.0.0.0 --port 8001 --workers 1"
    assert "PG_POOL_MAX_SIZE" not in api.get("environment", {})


def test_cuda_gate_is_executed_during_model_preload() -> None:
    endpoint = (ROOT / "src/ingestor/retrieval_v2_endpoint.py").read_text()
    assert "verify_required_inference_device(embed_model, reranker)" in endpoint


def test_model_preload_refuses_cpu_fallback_when_cuda_is_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.ingestor import retrieval_v2_endpoint as endpoint

    monkeypatch.setenv("RAG_REQUIRE_CUDA", "true")
    monkeypatch.setattr(inference_runtime, "_cuda_is_available", lambda: False)
    monkeypatch.setattr(endpoint, "_get_embed_model", lambda: SimpleNamespace(device="cpu"))
    monkeypatch.setattr(endpoint, "_get_reranker", lambda: SimpleNamespace(device="cpu"))
    monkeypatch.setattr(endpoint, "runtime_embedding_dimension", lambda _model: 1024)
    monkeypatch.setattr(endpoint, "declared_embedding_dim", lambda: 1024)

    with pytest.raises(inference_runtime.InferenceRuntimeError, match="CUDA_INFERENCE_UNAVAILABLE"):
        endpoint.preload_runtime_models()
