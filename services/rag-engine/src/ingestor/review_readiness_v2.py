"""Sonde read-only du rôle PostgreSQL dédié à la revue humaine v2."""

from __future__ import annotations

from typing import Final

import psycopg

try:
    from .readiness_db import (
        READINESS_CONNECT_TIMEOUT_S,
        READINESS_STATEMENT_TIMEOUT_MS,
        RUNTIME_RELATION_ALLOWLIST,
        apply_readiness_statement_budget,
        no_auxiliary_relation_privileges_sql,
        no_executable_security_definer_routines_sql,
        no_user_schema_create_privileges_sql,
        readiness_connect_timeout_s,
        readiness_connection_options,
    )
except ImportError:  # Image Docker aplatie sous /app.
    from readiness_db import (  # type: ignore[no-redef]
        READINESS_CONNECT_TIMEOUT_S,
        READINESS_STATEMENT_TIMEOUT_MS,
        RUNTIME_RELATION_ALLOWLIST,
        apply_readiness_statement_budget,
        no_auxiliary_relation_privileges_sql,
        no_executable_security_definer_routines_sql,
        no_user_schema_create_privileges_sql,
        readiness_connect_timeout_s,
        readiness_connection_options,
    )

_REQUIRED_REVIEW_PRIVILEGES: Final = (
    True,  # SELECT sur rag_chunks
    False,  # pas d'INSERT au niveau table
    True,  # aucune colonne ne permet INSERT
    False,  # pas de DELETE
    False,  # pas de TRUNCATE
    False,  # pas de TRIGGER
    True,  # aucune colonne ne permet REFERENCES
    False,  # pas d'UPDATE au niveau table
    True,  # UPDATE limité à review_status
    True,  # aucune autre colonne modifiable
    False,  # aucune appartenance au rôle propriétaire
    False,  # aucun rôle atteignable par SET ROLE
    False,  # pas superuser
    False,  # pas CREATEDB
    False,  # pas CREATEROLE
    False,  # pas REPLICATION
    False,  # pas BYPASSRLS
    True,  # USAGE requis sur le schéma public
    False,  # pas CREATE sur le schéma public
    False,  # pas CREATE sur la base
    False,  # pas de tables temporaires
    True,  # aucun SELECT sur le registre des migrations
    True,  # aucun INSERT sur le registre des migrations
    True,  # aucun UPDATE sur le registre des migrations
    True,  # aucune REFERENCES sur le registre des migrations
    False,  # pas de DELETE sur le registre des migrations
    False,  # pas de TRUNCATE sur le registre des migrations
    False,  # pas de TRIGGER sur le registre des migrations
    False,  # aucune appartenance au propriétaire du registre
    True,  # aucun privilège effectif sur une relation hors allowlist
    True,  # aucune routine utilisateur SECURITY DEFINER exécutable
    True,  # aucun CREATE ni ownership sur un schéma utilisateur
)

_REVIEW_PRIVILEGES_SQL = f"""
SELECT
    has_table_privilege(current_user, 'public.rag_chunks', 'SELECT'),
    has_table_privilege(current_user, 'public.rag_chunks', 'INSERT'),
    NOT EXISTS (
        SELECT 1
        FROM pg_attribute AS insertable_column
        WHERE insertable_column.attrelid = 'public.rag_chunks'::regclass
          AND insertable_column.attnum > 0
          AND NOT insertable_column.attisdropped
          AND has_column_privilege(
              current_user,
              'public.rag_chunks',
              insertable_column.attname,
              'INSERT'
          )
    ),
    has_table_privilege(current_user, 'public.rag_chunks', 'DELETE'),
    has_table_privilege(current_user, 'public.rag_chunks', 'TRUNCATE'),
    has_table_privilege(current_user, 'public.rag_chunks', 'TRIGGER'),
    NOT has_any_column_privilege(
        current_user, 'public.rag_chunks', 'REFERENCES'
    ),
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
    pg_has_role(current_user, tableowner, 'MEMBER'),
    EXISTS (
        SELECT 1
        FROM pg_roles AS reachable_role
        WHERE reachable_role.oid <> current_user::regrole
          AND pg_has_role(current_user, reachable_role.oid, 'MEMBER')
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
    NOT has_any_column_privilege(
        current_user, 'public.rag_schema_migrations', 'SELECT'
    ),
    NOT has_any_column_privilege(
        current_user, 'public.rag_schema_migrations', 'INSERT'
    ),
    NOT has_any_column_privilege(
        current_user, 'public.rag_schema_migrations', 'UPDATE'
    ),
    NOT has_any_column_privilege(
        current_user, 'public.rag_schema_migrations', 'REFERENCES'
    ),
    has_table_privilege(
        current_user, 'public.rag_schema_migrations', 'DELETE'
    ),
    has_table_privilege(
        current_user, 'public.rag_schema_migrations', 'TRUNCATE'
    ),
    has_table_privilege(
        current_user, 'public.rag_schema_migrations', 'TRIGGER'
    ),
    pg_has_role(
        current_user,
        (
            SELECT tableowner::regrole
            FROM pg_tables
            WHERE schemaname = 'public'
              AND tablename = 'rag_schema_migrations'
        ),
        'MEMBER'
    ),
    {no_auxiliary_relation_privileges_sql(RUNTIME_RELATION_ALLOWLIST)},
    {no_executable_security_definer_routines_sql()},
    {no_user_schema_create_privileges_sql()}
FROM pg_tables
JOIN pg_roles ON rolname = current_user
WHERE schemaname = 'public' AND tablename = 'rag_chunks'
"""


def review_database_ready(dsn: str) -> bool:
    """Prouver la connexion et le moindre privilège attendu du rôle review."""
    with psycopg.connect(
        dsn,
        connect_timeout=readiness_connect_timeout_s(),
        options=readiness_connection_options(),
    ) as connection:
        with connection.cursor() as cursor:
            apply_readiness_statement_budget(cursor)
            cursor.execute(_REVIEW_PRIVILEGES_SQL)
            row = cursor.fetchone()
    return row == _REQUIRED_REVIEW_PRIVILEGES


__all__ = [
    "READINESS_CONNECT_TIMEOUT_S",
    "READINESS_STATEMENT_TIMEOUT_MS",
    "review_database_ready",
]
