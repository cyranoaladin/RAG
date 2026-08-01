"""Tests du pool PostgreSQL partagé du retrieval v2."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from ingestor import pg_pool
from ingestor.pg_pool import PoolConfigurationError, PoolSettings

_ENV_KEYS = (
    "PG_RAG_DSN",
    "DATABASE_URL_SYNC",
    "PG_POOL_MIN_SIZE",
    "PG_POOL_MAX_SIZE",
    "PG_POOL_TIMEOUT_S",
)
_ENGINE_ROOT = Path(__file__).resolve().parents[1]


def _installed_requirement_manifests() -> set[Path]:
    manifests = {_ENGINE_ROOT / "requirements.lock", _ENGINE_ROOT / "requirements-dev.txt"}
    pending = list(manifests)
    while pending:
        manifest = pending.pop()
        for line in manifest.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("-r "):
                referenced = manifest.parent / line.strip().removeprefix("-r ")
                if referenced not in manifests:
                    manifests.add(referenced)
                    pending.append(referenced)
    return manifests


@pytest.fixture(autouse=True)
def _reset_pool_and_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    pg_pool.close_pool()
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    yield
    pg_pool.close_pool()


def test_from_env_prefers_nonblank_pg_rag_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "  postgresql://primary.example/rag  ")
    monkeypatch.setenv("DATABASE_URL_SYNC", "postgresql://fallback.example/rag")

    settings = PoolSettings.from_env()

    assert settings == PoolSettings(
        dsn="postgresql://primary.example/rag",
        min_size=1,
        max_size=10,
        timeout_s=5.0,
    )


def test_from_env_falls_back_to_nonblank_database_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_RAG_DSN", " \t")
    monkeypatch.setenv("DATABASE_URL_SYNC", "  postgresql://fallback.example/rag ")

    assert PoolSettings.from_env().dsn == "postgresql://fallback.example/rag"


@pytest.mark.parametrize(
    ("primary", "fallback"),
    [(None, None), ("", ""), ("  ", "\t")],
)
def test_from_env_rejects_missing_or_blank_dsn(
    monkeypatch: pytest.MonkeyPatch,
    primary: str | None,
    fallback: str | None,
) -> None:
    if primary is not None:
        monkeypatch.setenv("PG_RAG_DSN", primary)
    if fallback is not None:
        monkeypatch.setenv("DATABASE_URL_SYNC", fallback)

    with pytest.raises(PoolConfigurationError, match="DSN PostgreSQL requis"):
        PoolSettings.from_env()


def test_from_env_parses_explicit_pool_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://db.example/rag")
    monkeypatch.setenv("PG_POOL_MIN_SIZE", "2")
    monkeypatch.setenv("PG_POOL_MAX_SIZE", "25")
    monkeypatch.setenv("PG_POOL_TIMEOUT_S", "0.75")

    assert PoolSettings.from_env() == PoolSettings(
        dsn="postgresql://db.example/rag",
        min_size=2,
        max_size=25,
        timeout_s=0.75,
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("PG_POOL_MIN_SIZE", "not-an-int"),
        ("PG_POOL_MAX_SIZE", "1.5"),
        ("PG_POOL_TIMEOUT_S", "not-a-float"),
    ],
)
def test_from_env_rejects_unparseable_pool_values(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: str,
) -> None:
    dsn = "postgresql://secret-user:secret-password@db.example/rag"
    monkeypatch.setenv("PG_RAG_DSN", dsn)
    monkeypatch.setenv(key, value)

    with pytest.raises(PoolConfigurationError) as exc_info:
        PoolSettings.from_env()

    assert dsn not in str(exc_info.value)


@pytest.mark.parametrize(
    ("min_size", "max_size", "timeout_s"),
    [
        (0, 1, 1.0),
        (2, 1, 1.0),
        (1, 51, 1.0),
        (1, 1, 0.0),
        (1, 1, float("inf")),
        (1, 1, float("nan")),
    ],
)
def test_settings_reject_invalid_bounds(
    min_size: int,
    max_size: int,
    timeout_s: float,
) -> None:
    with pytest.raises(PoolConfigurationError):
        PoolSettings(
            dsn="postgresql://db.example/rag",
            min_size=min_size,
            max_size=max_size,
            timeout_s=timeout_s,
        )


@pytest.mark.parametrize("dsn", ["", " ", "\t"])
def test_settings_reject_blank_dsn_without_leaking_it(dsn: str) -> None:
    with pytest.raises(PoolConfigurationError, match="DSN PostgreSQL requis"):
        PoolSettings(dsn=dsn, min_size=1, max_size=10, timeout_s=5.0)


def test_settings_accept_boundary_values() -> None:
    PoolSettings(
        dsn="postgresql://db.example/rag", min_size=1, max_size=50, timeout_s=0.001
    )


def test_all_psycopg_manifest_entries_use_explicit_3_2_1_pins() -> None:
    manifests = _installed_requirement_manifests() | {
        _ENGINE_ROOT / "src/ingestor/requirements.v2.txt"
    }
    all_package_names: set[str] = set()
    for manifest in manifests:
        entries = [
            line.strip()
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("psycopg")
        ]
        assert len(entries) == len({entry.split("==", maxsplit=1)[0] for entry in entries})
        assert all("[" not in entry for entry in entries)
        assert all(entry.endswith("==3.2.1") for entry in entries)
        all_package_names.update(entry.split("==", maxsplit=1)[0] for entry in entries)

    assert all_package_names == {"psycopg", "psycopg-binary", "psycopg-pool"}


class FakePool:
    def __init__(self, events: list[tuple[Any, ...]], *, fail_at: str | None = None) -> None:
        self.events = events
        self.fail_at = fail_at

    def open(self, wait: bool = True) -> None:
        self.events.append(("open", wait))
        if self.fail_at == "open":
            raise RuntimeError("open failed for postgresql://secret@db/rag")

    def wait(self, timeout: float) -> None:
        self.events.append(("wait", timeout))
        if self.fail_at == "wait":
            raise RuntimeError("wait failed for postgresql://secret@db/rag")

    @contextmanager
    def connection(self, timeout: float) -> Iterator[str]:
        self.events.append(("connection-enter", timeout))
        try:
            yield "connection"
        finally:
            self.events.append(("connection-exit", timeout))

    def close(self) -> None:
        self.events.append(("close",))


def _settings(*, dsn: str = "postgresql://db.example/rag") -> PoolSettings:
    return PoolSettings(dsn=dsn, min_size=2, max_size=8, timeout_s=1.25)


def _install_factory(
    monkeypatch: pytest.MonkeyPatch,
    events: list[tuple[Any, ...]],
    *,
    fail_at: str | None = None,
) -> list[FakePool]:
    instances: list[FakePool] = []

    def factory(conninfo: str, **kwargs: Any) -> FakePool:
        events.append(("construct", conninfo, kwargs))
        pool = FakePool(events, fail_at=fail_at)
        instances.append(pool)
        return pool

    monkeypatch.setattr(pg_pool, "_pool_factory", factory)
    return instances


def test_get_pool_constructs_opens_waits_then_reuses_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    instances = _install_factory(monkeypatch, events)
    settings = _settings()

    first = pg_pool.get_pool(settings)
    second = pg_pool.get_pool(settings)

    assert first is second is instances[0]
    assert events == [
        (
            "construct",
            settings.dsn,
            {
                "min_size": 2,
                "max_size": 8,
                "timeout": 1.25,
                "open": False,
            },
        ),
        ("open", False),
        ("wait", 1.25),
    ]


def test_pool_connection_uses_configured_acquisition_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    _install_factory(monkeypatch, events)
    settings = _settings()

    with pg_pool.pool_connection(settings) as connection:
        assert connection == "connection"

    assert events[-2:] == [("connection-enter", 1.25), ("connection-exit", 1.25)]


def test_pool_connection_loads_settings_from_environment_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    _install_factory(monkeypatch, events)
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://db.example/rag")

    with pg_pool.pool_connection() as connection:
        assert connection == "connection"

    assert events[-2:] == [("connection-enter", 5.0), ("connection-exit", 5.0)]


def test_get_pool_refuses_different_settings_without_leaking_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    instances = _install_factory(monkeypatch, events)
    pg_pool.get_pool(_settings())
    other_dsn = "postgresql://secret-user:secret-password@other.example/rag"

    with pytest.raises(PoolConfigurationError, match="paramètres différents") as exc_info:
        pg_pool.get_pool(_settings(dsn=other_dsn))

    assert other_dsn not in str(exc_info.value)
    assert len(instances) == 1


@pytest.mark.parametrize("fail_at", ["open", "wait"])
def test_initialization_failure_closes_and_resets_pool(
    monkeypatch: pytest.MonkeyPatch,
    fail_at: str,
) -> None:
    events: list[tuple[Any, ...]] = []
    _install_factory(monkeypatch, events, fail_at=fail_at)

    with pytest.raises(PoolConfigurationError, match="initialiser le pool") as exc_info:
        pg_pool.get_pool(_settings())

    serialized_error = f"{exc_info.value!s} {exc_info.value!r}"
    assert "postgresql://secret@db/rag" not in serialized_error
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert events[-1] == ("close",)

    replacement_events: list[tuple[Any, ...]] = []
    replacement_instances = _install_factory(monkeypatch, replacement_events)
    assert pg_pool.get_pool(_settings()) is replacement_instances[0]


def test_factory_failure_resets_pool_and_masks_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_dsn = "postgresql://secret-user:secret-password@db.example/rag"

    def failing_factory(*args: Any, **kwargs: Any) -> FakePool:
        del args, kwargs
        raise RuntimeError(f"factory failed for {secret_dsn}")

    monkeypatch.setattr(pg_pool, "_pool_factory", failing_factory)

    with pytest.raises(PoolConfigurationError, match="initialiser le pool") as exc_info:
        pg_pool.get_pool(_settings(dsn=secret_dsn))

    serialized_error = f"{exc_info.value!s} {exc_info.value!r}"
    assert secret_dsn not in serialized_error
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None

    events: list[tuple[Any, ...]] = []
    instances = _install_factory(monkeypatch, events)
    assert pg_pool.get_pool(_settings(dsn=secret_dsn)) is instances[0]


def test_close_pool_is_idempotent_and_allows_recreation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    instances = _install_factory(monkeypatch, events)
    settings = _settings()
    first = pg_pool.get_pool(settings)

    pg_pool.close_pool()
    pg_pool.close_pool()
    second = pg_pool.get_pool(settings)

    assert first is instances[0]
    assert second is instances[1]
    assert events.count(("close",)) == 1
