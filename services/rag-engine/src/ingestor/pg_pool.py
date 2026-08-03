"""Pool PostgreSQL partagé pour le retrieval v2."""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from typing import Any, TypedDict

from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout, TooManyRequests


class PoolConfigurationError(RuntimeError):
    """Signale une configuration ou une initialisation de pool invalide."""


class RuntimeConnectionKwargs(TypedDict):
    """Arguments libpq bornés partagés par les connexions runtime."""

    connect_timeout: int
    options: str


COCKPIT_ENGINE_TIMEOUT_FLOOR_MS = 8_000
MAX_RUNTIME_DATABASE_BUDGET_MS = 6_000
_DEFAULT_RUNTIME_DATABASE_BUDGET_MS = 6_000
_MIN_RUNTIME_DATABASE_BUDGET_MS = 1_000
_DEFAULT_STATEMENT_TIMEOUT_MS = 3_000
_DEFAULT_LOCK_TIMEOUT_MS = 500
_DEFAULT_CONNECT_TIMEOUT_S = 1
_MAX_SERVER_TIMEOUT_MS = 60_000
_MAX_CONNECT_TIMEOUT_S = 30
_database_deadline: ContextVar[float | None] = ContextVar(
    "runtime_database_deadline",
    default=None,
)


def runtime_database_budget_ms_from_env() -> int:
    """Lire le budget SQL agrégé, toujours inférieur au délai minimal du BFF."""
    try:
        budget_ms = int(
            os.getenv(
                "PG_DATABASE_BUDGET_MS",
                str(_DEFAULT_RUNTIME_DATABASE_BUDGET_MS),
            )
        )
    except ValueError:
        raise PoolConfigurationError("Budget PostgreSQL invalide.") from None
    if not _MIN_RUNTIME_DATABASE_BUDGET_MS <= budget_ms <= MAX_RUNTIME_DATABASE_BUDGET_MS:
        raise PoolConfigurationError(
            "Budget PostgreSQL invalide: 1000 <= budget <= 6000 ms requis."
        )
    return budget_ms


@contextmanager
def runtime_database_budget(
    budget_ms: int | None = None,
) -> Iterator[float]:
    """Partager la deadline de requête entre inférences et phases SQL."""
    existing = _database_deadline.get()
    if existing is not None:
        yield existing
        return
    resolved_budget_ms = (
        runtime_database_budget_ms_from_env() if budget_ms is None else budget_ms
    )
    if not (
        _MIN_RUNTIME_DATABASE_BUDGET_MS
        <= resolved_budget_ms
        <= MAX_RUNTIME_DATABASE_BUDGET_MS
    ):
        raise PoolConfigurationError(
            "Budget PostgreSQL invalide: 1000 <= budget <= 6000 ms requis."
        )
    deadline = time.monotonic() + (resolved_budget_ms / 1_000.0)
    token: Token[float | None] = _database_deadline.set(deadline)
    try:
        yield deadline
    finally:
        _database_deadline.reset(token)


def remaining_database_budget_ms() -> int:
    """Retourner le reliquat de requête ou refuser une opération trop tardive."""
    deadline = _database_deadline.get()
    if deadline is None:
        return runtime_database_budget_ms_from_env()
    remaining_ms = math.ceil((deadline - time.monotonic()) * 1_000)
    if remaining_ms <= 0:
        raise PoolConfigurationError("Budget PostgreSQL épuisé.")
    return min(remaining_ms, MAX_RUNTIME_DATABASE_BUDGET_MS)


def current_runtime_request_deadline() -> float | None:
    """Exposer la deadline monotone active sans en créer une nouvelle."""
    return _database_deadline.get()


# Noms explicites utilisés par le retrieval. Les alias historiques restent
# l'API des primitives SQL et de review, mais partagent exactement le même
# ContextVar et donc une seule deadline monotone de bout en bout.
runtime_request_budget = runtime_database_budget
remaining_request_budget_ms = remaining_database_budget_ms


def bounded_database_wait_timeout_s(configured_timeout_s: float) -> float:
    """Borner une attente client par le reliquat de la requête courante."""
    if _database_deadline.get() is None:
        return configured_timeout_s
    return min(configured_timeout_s, remaining_database_budget_ms() / 1_000.0)


def execute_with_database_budget(
    cursor: Any,
    sql: str,
    params: object = None,
    *,
    statement_timeout_ms: int,
) -> Any:
    """Réduire statement_timeout au reliquat avant chaque instruction métier."""
    if _database_deadline.get() is not None:
        effective_timeout_ms = min(
            statement_timeout_ms,
            remaining_database_budget_ms(),
        )
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(effective_timeout_ms),),
        )
    return cursor.execute(sql, params)


def apply_database_budget_before_commit(
    connection: Any,
    *,
    statement_timeout_ms: int,
) -> None:
    """Borner aussi le COMMIT qui rend une décision de revue visible."""
    if _database_deadline.get() is None:
        return
    effective_timeout_ms = min(
        statement_timeout_ms,
        remaining_database_budget_ms(),
    )
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)",
            (str(effective_timeout_ms),),
        )


def _validate_runtime_timeouts(
    *,
    connect_timeout_s: int,
    statement_timeout_ms: int,
    lock_timeout_ms: int,
) -> None:
    if not 1 <= connect_timeout_s <= _MAX_CONNECT_TIMEOUT_S:
        raise PoolConfigurationError(
            "Délai de connexion PostgreSQL invalide: 1 <= connect <= 30 s requis."
        )
    if (
        not 1 <= statement_timeout_ms <= _MAX_SERVER_TIMEOUT_MS
        or not 1 <= lock_timeout_ms <= _MAX_SERVER_TIMEOUT_MS
        or lock_timeout_ms > statement_timeout_ms
    ):
        raise PoolConfigurationError(
            "Configuration des délais SQL invalide: "
            "1 <= lock <= statement <= 60000 ms requis."
        )


def _validate_runtime_budget_compatibility(
    *,
    database_budget_ms: int,
    connect_timeout_s: int,
    statement_timeout_ms: int,
    pool_timeout_s: float | None = None,
) -> None:
    if (
        connect_timeout_s * 1_000 > database_budget_ms
        or statement_timeout_ms > database_budget_ms
        or (
            pool_timeout_s is not None
            and pool_timeout_s * 1_000 > database_budget_ms
        )
    ):
        raise PoolConfigurationError(
            "Les délais PostgreSQL individuels doivent rester dans le budget "
            "PostgreSQL agrégé."
        )


def _runtime_timeouts_from_env() -> tuple[int, int, int]:
    values: tuple[int, int, int] | None = None
    try:
        values = (
            int(os.getenv("PG_CONNECT_TIMEOUT_S", str(_DEFAULT_CONNECT_TIMEOUT_S))),
            int(
                os.getenv(
                    "PG_STATEMENT_TIMEOUT_MS",
                    str(_DEFAULT_STATEMENT_TIMEOUT_MS),
                )
            ),
            int(os.getenv("PG_LOCK_TIMEOUT_MS", str(_DEFAULT_LOCK_TIMEOUT_MS))),
        )
    except ValueError:
        pass
    if values is None:
        raise PoolConfigurationError(
            "Paramètres numériques des délais PostgreSQL invalides."
        ) from None
    connect_timeout_s, statement_timeout_ms, lock_timeout_ms = values
    _validate_runtime_timeouts(
        connect_timeout_s=connect_timeout_s,
        statement_timeout_ms=statement_timeout_ms,
        lock_timeout_ms=lock_timeout_ms,
    )
    _validate_runtime_budget_compatibility(
        database_budget_ms=runtime_database_budget_ms_from_env(),
        connect_timeout_s=connect_timeout_s,
        statement_timeout_ms=statement_timeout_ms,
    )
    return values


def runtime_statement_timeout_ms_from_env() -> int:
    """Exposer la borne serveur canonique aux connexions directes de review."""
    return _runtime_timeouts_from_env()[1]


def runtime_connection_kwargs_from_env() -> RuntimeConnectionKwargs:
    """Partager les bornes réseau et SQL avec les connexions runtime directes."""
    connect_timeout_s, statement_timeout_ms, lock_timeout_ms = (
        _runtime_timeouts_from_env()
    )
    return {
        "connect_timeout": connect_timeout_s,
        "options": (
            f"-c statement_timeout={statement_timeout_ms} "
            f"-c lock_timeout={lock_timeout_ms}"
        ),
    }


@dataclass(frozen=True)
class PoolSettings:
    """Configuration immuable du pool PostgreSQL."""

    dsn: str = field(repr=False)
    min_size: int
    max_size: int
    timeout_s: float
    connect_timeout_s: int = _DEFAULT_CONNECT_TIMEOUT_S
    statement_timeout_ms: int = _DEFAULT_STATEMENT_TIMEOUT_MS
    lock_timeout_ms: int = _DEFAULT_LOCK_TIMEOUT_MS
    database_budget_ms: int = _DEFAULT_RUNTIME_DATABASE_BUDGET_MS

    def __post_init__(self) -> None:
        normalized_dsn = self.dsn.strip()
        if not normalized_dsn:
            raise PoolConfigurationError("DSN PostgreSQL requis pour le pool.")

        dsn_is_valid = True
        try:
            conninfo_to_dict(normalized_dsn)
        except Exception:
            dsn_is_valid = False
        if not dsn_is_valid:
            raise PoolConfigurationError("DSN PostgreSQL invalide pour le pool.") from None

        if not 1 <= self.min_size <= self.max_size <= 50:
            raise PoolConfigurationError(
                "Tailles du pool invalides: 1 <= min_size <= max_size <= 50 requis."
            )
        if not math.isfinite(self.timeout_s) or self.timeout_s <= 0:
            raise PoolConfigurationError("Délai du pool invalide: une valeur finie positive est requise.")
        _validate_runtime_timeouts(
            connect_timeout_s=self.connect_timeout_s,
            statement_timeout_ms=self.statement_timeout_ms,
            lock_timeout_ms=self.lock_timeout_ms,
        )
        if not (
            _MIN_RUNTIME_DATABASE_BUDGET_MS
            <= self.database_budget_ms
            <= MAX_RUNTIME_DATABASE_BUDGET_MS
        ):
            raise PoolConfigurationError(
                "Budget PostgreSQL invalide: 1000 <= budget <= 6000 ms requis."
            )
        _validate_runtime_budget_compatibility(
            database_budget_ms=self.database_budget_ms,
            connect_timeout_s=self.connect_timeout_s,
            statement_timeout_ms=self.statement_timeout_ms,
            pool_timeout_s=self.timeout_s,
        )
        object.__setattr__(self, "dsn", normalized_dsn)

    @classmethod
    def from_env(cls) -> PoolSettings:
        dsn = os.getenv("PG_RAG_DSN", "").strip()
        if not dsn:
            raise PoolConfigurationError("DSN PostgreSQL requis pour le pool.")

        parsed_values: tuple[int, int, float] | None = None
        try:
            parsed_values = (
                int(os.getenv("PG_POOL_MIN_SIZE", "1")),
                int(os.getenv("PG_POOL_MAX_SIZE", "10")),
                float(os.getenv("PG_POOL_TIMEOUT_S", "1.0")),
            )
        except ValueError:
            pass
        if parsed_values is None:
            raise PoolConfigurationError(
                "Paramètres numériques du pool PostgreSQL invalides."
            ) from None
        min_size, max_size, timeout_s = parsed_values
        connect_timeout_s, statement_timeout_ms, lock_timeout_ms = (
            _runtime_timeouts_from_env()
        )

        return cls(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout_s=timeout_s,
            connect_timeout_s=connect_timeout_s,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
            database_budget_ms=runtime_database_budget_ms_from_env(),
        )


_pool_lock = threading.Lock()
_pool: ConnectionPool[Any] | None = None
_pool_settings: PoolSettings | None = None
_pool_factory: Any = ConnectionPool


def get_pool(settings: PoolSettings) -> ConnectionPool[Any]:
    """Retourne le singleton initialisé pour les paramètres fournis."""
    global _pool, _pool_settings

    lock_timeout_s = bounded_database_wait_timeout_s(settings.timeout_s)
    if not _pool_lock.acquire(timeout=lock_timeout_s):
        raise PoolConfigurationError(
            "Impossible d'accéder au pool PostgreSQL dans le budget imparti."
        )
    try:
        if _pool is not None:
            if _pool_settings != settings:
                raise PoolConfigurationError(
                    "Un pool PostgreSQL actif utilise des paramètres différents."
                )
            return _pool

        created_pool: ConnectionPool[Any] | None = None
        initialization_failed = False
        try:
            pool_result: ConnectionPool[Any] = _pool_factory(
                settings.dsn,
                min_size=settings.min_size,
                max_size=settings.max_size,
                timeout=settings.timeout_s,
                open=False,
                kwargs={
                    "connect_timeout": settings.connect_timeout_s,
                    "options": (
                        "-c default_transaction_read_only=on "
                        f"-c statement_timeout={settings.statement_timeout_ms} "
                        f"-c lock_timeout={settings.lock_timeout_ms}"
                    )
                },
            )
            created_pool = pool_result
            pool_result.open(wait=False)
            pool_result.wait(
                timeout=bounded_database_wait_timeout_s(settings.timeout_s)
            )
        except Exception:
            initialization_failed = True
            if created_pool is not None:
                try:
                    created_pool.close()
                except Exception:
                    pass
            _pool = None
            _pool_settings = None

        if initialization_failed:
            raise PoolConfigurationError("Impossible d'initialiser le pool PostgreSQL.") from None
        if created_pool is None:  # pragma: no cover - garde défensive de typage
            raise PoolConfigurationError("Impossible d'initialiser le pool PostgreSQL.")

        _pool = created_pool
        _pool_settings = settings
        return created_pool
    finally:
        _pool_lock.release()


@contextmanager
def pool_connection(settings: PoolSettings | None = None) -> Iterator[Any]:
    """Emprunte une connexion sans conserver le verrou global pendant son usage."""
    resolved_settings = settings if settings is not None else PoolSettings.from_env()
    pool = get_pool(resolved_settings)
    stack = ExitStack()
    connection: Any = None
    acquisition_failed = False
    try:
        connection = stack.enter_context(
            pool.connection(
                timeout=bounded_database_wait_timeout_s(
                    resolved_settings.timeout_s
                )
            )
        )
    except (PoolTimeout, PoolClosed, TooManyRequests):
        acquisition_failed = True

    if acquisition_failed:
        stack.close()
        raise PoolConfigurationError(
            "Impossible d'emprunter une connexion PostgreSQL au pool."
        ) from None

    with stack:
        yield connection


def close_pool() -> None:
    """Ferme et oublie le singleton courant; l'appel est idempotent."""
    global _pool, _pool_settings

    with _pool_lock:
        pool = _pool
        _pool = None
        _pool_settings = None

    if pool is not None:
        close_failed = False
        try:
            pool.close()
        except Exception:
            close_failed = True
        if close_failed:
            raise PoolConfigurationError("Impossible de fermer le pool PostgreSQL.") from None
