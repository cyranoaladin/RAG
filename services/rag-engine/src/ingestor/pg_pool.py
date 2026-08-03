"""Pool PostgreSQL partagé pour le retrieval v2."""

from __future__ import annotations

import math
import os
import threading
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field
from typing import Any

from psycopg.conninfo import conninfo_to_dict
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout, TooManyRequests


class PoolConfigurationError(RuntimeError):
    """Signale une configuration ou une initialisation de pool invalide."""


_DEFAULT_STATEMENT_TIMEOUT_MS = 7_000
_DEFAULT_LOCK_TIMEOUT_MS = 1_000
_MAX_SERVER_TIMEOUT_MS = 60_000


@dataclass(frozen=True)
class PoolSettings:
    """Configuration immuable du pool PostgreSQL."""

    dsn: str = field(repr=False)
    min_size: int
    max_size: int
    timeout_s: float
    statement_timeout_ms: int = _DEFAULT_STATEMENT_TIMEOUT_MS
    lock_timeout_ms: int = _DEFAULT_LOCK_TIMEOUT_MS

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
        if (
            not 1 <= self.statement_timeout_ms <= _MAX_SERVER_TIMEOUT_MS
            or not 1 <= self.lock_timeout_ms <= _MAX_SERVER_TIMEOUT_MS
            or self.lock_timeout_ms > self.statement_timeout_ms
        ):
            raise PoolConfigurationError(
                "Configuration des délais SQL invalide: 1 <= lock <= statement <= 60000 ms requis."
            )
        object.__setattr__(self, "dsn", normalized_dsn)

    @classmethod
    def from_env(cls) -> PoolSettings:
        dsn = os.getenv("PG_RAG_DSN", "").strip()
        if not dsn:
            raise PoolConfigurationError("DSN PostgreSQL requis pour le pool.")

        parsed_values: tuple[int, int, float, int, int] | None = None
        try:
            parsed_values = (
                int(os.getenv("PG_POOL_MIN_SIZE", "1")),
                int(os.getenv("PG_POOL_MAX_SIZE", "10")),
                float(os.getenv("PG_POOL_TIMEOUT_S", "5.0")),
                int(
                    os.getenv(
                        "PG_STATEMENT_TIMEOUT_MS",
                        str(_DEFAULT_STATEMENT_TIMEOUT_MS),
                    )
                ),
                int(
                    os.getenv(
                        "PG_LOCK_TIMEOUT_MS",
                        str(_DEFAULT_LOCK_TIMEOUT_MS),
                    )
                ),
            )
        except ValueError:
            pass
        if parsed_values is None:
            raise PoolConfigurationError(
                "Paramètres numériques du pool PostgreSQL invalides."
            ) from None
        min_size, max_size, timeout_s, statement_timeout_ms, lock_timeout_ms = (
            parsed_values
        )

        return cls(
            dsn=dsn,
            min_size=min_size,
            max_size=max_size,
            timeout_s=timeout_s,
            statement_timeout_ms=statement_timeout_ms,
            lock_timeout_ms=lock_timeout_ms,
        )


_pool_lock = threading.Lock()
_pool: ConnectionPool[Any] | None = None
_pool_settings: PoolSettings | None = None
_pool_factory: Any = ConnectionPool


def get_pool(settings: PoolSettings) -> ConnectionPool[Any]:
    """Retourne le singleton initialisé pour les paramètres fournis."""
    global _pool, _pool_settings

    with _pool_lock:
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
                    "options": (
                        "-c default_transaction_read_only=on "
                        f"-c statement_timeout={settings.statement_timeout_ms} "
                        f"-c lock_timeout={settings.lock_timeout_ms}"
                    )
                },
            )
            created_pool = pool_result
            pool_result.open(wait=False)
            pool_result.wait(timeout=settings.timeout_s)
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
            pool.connection(timeout=resolved_settings.timeout_s)
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
