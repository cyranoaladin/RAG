"""Paramètres PostgreSQL read-only communs aux sondes de readiness v2."""

from __future__ import annotations

from typing import Final

READINESS_CONNECT_TIMEOUT_S: Final = 3
READINESS_STATEMENT_TIMEOUT_MS: Final = 3000


def readiness_connection_options() -> str:
    """Retourner les options bornées et non mutantes du contrat de readiness."""
    return (
        f"-c statement_timeout={READINESS_STATEMENT_TIMEOUT_MS} "
        "-c default_transaction_read_only=on"
    )


__all__ = [
    "READINESS_CONNECT_TIMEOUT_S",
    "READINESS_STATEMENT_TIMEOUT_MS",
    "readiness_connection_options",
]
