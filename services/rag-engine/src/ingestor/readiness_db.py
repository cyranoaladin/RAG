"""Paramètres PostgreSQL read-only communs aux sondes de readiness v2."""

from __future__ import annotations

import re
from typing import Final

import psycopg

READINESS_CONNECT_TIMEOUT_S: Final = 3
READINESS_STATEMENT_TIMEOUT_MS: Final = 3000
RUNTIME_RELATION_ALLOWLIST: Final = (
    ("public", "rag_chunks"),
    ("public", "rag_schema_migrations"),
)
_SAFE_CATALOG_NAME = re.compile(r"[a-z_][a-z0-9_]*\Z")


def no_auxiliary_relation_privileges_sql(
    allowed_relations: tuple[tuple[str, str], ...],
) -> str:
    """Construire le prédicat PG16 interdisant les droits hors allowlist."""
    if (
        not allowed_relations
        or len(set(allowed_relations)) != len(allowed_relations)
        or any(
            _SAFE_CATALOG_NAME.fullmatch(name) is None
            for relation in allowed_relations
            if len(relation) == 2
            for name in relation
        )
        or any(len(relation) != 2 for relation in allowed_relations)
    ):
        raise ValueError("allowlist de relations PostgreSQL invalide")

    allowed_sql = ", ".join(
        f"('{schema}', '{relation}')" for schema, relation in allowed_relations
    )
    return f"""
NOT EXISTS (
    SELECT 1
    FROM pg_class AS auxiliary_relation
    JOIN pg_namespace AS auxiliary_namespace
      ON auxiliary_namespace.oid = auxiliary_relation.relnamespace
    WHERE auxiliary_namespace.nspname NOT IN (
              'pg_catalog', 'information_schema'
          )
      AND auxiliary_namespace.nspname NOT LIKE 'pg_toast%'
      AND auxiliary_namespace.nspname NOT LIKE 'pg_temp_%'
      AND (
          auxiliary_namespace.nspname,
          auxiliary_relation.relname
      ) NOT IN ({allowed_sql})
      AND (
          (
              auxiliary_relation.relkind IN ('r', 'p', 'v', 'm', 'f')
              AND (
                  has_table_privilege(
                      current_user, auxiliary_relation.oid, 'SELECT'
                  )
                  OR has_table_privilege(
                      current_user, auxiliary_relation.oid, 'INSERT'
                  )
                  OR has_table_privilege(
                      current_user, auxiliary_relation.oid, 'UPDATE'
                  )
                  OR has_table_privilege(
                      current_user, auxiliary_relation.oid, 'DELETE'
                  )
                  OR has_table_privilege(
                      current_user, auxiliary_relation.oid, 'TRUNCATE'
                  )
                  OR has_table_privilege(
                      current_user, auxiliary_relation.oid, 'REFERENCES'
                  )
                  OR has_table_privilege(
                      current_user, auxiliary_relation.oid, 'TRIGGER'
                  )
                  OR has_any_column_privilege(
                      current_user, auxiliary_relation.oid, 'SELECT'
                  )
                  OR has_any_column_privilege(
                      current_user, auxiliary_relation.oid, 'INSERT'
                  )
                  OR has_any_column_privilege(
                      current_user, auxiliary_relation.oid, 'UPDATE'
                  )
                  OR has_any_column_privilege(
                      current_user, auxiliary_relation.oid, 'REFERENCES'
                  )
              )
          )
          OR (
              auxiliary_relation.relkind = 'S'
              AND (
                  has_sequence_privilege(
                      current_user, auxiliary_relation.oid, 'USAGE'
                  )
                  OR has_sequence_privilege(
                      current_user, auxiliary_relation.oid, 'SELECT'
                  )
                  OR has_sequence_privilege(
                      current_user, auxiliary_relation.oid, 'UPDATE'
                  )
              )
          )
      )
)
""".strip()


def no_executable_security_definer_routines_sql() -> str:
    """Refuser toute routine utilisateur privilégiée exécutable par le rôle."""
    return """
NOT EXISTS (
    SELECT 1
    FROM pg_proc AS privileged_routine
    JOIN pg_namespace AS routine_namespace
      ON routine_namespace.oid = privileged_routine.pronamespace
    WHERE routine_namespace.nspname NOT IN (
              'pg_catalog', 'information_schema'
          )
      AND routine_namespace.nspname NOT LIKE 'pg_toast%'
      AND routine_namespace.nspname NOT LIKE 'pg_temp_%'
      AND privileged_routine.prokind IN ('f', 'p')
      AND privileged_routine.prosecdef
      AND has_function_privilege(
          current_user, privileged_routine.oid, 'EXECUTE'
      )
)
""".strip()


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
    "RUNTIME_RELATION_ALLOWLIST",
    "no_auxiliary_relation_privileges_sql",
    "no_executable_security_definer_routines_sql",
    "postgres_database_identity",
    "readiness_connection_options",
]
