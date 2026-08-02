"""Vérification read-only du contrat PostgreSQL au head LOT41 003."""

from __future__ import annotations

import os
import re
from hashlib import sha256
from pathlib import Path
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

_FINGERPRINT_KEYS: Final = {
    "RAG_CHUNKS_CANDIDAT_LOT41_CHECK_MD5": (
        "rag_chunks_candidat_lot41_check"
    ),
    "RAG_CHUNKS_PROGRAMME_VERSION_LOT41_CHECK_MD5": (
        "rag_chunks_programme_version_lot41_check"
    ),
    "RAG_CHUNKS_SCHOOL_YEAR_LOT41_CHECK_MD5": (
        "rag_chunks_school_year_lot41_check"
    ),
    "RAG_CHUNKS_TENANT_LOT41_CHECK_MD5": "rag_chunks_tenant_lot41_check",
    "RAG_CHUNKS_VISIBILITY_LOT41_CHECK_MD5": (
        "rag_chunks_visibility_lot41_check"
    ),
}
_INDEX_DEFINITION_KEY: Final = "RAG_CHUNKS_PROFILE_REVIEWED_INDEX_MD5"
_INDEX_PREDICATE_KEY: Final = "RAG_CHUNKS_PROFILE_REVIEWED_PREDICATE_MD5"
_MD5 = re.compile(r"[0-9a-f]{32}")


def _default_fingerprint_path() -> Path:
    configured = os.environ.get("RAG_SCHEMA_HEAD_FINGERPRINTS", "").strip()
    if configured:
        return Path(configured)
    packaged = Path(__file__).resolve().with_name("schema_head_003_fingerprints.env")
    if packaged.is_file():
        return packaged
    return (
        Path(__file__).resolve().parents[2]
        / "infra"
        / "postgres"
        / "schema_head_003_fingerprints.env"
    )


def load_schema_head_003_fingerprints(
    path: Path | None = None,
) -> dict[str, str]:
    """Lire strictement la source versionnée unique des empreintes PostgreSQL."""
    values: dict[str, str] = {}
    try:
        for line in (path or _default_fingerprint_path()).read_text(
            encoding="utf-8"
        ).splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in values or _MD5.fullmatch(value) is None:
                raise RuntimeError("SCHEMA_HEAD_003_FINGERPRINTS_INVALID")
            values[key] = value
    except OSError as exc:
        raise RuntimeError("SCHEMA_HEAD_003_FINGERPRINTS_UNAVAILABLE") from exc
    expected_keys = {*_FINGERPRINT_KEYS, _INDEX_DEFINITION_KEY, _INDEX_PREDICATE_KEY}
    if set(values) != expected_keys:
        raise RuntimeError("SCHEMA_HEAD_003_FINGERPRINTS_INVALID")
    return values


_FINGERPRINTS = load_schema_head_003_fingerprints()
REQUIRED_PROFILE_CONSTRAINT_DEFINITIONS: Final = {
    constraint_name: _FINGERPRINTS[key]
    for key, constraint_name in _FINGERPRINT_KEYS.items()
}
REQUIRED_PROFILE_INDEX_DEFINITION: Final = _FINGERPRINTS[_INDEX_DEFINITION_KEY]
REQUIRED_PROFILE_INDEX_PREDICATE: Final = _FINGERPRINTS[_INDEX_PREDICATE_KEY]

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
    with psycopg.connect(
        dsn,
        connect_timeout=READINESS_CONNECT_TIMEOUT_S,
        options=readiness_connection_options(),
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
    "load_schema_head_003_fingerprints",
    "schema_head_003_ready",
]
