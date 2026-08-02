"""Vérification read-only du contrat PostgreSQL au head LOT41 003."""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from typing import Final

import psycopg

READINESS_CONNECT_TIMEOUT_S: Final = 3
READINESS_STATEMENT_TIMEOUT_MS: Final = 3000

REQUIRED_MIGRATIONS: Final = (
    (1, "001_rag_chunks_v2_schema.sql"),
    (2, "002_hybrid_retrieval.sql"),
    (3, "003_profile_filtering.sql"),
)
REQUIRED_PROFILE_COLUMN_DEFINITIONS: Final = {
    "candidat": ["text", "YES", None],
    "programme_version": ["text", "YES", None],
    "school_year": ["text", "YES", None],
    "tenant": ["text", "YES", None],
    "visibility": ["text", "YES", None],
}

# Empreintes des sorties pg_get_constraintdef(..., pretty_bool => true) sur le
# PostgreSQL 16 épinglé. Elles détectent les objets homonymes et toute dérive
# après l'enregistrement des migrations canoniques.
REQUIRED_PROFILE_CONSTRAINT_DEFINITIONS: Final = {
    "rag_chunks_candidat_lot41_check": "4d93d3e34b13897d1bb7cb39becc029c",
    "rag_chunks_programme_version_lot41_check": (
        "932c1c1568ffc8f558e757e2c1b342dd"
    ),
    "rag_chunks_school_year_lot41_check": "551bb8058f049be32467d33c99833d50",
    "rag_chunks_tenant_lot41_check": "c47730624202793895c2196f89ccc003",
    "rag_chunks_visibility_lot41_check": "3a09f093ae8366bb1bcf83d26021dcc8",
}
REQUIRED_PROFILE_INDEX_DEFINITION: Final = "1e810dca20fd302afe0390124cea16fa"
REQUIRED_PROFILE_INDEX_PREDICATE: Final = "f0c66a863c91e23b8eda575e06e93e33"

_SCHEMA_HEAD_003_SQL = """
SELECT
    COALESCE((
        SELECT jsonb_object_agg(
            column_name,
            jsonb_build_array(data_type, is_nullable, column_default)
        )
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
    ), '{}'::jsonb),
    COALESCE((
        SELECT jsonb_object_agg(
            constraint_definition.conname,
            md5(pg_get_constraintdef(constraint_definition.oid, true))
        )
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
    ), '{}'::jsonb),
    (
        SELECT md5(pg_get_indexdef(index_definition.indexrelid))
        FROM pg_index AS index_definition
        WHERE index_definition.indexrelid =
            to_regclass('public.idx_rag_chunks_profile_reviewed')
          AND index_definition.indisvalid
          AND index_definition.indisready
    ),
    (
        SELECT md5(pg_get_expr(
            index_definition.indpred,
            index_definition.indrelid,
            true
        ))
        FROM pg_index AS index_definition
        WHERE index_definition.indexrelid =
            to_regclass('public.idx_rag_chunks_profile_reviewed')
          AND index_definition.indisvalid
          AND index_definition.indisready
    ),
    COALESCE((
        SELECT jsonb_agg(
            jsonb_build_array(version, file_name, sha256)
            ORDER BY version
        )
        FROM rag_schema_migrations
    ), '[]'::jsonb)
"""


def _default_migration_root() -> Path:
    configured = os.environ.get("RAG_MIGRATIONS_DIR", "").strip()
    if configured:
        return Path(configured)
    packaged = Path(__file__).resolve().with_name("migrations")
    if packaged.is_dir():
        return packaged
    return Path(__file__).resolve().parents[2] / "infra" / "postgres" / "migrations"


def expected_migration_records(
    migration_root: Path | None = None,
) -> tuple[tuple[int, str, str], ...]:
    """Calculer les SHA attendus depuis les migrations livrées avec le runtime."""
    root = migration_root or _default_migration_root()
    return tuple(
        (version, file_name, sha256((root / file_name).read_bytes()).hexdigest())
        for version, file_name in REQUIRED_MIGRATIONS
    )


def schema_head_003_ready(dsn: str) -> bool:
    """Prouver le registre, les SHA et les définitions exactes du head 003."""
    options = (
        f"-c statement_timeout={READINESS_STATEMENT_TIMEOUT_MS} "
        "-c default_transaction_read_only=on"
    )
    with psycopg.connect(
        dsn,
        connect_timeout=READINESS_CONNECT_TIMEOUT_S,
        options=options,
    ) as connection:
        with connection.cursor() as cursor:
            cursor.execute(_SCHEMA_HEAD_003_SQL)
            row = cursor.fetchone()

    if row is None or len(row) != 5:
        return False
    columns, constraints, index_definition, index_predicate, migrations = row
    return bool(
        columns == REQUIRED_PROFILE_COLUMN_DEFINITIONS
        and constraints == REQUIRED_PROFILE_CONSTRAINT_DEFINITIONS
        and index_definition == REQUIRED_PROFILE_INDEX_DEFINITION
        and index_predicate == REQUIRED_PROFILE_INDEX_PREDICATE
        and migrations
        == [list(item) for item in expected_migration_records()]
    )


__all__ = [
    "READINESS_CONNECT_TIMEOUT_S",
    "READINESS_STATEMENT_TIMEOUT_MS",
    "REQUIRED_PROFILE_COLUMN_DEFINITIONS",
    "REQUIRED_PROFILE_CONSTRAINT_DEFINITIONS",
    "REQUIRED_PROFILE_INDEX_DEFINITION",
    "REQUIRED_PROFILE_INDEX_PREDICATE",
    "expected_migration_records",
    "schema_head_003_ready",
]
