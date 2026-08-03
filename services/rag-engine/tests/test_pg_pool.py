"""Tests du pool PostgreSQL partagé du retrieval v2."""

from __future__ import annotations

import importlib
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from psycopg import ProgrammingError
from psycopg_pool import PoolClosed, PoolTimeout, TooManyRequests

from ingestor import pg_pool
from ingestor.pg_pool import PoolConfigurationError, PoolSettings

_ENV_KEYS = (
    "PG_RAG_DSN",
    "DATABASE_URL_SYNC",
    "PG_POOL_MIN_SIZE",
    "PG_POOL_MAX_SIZE",
    "PG_POOL_TIMEOUT_S",
    "PG_CONNECT_TIMEOUT_S",
    "PG_STATEMENT_TIMEOUT_MS",
    "PG_LOCK_TIMEOUT_MS",
    "PG_DATABASE_BUDGET_MS",
)
_ENGINE_ROOT = Path(__file__).resolve().parents[1]
_THREE_PSYCOPG_PINS = {
    "psycopg==3.2.1",
    "psycopg-binary==3.2.1",
    "psycopg-pool==3.2.1",
}


def _secret_dsn(
    *, host: str = "db.example", password: str = "secret-password"
) -> str:
    return "".join(("postgresql://", "secret-user", ":", password, "@", host, "/rag"))


def test_secret_dsn_reconstructs_historical_fixture_values() -> None:
    assert _secret_dsn() == "".join(
        ("postgresql://secret-user:", "secret-password@db.example/rag")
    )
    assert _secret_dsn(password="secret-password%zz") == "".join(
        ("postgresql://secret-user:", "secret-password%zz@db.example/rag")
    )
    assert _secret_dsn(host="other.example") == "".join(
        ("postgresql://secret-user:", "secret-password@other.example/rag")
    )


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
        timeout_s=1.0,
    )


def test_from_env_refuses_owner_dsn_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PG_RAG_DSN", " \t")
    monkeypatch.setenv("DATABASE_URL_SYNC", "  postgresql://fallback.example/rag ")

    with pytest.raises(PoolConfigurationError, match="DSN PostgreSQL requis"):
        PoolSettings.from_env()


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
    monkeypatch.setenv("PG_CONNECT_TIMEOUT_S", "4")
    monkeypatch.setenv("PG_STATEMENT_TIMEOUT_MS", "5500")
    monkeypatch.setenv("PG_LOCK_TIMEOUT_MS", "750")

    assert PoolSettings.from_env() == PoolSettings(
        dsn="postgresql://db.example/rag",
        min_size=2,
        max_size=25,
        timeout_s=0.75,
        connect_timeout_s=4,
        statement_timeout_ms=5500,
        lock_timeout_ms=750,
    )


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("PG_POOL_MIN_SIZE", "not-an-int"),
        ("PG_POOL_MAX_SIZE", "1.5"),
        ("PG_POOL_TIMEOUT_S", "not-a-float"),
        ("PG_CONNECT_TIMEOUT_S", "1.5"),
        ("PG_STATEMENT_TIMEOUT_MS", "1.5"),
        ("PG_LOCK_TIMEOUT_MS", "not-an-int"),
    ],
)
def test_from_env_rejects_unparseable_pool_values(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: str,
) -> None:
    dsn = _secret_dsn()
    monkeypatch.setenv("PG_RAG_DSN", dsn)
    monkeypatch.setenv(key, value)

    with pytest.raises(PoolConfigurationError) as exc_info:
        PoolSettings.from_env()

    serialized_error = f"{exc_info.value!s} {exc_info.value!r}"
    assert dsn not in serialized_error
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


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


@pytest.mark.parametrize(
    ("statement_timeout_ms", "lock_timeout_ms"),
    [
        (0, 1),
        (60_001, 1),
        (7_000, 0),
        (7_000, 60_001),
        (1_000, 1_001),
    ],
)
def test_settings_reject_invalid_server_side_timeouts(
    statement_timeout_ms: int,
    lock_timeout_ms: int,
) -> None:
    with pytest.raises(PoolConfigurationError, match="délais SQL"):
        PoolSettings(
            dsn="postgresql://db.example/rag",
            min_size=1,
            max_size=10,
            timeout_s=5.0,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
        )


@pytest.mark.parametrize("connect_timeout_s", (0, 31))
def test_settings_reject_invalid_connect_timeout(connect_timeout_s: int) -> None:
    with pytest.raises(PoolConfigurationError, match="connexion PostgreSQL"):
        PoolSettings(
            dsn="postgresql://db.example/rag",
            min_size=1,
            max_size=10,
            timeout_s=5.0,
            connect_timeout_s=connect_timeout_s,
        )


def test_direct_connection_kwargs_share_the_runtime_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_CONNECT_TIMEOUT_S", "4")
    monkeypatch.setenv("PG_STATEMENT_TIMEOUT_MS", "5500")
    monkeypatch.setenv("PG_LOCK_TIMEOUT_MS", "750")

    assert pg_pool.runtime_connection_kwargs_from_env() == {
        "connect_timeout": 4,
        "options": "-c statement_timeout=5500 -c lock_timeout=750",
    }


def test_database_budget_is_strictly_below_the_cockpit_bff_deadline() -> None:
    assert pg_pool.MAX_RUNTIME_DATABASE_BUDGET_MS == 6_000
    assert pg_pool.COCKPIT_ENGINE_TIMEOUT_FLOOR_MS == 8_000
    assert (
        pg_pool.MAX_RUNTIME_DATABASE_BUDGET_MS
        < pg_pool.COCKPIT_ENGINE_TIMEOUT_FLOOR_MS
    )


@pytest.mark.parametrize("value", ("0", "999", "6001", "not-an-int"))
def test_runtime_database_budget_rejects_unsafe_values(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("PG_DATABASE_BUDGET_MS", value)

    with pytest.raises(PoolConfigurationError, match="Budget PostgreSQL"):
        pg_pool.runtime_database_budget_ms_from_env()


def test_runtime_database_budget_accepts_libpq_minimum(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PG_DATABASE_BUDGET_MS", "1000")

    assert pg_pool.runtime_database_budget_ms_from_env() == 1_000


def test_runtime_database_budget_is_shared_by_nested_operations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter((10.0, 10.5, 11.0))
    monkeypatch.setattr(pg_pool.time, "monotonic", lambda: next(moments))

    with pg_pool.runtime_database_budget(2_000) as outer:
        assert pg_pool.remaining_database_budget_ms() == 1_500
        with pg_pool.runtime_database_budget(1_000) as nested:
            assert nested is outer
            assert pg_pool.remaining_database_budget_ms() == 1_000


def test_runtime_database_budget_fails_after_its_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter((10.0, 16.1))
    monkeypatch.setattr(pg_pool.time, "monotonic", lambda: next(moments))

    with pg_pool.runtime_database_budget(6_000):
        with pytest.raises(PoolConfigurationError, match="Budget PostgreSQL épuisé"):
            pg_pool.remaining_database_budget_ms()


def test_each_sql_statement_is_rebounded_to_the_aggregate_remainder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    moments = iter((10.0, 10.5))
    monkeypatch.setattr(pg_pool.time, "monotonic", lambda: next(moments))
    executions: list[tuple[str, object]] = []

    class Cursor:
        def execute(self, sql: str, params: object = None) -> None:
            executions.append((sql, params))

    with pg_pool.runtime_database_budget(2_000):
        pg_pool.execute_with_database_budget(
            Cursor(),
            "SELECT business_data FROM bounded_view",
            ("scope",),
            statement_timeout_ms=3_000,
        )

    assert executions == [
        (
            "SELECT set_config('statement_timeout', %s, true)",
            ("1500",),
        ),
        ("SELECT business_data FROM bounded_view", ("scope",)),
    ]


@pytest.mark.parametrize("dsn", ["", " ", "\t"])
def test_settings_reject_blank_dsn_without_leaking_it(dsn: str) -> None:
    with pytest.raises(PoolConfigurationError, match="DSN PostgreSQL requis"):
        PoolSettings(dsn=dsn, min_size=1, max_size=10, timeout_s=5.0)


def test_settings_accept_boundary_values() -> None:
    PoolSettings(
        dsn="postgresql://db.example/rag", min_size=1, max_size=50, timeout_s=0.001
    )
    PoolSettings(
        dsn="postgresql://db.example/rag",
        min_size=1,
        max_size=1,
        timeout_s=1.0,
        statement_timeout_ms=6_000,
        lock_timeout_ms=6_000,
    )


def test_settings_repr_never_contains_dsn_or_password() -> None:
    dsn = _secret_dsn()

    settings = PoolSettings(dsn=dsn, min_size=1, max_size=10, timeout_s=5.0)

    serialized_settings = f"{settings!s} {settings!r}"
    assert dsn not in serialized_settings
    assert "secret-password" not in serialized_settings


def test_malformed_dsn_is_rejected_before_pool_factory_without_leak(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    malformed_dsn = _secret_dsn(password="secret-password%zz")
    factory_called = False

    def forbidden_factory(*args: Any, **kwargs: Any) -> Any:
        nonlocal factory_called
        del args, kwargs
        factory_called = True
        raise AssertionError("la factory ne doit pas être appelée")

    monkeypatch.setattr(pg_pool, "_pool_factory", forbidden_factory)

    with pytest.raises(PoolConfigurationError, match="DSN PostgreSQL invalide") as exc_info:
        pg_pool.get_pool(
            PoolSettings(dsn=malformed_dsn, min_size=1, max_size=10, timeout_s=5.0)
        )

    serialized_error = f"{exc_info.value!s} {exc_info.value!r}"
    assert factory_called is False
    assert malformed_dsn not in serialized_error
    assert "secret-password" not in serialized_error
    assert "secret-password" not in caplog.text
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None


def test_each_runtime_manifest_has_its_exact_psycopg_pins() -> None:
    expected_by_manifest = {
        _ENGINE_ROOT / "requirements.lock": _THREE_PSYCOPG_PINS,
        _ENGINE_ROOT / "src/ingestor/requirements.runtime-v2.txt": _THREE_PSYCOPG_PINS,
        _ENGINE_ROOT / "src/ingestor/requirements.v2.txt": _THREE_PSYCOPG_PINS,
        _ENGINE_ROOT / "src/ingestor/requirements.txt": _THREE_PSYCOPG_PINS,
        _ENGINE_ROOT / "src/backend/requirements.txt": {
            "psycopg==3.2.1",
            "psycopg-binary==3.2.1",
        },
    }

    for manifest, expected in expected_by_manifest.items():
        entries = [
            line.strip()
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip().startswith("psycopg")
        ]
        assert len(entries) == len(set(entries)), manifest.relative_to(_ENGINE_ROOT)
        assert set(entries) == expected, manifest.relative_to(_ENGINE_ROOT)


def test_ingestor_v2_image_installs_only_the_checked_runtime_manifest() -> None:
    dockerfile = (_ENGINE_ROOT / "infra/Dockerfile.ingestor-v2").read_text(encoding="utf-8")

    assert (
        "COPY services/rag-engine/src/ingestor/requirements.runtime-v2.txt "
        "/tmp/requirements.runtime-v2.txt"
        in dockerfile
    )
    assert "pip install --no-cache-dir -r /tmp/requirements.runtime-v2.txt" in dockerfile
    assert "/tmp/requirements.txt" not in dockerfile
    assert "/tmp/requirements.v2.txt" not in dockerfile


def test_pg_pool_module_imports_with_runtime_dependencies() -> None:
    assert importlib.import_module("ingestor.pg_pool") is pg_pool


class FakePool:
    def __init__(
        self,
        events: list[tuple[Any, ...]],
        *,
        fail_at: str | None = None,
        connection_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.fail_at = fail_at
        self.connection_error = connection_error

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
        self.events.append(("connection-attempt", timeout))
        if self.connection_error is not None:
            raise self.connection_error
        self.events.append(("connection-enter", timeout))
        try:
            yield "connection"
        finally:
            self.events.append(("connection-exit", timeout))

    def close(self) -> None:
        self.events.append(("close",))


def _settings(*, dsn: str = "postgresql://db.example/rag") -> PoolSettings:
    return PoolSettings(
        dsn=dsn,
        min_size=2,
        max_size=8,
        timeout_s=1.25,
        connect_timeout_s=4,
        statement_timeout_ms=5_500,
        lock_timeout_ms=750,
    )


def _install_factory(
    monkeypatch: pytest.MonkeyPatch,
    events: list[tuple[Any, ...]],
    *,
    fail_at: str | None = None,
    connection_error: Exception | None = None,
) -> list[FakePool]:
    instances: list[FakePool] = []

    def factory(conninfo: str, **kwargs: Any) -> FakePool:
        events.append(("construct", conninfo, kwargs))
        pool = FakePool(events, fail_at=fail_at, connection_error=connection_error)
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
                "kwargs": {
                    "connect_timeout": 4,
                    "options": (
                        "-c default_transaction_read_only=on "
                        "-c statement_timeout=5500 -c lock_timeout=750"
                    ),
                },
            },
        ),
        ("open", False),
        ("wait", 1.25),
    ]


def test_get_pool_publishes_one_instance_under_24_concurrent_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    instances = _install_factory(monkeypatch, events)
    settings = _settings()
    start = threading.Barrier(24)

    def get_after_barrier() -> Any:
        start.wait(timeout=5)
        return pg_pool.get_pool(settings)

    with ThreadPoolExecutor(max_workers=24) as executor:
        pools = list(executor.map(lambda _: get_after_barrier(), range(24)))

    assert len(instances) == 1
    assert all(pool is instances[0] for pool in pools)
    assert sum(event[0] == "construct" for event in events) == 1

    pg_pool.close_pool()
    assert events.count(("close",)) == 1


def test_pool_connection_uses_configured_acquisition_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    _install_factory(monkeypatch, events)
    settings = _settings()

    with pg_pool.pool_connection(settings) as connection:
        assert connection == "connection"

    assert events[-3:] == [
        ("connection-attempt", 1.25),
        ("connection-enter", 1.25),
        ("connection-exit", 1.25),
    ]


def test_pool_connection_loads_settings_from_environment_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    _install_factory(monkeypatch, events)
    monkeypatch.setenv("PG_RAG_DSN", "postgresql://db.example/rag")

    with pg_pool.pool_connection() as connection:
        assert connection == "connection"

    assert events[-3:] == [
        ("connection-attempt", 1.0),
        ("connection-enter", 1.0),
        ("connection-exit", 1.0),
    ]


@pytest.mark.parametrize("error_type", [PoolTimeout, PoolClosed, TooManyRequests])
def test_pool_connection_masks_only_acquisition_pool_errors(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error_type: type[Exception],
) -> None:
    secret = _secret_dsn()
    acquisition_error = error_type(f"acquisition failed for {secret}")
    events: list[tuple[Any, ...]] = []
    _install_factory(monkeypatch, events, connection_error=acquisition_error)

    with pytest.raises(PoolConfigurationError, match="emprunter une connexion") as exc_info:
        with pg_pool.pool_connection(_settings(dsn=secret)):
            pytest.fail("le corps ne doit pas être exécuté")

    serialized_error = f"{exc_info.value!s} {exc_info.value!r}"
    assert secret not in serialized_error
    assert "secret-password" not in caplog.text
    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
    assert events[-1] == ("connection-attempt", 1.25)


@pytest.mark.parametrize(
    "body_error",
    [PoolTimeout("timeout après acquisition"), ProgrammingError("erreur SQL du corps")],
)
def test_pool_connection_preserves_body_exception_identity(
    monkeypatch: pytest.MonkeyPatch,
    body_error: Exception,
) -> None:
    events: list[tuple[Any, ...]] = []
    _install_factory(monkeypatch, events)
    acquired = False

    with pytest.raises(type(body_error)) as exc_info:
        with pg_pool.pool_connection(_settings()):
            acquired = True
            raise body_error

    assert acquired is True
    assert exc_info.value is body_error
    assert ("connection-enter", 1.25) in events
    assert events[-1] == ("connection-exit", 1.25)


def test_get_pool_refuses_different_settings_without_leaking_dsn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[Any, ...]] = []
    instances = _install_factory(monkeypatch, events)
    pg_pool.get_pool(_settings())
    other_dsn = _secret_dsn(host="other.example")

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
    secret_dsn = _secret_dsn()

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
