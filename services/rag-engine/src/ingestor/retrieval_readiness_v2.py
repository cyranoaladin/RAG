"""Sonde read-only du rôle PostgreSQL dédié au retrieval v2."""

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

_REQUIRED_RETRIEVAL_PRIVILEGES: Final = (
    True,  # SELECT sur rag_chunks
    False,  # pas d'INSERT
    False,  # pas d'UPDATE
    False,  # pas de DELETE
    False,  # pas de TRUNCATE
    False,  # pas de REFERENCES
    False,  # pas de TRIGGER
    True,  # SELECT sur le registre des migrations
    False,  # pas d'INSERT sur le registre
    False,  # pas d'UPDATE sur le registre
    False,  # pas de DELETE sur le registre
    False,  # pas de TRUNCATE sur le registre
    False,  # pas de REFERENCES sur le registre
    False,  # pas de TRIGGER sur le registre
    False,  # aucune appartenance au propriétaire de rag_chunks
    False,  # aucune appartenance au propriétaire du registre
    False,  # pas superuser
    False,  # pas CREATEDB
    False,  # pas CREATEROLE
    False,  # pas REPLICATION
    False,  # pas BYPASSRLS
    True,  # USAGE requis sur le schéma public
    False,  # pas CREATE sur le schéma public
    False,  # pas CREATE sur la base
    False,  # pas de tables temporaires
    True,  # USAGE requis sur le type vector
)

_RETRIEVAL_PRIVILEGES_SQL = """
SELECT
    has_table_privilege(current_user, 'public.rag_chunks', 'SELECT'),
    has_table_privilege(current_user, 'public.rag_chunks', 'INSERT'),
    has_table_privilege(current_user, 'public.rag_chunks', 'UPDATE'),
    has_table_privilege(current_user, 'public.rag_chunks', 'DELETE'),
    has_table_privilege(current_user, 'public.rag_chunks', 'TRUNCATE'),
    has_table_privilege(current_user, 'public.rag_chunks', 'REFERENCES'),
    has_table_privilege(current_user, 'public.rag_chunks', 'TRIGGER'),
    has_table_privilege(current_user, 'public.rag_schema_migrations', 'SELECT'),
    has_table_privilege(current_user, 'public.rag_schema_migrations', 'INSERT'),
    has_table_privilege(current_user, 'public.rag_schema_migrations', 'UPDATE'),
    has_table_privilege(current_user, 'public.rag_schema_migrations', 'DELETE'),
    has_table_privilege(current_user, 'public.rag_schema_migrations', 'TRUNCATE'),
    has_table_privilege(current_user, 'public.rag_schema_migrations', 'REFERENCES'),
    has_table_privilege(current_user, 'public.rag_schema_migrations', 'TRIGGER'),
    pg_has_role(
        current_user,
        (
            SELECT tableowner
            FROM pg_tables
            WHERE schemaname = 'public' AND tablename = 'rag_chunks'
        ),
        'USAGE'
    ),
    pg_has_role(
        current_user,
        (
            SELECT tableowner
            FROM pg_tables
            WHERE schemaname = 'public' AND tablename = 'rag_schema_migrations'
        ),
        'USAGE'
    ),
    rolsuper,
    rolcreatedb,
    rolcreaterole,
    rolreplication,
    rolbypassrls,
    has_schema_privilege(current_user, 'public', 'USAGE'),
    has_schema_privilege(current_user, 'public', 'CREATE'),
    has_database_privilege(current_user, current_database(), 'CREATE'),
    has_database_privilege(current_user, current_database(), 'TEMP'),
    has_type_privilege(current_user, 'public.vector', 'USAGE')
FROM pg_roles
WHERE rolname = current_user
"""


def retrieval_database_ready(dsn: str) -> bool:
    """Prouver la connexion et le contrat exact du rôle de lecture."""
    with psycopg.connect(
        dsn,
        connect_timeout=READINESS_CONNECT_TIMEOUT_S,
        options=readiness_connection_options(),
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_RETRIEVAL_PRIVILEGES_SQL)
            row = cursor.fetchone()
    return row == _REQUIRED_RETRIEVAL_PRIVILEGES


__all__ = [
    "READINESS_CONNECT_TIMEOUT_S",
    "READINESS_STATEMENT_TIMEOUT_MS",
    "retrieval_database_ready",
]
