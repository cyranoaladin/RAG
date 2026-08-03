"""Cycle de vie du pool PostgreSQL partagé par l'application FastAPI."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.ingestor import api_v2, pg_pool


class _FakePool:
    def __init__(self) -> None:
        self.close_calls = 0

    def open(self, *, wait: bool) -> None:
        assert wait is False

    def wait(self, *, timeout: float) -> None:
        assert timeout == 1.0

    def close(self) -> None:
        self.close_calls += 1


@pytest.fixture(autouse=True)
def reset_pool() -> Iterator[None]:
    pg_pool.close_pool()
    try:
        yield
    finally:
        pg_pool.close_pool()


def test_fastapi_shutdown_closes_pool_once_and_allows_recreation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert hasattr(api_v2, "close_pool")
    instances: list[_FakePool] = []

    def factory(_dsn: str, **_kwargs: Any) -> _FakePool:
        pool = _FakePool()
        instances.append(pool)
        return pool

    monkeypatch.setattr(pg_pool, "_pool_factory", factory)
    attestations = (
        MagicMock(name="embedding_attestation"),
        MagicMock(name="reranker_attestation"),
    )
    monkeypatch.setattr(
        api_v2,
        "_initialize_model_artifacts",
        lambda: attestations,
    )
    monkeypatch.setattr(
        api_v2.retrieval_v2_endpoint,
        "preload_runtime_models",
        lambda: None,
    )
    monkeypatch.setattr(api_v2, "_model_artifacts_ready", lambda: True)
    close_spy = MagicMock(wraps=pg_pool.close_pool)
    monkeypatch.setattr(api_v2, "close_pool", close_spy)
    settings = pg_pool.PoolSettings(
        dsn="postgresql://runtime.invalid/rag",
        min_size=1,
        max_size=2,
        timeout_s=1.0,
    )
    monkeypatch.setattr(
        api_v2.PoolSettings,
        "from_env",
        classmethod(lambda _cls: settings),
    )
    first = pg_pool.get_pool(settings)

    with TestClient(api_v2.app):
        pass

    assert close_spy.call_count == 1
    assert first is instances[0]
    assert instances[0].close_calls == 1

    second = pg_pool.get_pool(settings)
    assert second is instances[1]
    assert second is not first
