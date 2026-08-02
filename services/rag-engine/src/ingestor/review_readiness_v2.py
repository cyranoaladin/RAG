"""Sonde read-only du rôle PostgreSQL dédié à la revue humaine v2."""

from __future__ import annotations

from typing import Final

import psycopg

try:
    from .readiness_db import (
        READINESS_CONNECT_TIMEOUT_S,
        READINESS_STATEMENT_TIMEOUT_MS,
        readiness_connection_options,
    )
except ImportError:  # Image Docker aplatie sous /app.
    from readiness_db import (  # type: ignore[no-redef]
        READINESS_CONNECT_TIMEOUT_S,
        READINESS_STATEMENT_TIMEOUT_MS,
        readiness_connection_options,
    )

_REQUIRED_REVIEW_PRIVILEGES: Final = (
    True,  # SELECT sur rag_chunks
    False,  # pas d'INSERT
    False,  # pas de DELETE
    False,  # pas de TRUNCATE
    False,  # pas d'UPDATE au niveau table
    True,  # UPDATE limité à review_status
    True,  # aucune autre colonne modifiable
    False,  # aucune appartenance au rôle propriétaire
    False,  # pas superuser
    False,  # pas CREATEDB
    False,  # pas CREATEROLE
    False,  # pas REPLICATION
    False,  # pas BYPASSRLS
    True,  # USAGE requis sur le schéma public
    False,  # pas CREATE sur le schéma public
    False,  # pas CREATE sur la base
    False,  # pas de tables temporaires
)

_REVIEW_PRIVILEGES_SQL = """
SELECT
    has_table_privilege(current_user, 'public.rag_chunks', 'SELECT'),
    has_table_privilege(current_user, 'public.rag_chunks', 'INSERT'),
    has_table_privilege(current_user, 'public.rag_chunks', 'DELETE'),
    has_table_privilege(current_user, 'public.rag_chunks', 'TRUNCATE'),
    has_table_privilege(current_user, 'public.rag_chunks', 'UPDATE'),
    has_column_privilege(
        current_user, 'public.rag_chunks', 'review_status', 'UPDATE'
    ),
    NOT EXISTS (
        SELECT 1
        FROM pg_attribute AS forbidden_column
        WHERE forbidden_column.attrelid = 'public.rag_chunks'::regclass
          AND forbidden_column.attnum > 0
          AND NOT forbidden_column.attisdropped
          AND forbidden_column.attname <> 'review_status'
          AND has_column_privilege(
              current_user,
              'public.rag_chunks',
              forbidden_column.attname,
              'UPDATE'
          )
    ),
    pg_has_role(current_user, tableowner, 'USAGE'),
    rolsuper,
    rolcreatedb,
    rolcreaterole,
    rolreplication,
    rolbypassrls,
    has_schema_privilege(current_user, 'public', 'USAGE'),
    has_schema_privilege(current_user, 'public', 'CREATE'),
    has_database_privilege(current_user, current_database(), 'CREATE'),
    has_database_privilege(current_user, current_database(), 'TEMP')
FROM pg_tables
JOIN pg_roles ON rolname = current_user
WHERE schemaname = 'public' AND tablename = 'rag_chunks'
"""


def review_database_ready(dsn: str) -> bool:
    """Prouver la connexion et le moindre privilège attendu du rôle review."""
    with psycopg.connect(
        dsn,
        connect_timeout=READINESS_CONNECT_TIMEOUT_S,
        options=readiness_connection_options(),
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_REVIEW_PRIVILEGES_SQL)
            row = cursor.fetchone()
    return row == _REQUIRED_REVIEW_PRIVILEGES


__all__ = [
    "READINESS_CONNECT_TIMEOUT_S",
    "READINESS_STATEMENT_TIMEOUT_MS",
    "review_database_ready",
]
