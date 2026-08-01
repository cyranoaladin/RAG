"""Cycle de vie du pool PostgreSQL partagé par l'application FastAPI."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.ingestor import api, pg_pool


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
    assert hasattr(api, "close_pool")
    instances: list[_FakePool] = []

    def factory(_dsn: str, **_kwargs: Any) -> _FakePool:
        pool = _FakePool()
        instances.append(pool)
        return pool

    monkeypatch.setattr(pg_pool, "_pool_factory", factory)
    close_spy = MagicMock(wraps=pg_pool.close_pool)
    monkeypatch.setattr(api, "close_pool", close_spy)
    settings = pg_pool.PoolSettings(
        dsn="postgresql://runtime.invalid/rag",
        min_size=1,
        max_size=2,
        timeout_s=1.0,
    )
    first = pg_pool.get_pool(settings)

    with TestClient(api.app):
        pass

    assert close_spy.call_count == 1
    assert first is instances[0]
    assert instances[0].close_calls == 1

    second = pg_pool.get_pool(settings)
    assert second is instances[1]
    assert second is not first
