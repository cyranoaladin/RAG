"""Paramètres PostgreSQL read-only communs aux sondes de readiness v2."""

from __future__ import annotations

from typing import Final

import psycopg

READINESS_CONNECT_TIMEOUT_S: Final = 3
READINESS_STATEMENT_TIMEOUT_MS: Final = 3000


def readiness_connection_options() -> str:
    """Retourner les options bornées et non mutantes du contrat de readiness."""
    return (
        f"-c statement_timeout={READINESS_STATEMENT_TIMEOUT_MS} "
        "-c default_transaction_read_only=on"
    )


def postgres_database_identity(dsn: str) -> tuple[str, str]:
    """Attester l'identifiant du cluster et le nom de base ciblés par un DSN."""
    with psycopg.connect(
        dsn,
        connect_timeout=READINESS_CONNECT_TIMEOUT_S,
        options=readiness_connection_options(),
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT system_identifier::text, current_database()
                FROM pg_control_system()
                """
            )
            row = cursor.fetchone()
    if (
        not isinstance(row, tuple)
        or len(row) != 2
        or not all(isinstance(value, str) and value.strip() for value in row)
    ):
        raise RuntimeError("database identity unavailable")
    return row[0], row[1]


__all__ = [
    "READINESS_CONNECT_TIMEOUT_S",
    "READINESS_STATEMENT_TIMEOUT_MS",
    "postgres_database_identity",
    "readiness_connection_options",
]
