"""Vérification read-only du contrat PostgreSQL au head LOT41 003."""

from __future__ import annotations

from collections.abc import Sequence

import psycopg

REQUIRED_PROFILE_COLUMNS = frozenset(
    {
        "tenant",
        "candidat",
        "visibility",
        "school_year",
        "programme_version",
    }
)
REQUIRED_PROFILE_CONSTRAINTS = frozenset(
    {
        "rag_chunks_tenant_lot41_check",
        "rag_chunks_candidat_lot41_check",
        "rag_chunks_visibility_lot41_check",
        "rag_chunks_school_year_lot41_check",
        "rag_chunks_programme_version_lot41_check",
    }
)

_SCHEMA_HEAD_003_SQL = """
SELECT
    ARRAY(
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'rag_chunks'
          AND column_name IN (
              'tenant',
              'candidat',
              'visibility',
              'school_year',
              'programme_version'
          )
        ORDER BY column_name
    ),
    ARRAY(
        SELECT constraint_definition.conname
        FROM pg_constraint AS constraint_definition
        WHERE constraint_definition.conrelid = 'public.rag_chunks'::regclass
          AND constraint_definition.convalidated
          AND constraint_definition.conname IN (
              'rag_chunks_tenant_lot41_check',
              'rag_chunks_candidat_lot41_check',
              'rag_chunks_visibility_lot41_check',
              'rag_chunks_school_year_lot41_check',
              'rag_chunks_programme_version_lot41_check'
          )
        ORDER BY constraint_definition.conname
    ),
    to_regclass('public.idx_rag_chunks_profile_reviewed') IS NOT NULL
"""


def _as_name_set(value: object) -> frozenset[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return frozenset()
    return frozenset(item for item in value if isinstance(item, str))


def schema_head_003_ready(dsn: str) -> bool:
    """Prouver la présence exacte des objets ajoutés par la migration 003."""
    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_SCHEMA_HEAD_003_SQL)
            row = cursor.fetchone()

    if row is None or len(row) != 3:
        return False
    columns, constraints, index_present = row
    return (
        _as_name_set(columns) == REQUIRED_PROFILE_COLUMNS
        and _as_name_set(constraints) == REQUIRED_PROFILE_CONSTRAINTS
        and index_present is True
    )


__all__ = [
    "REQUIRED_PROFILE_COLUMNS",
    "REQUIRED_PROFILE_CONSTRAINTS",
    "schema_head_003_ready",
]
