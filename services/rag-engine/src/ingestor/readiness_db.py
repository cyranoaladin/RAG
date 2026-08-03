"""Paramètres PostgreSQL read-only communs aux sondes de readiness v2."""

from __future__ import annotations

import re
import secrets
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from typing import Any, Final

import psycopg

READINESS_CONNECT_TIMEOUT_S: Final = 3
READINESS_STATEMENT_TIMEOUT_MS: Final = 3000
READINESS_AGGREGATE_BUDGET_MS: Final = 7000
_MIN_LIBPQ_CONNECT_TIMEOUT_S: Final = 2
RUNTIME_RELATION_ALLOWLIST: Final = (
    ("public", "rag_chunks"),
    ("public", "rag_schema_migrations"),
)
_SAFE_CATALOG_NAME = re.compile(r"[a-z_][a-z0-9_]*\Z")
_readiness_deadline: ContextVar[float | None] = ContextVar(
    "readiness_database_deadline",
    default=None,
)


@contextmanager
def readiness_database_budget() -> Iterator[float]:
    """Partager une deadline unique, plus courte que le healthcheck Compose."""
    existing = _readiness_deadline.get()
    if existing is not None:
        yield existing
        return
    deadline = time.monotonic() + (READINESS_AGGREGATE_BUDGET_MS / 1000.0)
    token: Token[float | None] = _readiness_deadline.set(deadline)
    try:
        yield deadline
    finally:
        _readiness_deadline.reset(token)


def remaining_readiness_budget_ms() -> int:
    """Retourner le reliquat de la sonde profonde ou échouer fermé."""
    deadline = _readiness_deadline.get()
    if deadline is None:
        return READINESS_AGGREGATE_BUDGET_MS
    remaining_ms = int((deadline - time.monotonic()) * 1000)
    if remaining_ms <= 0:
        raise RuntimeError("database readiness budget exhausted")
    return min(remaining_ms, READINESS_AGGREGATE_BUDGET_MS)


def readiness_connect_timeout_s() -> int:
    """Borner libpq au reliquat, en respectant son minimum effectif de 2 s."""
    if _readiness_deadline.get() is None:
        return READINESS_CONNECT_TIMEOUT_S
    remaining_s = remaining_readiness_budget_ms() // 1000
    if remaining_s < _MIN_LIBPQ_CONNECT_TIMEOUT_S:
        raise RuntimeError("database readiness budget exhausted")
    return min(READINESS_CONNECT_TIMEOUT_S, remaining_s)


def apply_readiness_statement_budget(cursor: Any) -> None:
    """Réduire le timeout du prochain statement au reliquat agrégé."""
    timeout_ms = min(
        READINESS_STATEMENT_TIMEOUT_MS,
        remaining_readiness_budget_ms(),
    )
    cursor.execute(f"SET LOCAL statement_timeout = {timeout_ms}")


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
    """Refuser toute routine non native privilégiée exécutable par le rôle.

    PostgreSQL réserve les OID inférieurs à FirstNormalObjectId (16384) aux
    objets natifs du catalogue. Une routine créée ensuite reste donc contrôlée
    même si un administrateur la place dans ``pg_catalog``.
    """
    return """
NOT EXISTS (
    SELECT 1
    FROM pg_proc AS privileged_routine
    WHERE privileged_routine.oid >= 16384
      AND privileged_routine.prosecdef
      AND has_function_privilege(
          current_user, privileged_routine.oid, 'EXECUTE'
      )
)
""".strip()


def no_user_schema_create_privileges_sql() -> str:
    """Refuser ownership et CREATE effectif sur tout schéma utilisateur."""
    return r"""
NOT EXISTS (
    SELECT 1
    FROM pg_namespace AS user_namespace
    WHERE user_namespace.nspname <> 'information_schema'
      AND user_namespace.nspname NOT LIKE E'pg\\_%' ESCAPE E'\\'
      AND (
          has_schema_privilege(
              current_user, user_namespace.oid, 'CREATE'
          )
          OR pg_has_role(
              current_user, user_namespace.nspowner, 'MEMBER'
          )
      )
)
""".strip()


def no_large_object_privileges_sql() -> str:
    """Refuser ownership et droits effectifs sur tout large object PostgreSQL."""
    return """
NOT EXISTS (
    SELECT 1
    FROM pg_largeobject_metadata AS large_object
    WHERE pg_has_role(
              current_user, large_object.lomowner, 'MEMBER'
          )
       OR EXISTS (
              SELECT 1
              FROM aclexplode(COALESCE(
                  large_object.lomacl,
                  acldefault('L'::"char", large_object.lomowner)
              )) AS large_object_acl
              WHERE large_object_acl.privilege_type IN ('SELECT', 'UPDATE')
                AND CASE
                    WHEN large_object_acl.grantee = 0 THEN true
                    ELSE pg_has_role(
                        current_user,
                        large_object_acl.grantee,
                        'MEMBER'
                    )
                END
          )
)
""".strip()


def large_object_acl_enforcement_columns_sql() -> str:
    """Attester les ACL large objects actives et non désactivables par le rôle."""
    return """
current_setting('lo_compat_privileges') = 'off',
NOT has_parameter_privilege(
    current_user,
    'lo_compat_privileges',
    'SET, ALTER SYSTEM'
)
""".strip()


def readiness_connection_options() -> str:
    """Retourner les options bornées et non mutantes du contrat de readiness."""
    return (
        f"-c statement_timeout={min(READINESS_STATEMENT_TIMEOUT_MS, remaining_readiness_budget_ms())} "
        "-c default_transaction_read_only=on"
    )


def _postgres_database_identity(cursor: Any) -> tuple[str, str]:
    apply_readiness_statement_budget(cursor)
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


def postgres_database_identity(dsn: str) -> tuple[str, str]:
    """Attester l'identifiant du cluster et le nom de base ciblés par un DSN."""
    with psycopg.connect(
        dsn,
        connect_timeout=readiness_connect_timeout_s(),
        options=readiness_connection_options(),
    ) as connection:
        with connection.cursor() as cursor:
            return _postgres_database_identity(cursor)


def postgres_database_authorities_share_instance(
    rag_dsn: str,
    review_dsn: str,
) -> bool:
    """Prouver en direct que les deux autorités partagent le même lock manager."""
    challenge = secrets.randbits(63)
    reader_acquired = False
    reviewer_acquired = False
    with psycopg.connect(
        rag_dsn,
        connect_timeout=readiness_connect_timeout_s(),
        options=readiness_connection_options(),
    ) as rag_connection:
        with psycopg.connect(
            review_dsn,
            connect_timeout=readiness_connect_timeout_s(),
            options=readiness_connection_options(),
        ) as review_connection:
            with rag_connection.cursor() as rag_cursor:
                with review_connection.cursor() as review_cursor:
                    try:
                        if _postgres_database_identity(
                            rag_cursor
                        ) != _postgres_database_identity(review_cursor):
                            return False
                        apply_readiness_statement_budget(rag_cursor)
                        rag_cursor.execute(
                            "SELECT pg_try_advisory_lock(%s)",
                            (challenge,),
                        )
                        reader_row = rag_cursor.fetchone()
                        reader_acquired = reader_row == (True,)
                        if not reader_acquired:
                            return False
                        apply_readiness_statement_budget(review_cursor)
                        review_cursor.execute(
                            "SELECT pg_try_advisory_lock(%s)",
                            (challenge,),
                        )
                        review_row = review_cursor.fetchone()
                        reviewer_acquired = review_row == (True,)
                        return not reviewer_acquired
                    finally:
                        if reviewer_acquired:
                            review_cursor.execute(
                                "SELECT pg_advisory_unlock(%s)",
                                (challenge,),
                            )
                        if reader_acquired:
                            rag_cursor.execute(
                                "SELECT pg_advisory_unlock(%s)",
                                (challenge,),
                            )


__all__ = [
    "READINESS_CONNECT_TIMEOUT_S",
    "READINESS_AGGREGATE_BUDGET_MS",
    "READINESS_STATEMENT_TIMEOUT_MS",
    "RUNTIME_RELATION_ALLOWLIST",
    "apply_readiness_statement_budget",
    "large_object_acl_enforcement_columns_sql",
    "no_auxiliary_relation_privileges_sql",
    "no_executable_security_definer_routines_sql",
    "no_large_object_privileges_sql",
    "no_user_schema_create_privileges_sql",
    "postgres_database_authorities_share_instance",
    "postgres_database_identity",
    "readiness_connect_timeout_s",
    "readiness_connection_options",
    "readiness_database_budget",
    "remaining_readiness_budget_ms",
]
