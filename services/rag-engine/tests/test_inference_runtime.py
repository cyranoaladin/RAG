"""Tests du budget global et de la capacité d'inférence du retrieval v2."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from src.ingestor import inference_runtime, pg_pool


def _run_after_capacity_release() -> tuple[float, ...]:
    deadline = time.monotonic() + 1.0
    while True:
        try:
            return inference_runtime.run_bounded_inference(lambda: (3.0,))
        except inference_runtime.InferenceRuntimeError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.001)


def test_bounded_inference_refuses_saturation_without_queueing_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    rejected_operation_called = Event()
    budget_calls = 0

    def remaining_budget() -> int:
        nonlocal budget_calls
        budget_calls += 1
        return 1_000

    monkeypatch.setattr(
        inference_runtime,
        "remaining_request_budget_ms",
        remaining_budget,
    )

    def blocking_operation() -> tuple[float, ...]:
        started.set()
        assert release.wait(timeout=1.0)
        return (1.0,)

    with ThreadPoolExecutor(max_workers=1) as caller:
        first = caller.submit(inference_runtime.run_bounded_inference, blocking_operation)
        assert started.wait(timeout=1.0)

        def rejected_operation() -> tuple[float, ...]:
            rejected_operation_called.set()
            return (2.0,)

        with pytest.raises(inference_runtime.InferenceRuntimeError):
            inference_runtime.run_bounded_inference(rejected_operation)
        assert rejected_operation_called.is_set() is False
        assert budget_calls == 1
        release.set()
        assert first.result(timeout=1.0) == (1.0,)
        monkeypatch.setattr(
            inference_runtime,
            "remaining_request_budget_ms",
            lambda: 1_000,
        )
        assert _run_after_capacity_release() == (3.0,)


def test_bounded_inference_returns_on_deadline_and_holds_capacity_until_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    release = Event()
    monkeypatch.setattr(
        inference_runtime,
        "remaining_request_budget_ms",
        lambda: 20,
    )

    def blocking_operation() -> tuple[float, ...]:
        started.set()
        assert release.wait(timeout=1.0)
        return (1.0,)

    with pytest.raises(inference_runtime.InferenceRuntimeError):
        inference_runtime.run_bounded_inference(blocking_operation)
    assert started.is_set() is True

    with pytest.raises(inference_runtime.InferenceRuntimeError):
        inference_runtime.run_bounded_inference(lambda: (2.0,))

    release.set()
    monkeypatch.setattr(
        inference_runtime,
        "remaining_request_budget_ms",
        lambda: 1_000,
    )
    assert _run_after_capacity_release() == (3.0,)


def test_bounded_inference_propagates_the_request_deadline_to_its_worker() -> None:
    with pg_pool.runtime_request_budget(1_000):
        caller_remainder_ms = pg_pool.remaining_request_budget_ms()
        worker_remainder_ms = inference_runtime.run_bounded_inference(
            pg_pool.remaining_request_budget_ms
        )

    assert 0 < worker_remainder_ms <= caller_remainder_ms <= 1_000


def test_model_adapters_materialize_results_inside_bounded_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def immediate(operation):
        calls.append("bounded")
        return operation()

    monkeypatch.setattr(inference_runtime, "run_bounded_inference", immediate)

    class Embedder:
        def encode(self, text: str, *, normalize_embeddings: bool):
            assert text == "query: graphe"
            assert normalize_embeddings is True
            return (value for value in (1.0, 0.0))

    class Reranker:
        def predict(self, pairs):
            assert pairs == [("graphe", "cours")]
            return (value for value in (2.0,))

    embedder = inference_runtime.BoundedInferenceEmbedder(Embedder())
    reranker = inference_runtime.BoundedInferenceReranker(Reranker())

    assert embedder.encode("query: graphe", normalize_embeddings=True) == (1.0, 0.0)
    assert reranker.predict([("graphe", "cours")]) == (2.0,)
    assert calls == ["bounded", "bounded"]
