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
REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS: Final = {
    "audience": [
        "ARRAY", "_text", "NO", "NEVER", "'{tous}'::text[]", "text[]", -1
    ],
    "candidat": ["text", "text", "YES", "NEVER", None, "text", -1],
    "chunk_id": ["text", "text", "NO", "NEVER", None, "text", -1],
    "chunk_index": ["integer", "int4", "NO", "NEVER", "0", "integer", -1],
    "chunk_sha256": ["text", "text", "NO", "NEVER", None, "text", -1],
    "collection": ["text", "text", "NO", "NEVER", None, "text", -1],
    "doc_id": ["text", "text", "NO", "NEVER", None, "text", -1],
    "domain": [
        "text", "text", "NO", "NEVER", "'education'::text", "text", -1
    ],
    "indexed_at": [
        "timestamp with time zone",
        "timestamptz",
        "NO",
        "NEVER",
        "now()",
        "timestamp with time zone",
        -1,
    ],
    "matiere": ["text", "text", "NO", "NEVER", None, "text", -1],
    "model": ["text", "text", "YES", "NEVER", None, "text", -1],
    "niveau": ["text", "text", "NO", "NEVER", None, "text", -1],
    "notions": [
        "ARRAY", "_text", "NO", "NEVER", "'{}'::text[]", "text[]", -1
    ],
    "official": ["boolean", "bool", "NO", "NEVER", "false", "boolean", -1],
    "page_end": ["integer", "int4", "YES", "NEVER", None, "integer", -1],
    "page_start": ["integer", "int4", "YES", "NEVER", None, "integer", -1],
    "programme_version": ["text", "text", "YES", "NEVER", None, "text", -1],
    "review_status": [
        "text", "text", "NO", "NEVER", "'needs_review'::text", "text", -1
    ],
    "rights": ["text", "text", "NO", "NEVER", None, "text", -1],
    "school_year": ["text", "text", "YES", "NEVER", None, "text", -1],
    "source_kind": [
        "text", "text", "NO", "NEVER", "'unknown'::text", "text", -1
    ],
    "source_label": ["text", "text", "NO", "NEVER", None, "text", -1],
    "source_uri": ["text", "text", "NO", "NEVER", None, "text", -1],
    "statut_enseignement": [
        "text", "text", "NO", "NEVER", "'unknown'::text", "text", -1
    ],
    "tenant": ["text", "text", "YES", "NEVER", None, "text", -1],
    "text": ["text", "text", "YES", "NEVER", None, "text", -1],
    "text_tsv": [
        "tsvector", "tsvector", "YES", "ALWAYS", None, "tsvector", -1
    ],
    "type_doc": ["text", "text", "NO", "NEVER", None, "text", -1],
    "vector": [
        "USER-DEFINED", "vector", "YES", "NEVER", None, "vector(1024)", 1024
    ],
    "visibility": ["text", "text", "YES", "NEVER", None, "text", -1],
    "voie": [
        "text", "text", "NO", "NEVER", "'generale'::text", "text", -1
    ],
}
REQUIRED_PROFILE_COLUMN_DEFINITIONS: Final = {
    name: REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS[name]
    for name in (
        "candidat",
        "programme_version",
        "school_year",
        "tenant",
        "visibility",
    )
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
_INDEX_FINGERPRINT_KEYS: Final = {
    "IDX_RAG_CHUNKS_AUDIENCE_MD5": "idx_rag_chunks_audience",
    "IDX_RAG_CHUNKS_COLLECTION_MD5": "idx_rag_chunks_collection",
    "IDX_RAG_CHUNKS_MATIERE_MD5": "idx_rag_chunks_matiere",
    "IDX_RAG_CHUNKS_NIVEAU_MD5": "idx_rag_chunks_niveau",
    "RAG_CHUNKS_PROFILE_REVIEWED_INDEX_MD5": (
        "idx_rag_chunks_profile_reviewed"
    ),
    "IDX_RAG_CHUNKS_REVIEW_MD5": "idx_rag_chunks_review",
    "IDX_RAG_CHUNKS_RIGHTS_MD5": "idx_rag_chunks_rights",
    "IDX_RAG_CHUNKS_TEXT_TSV_MD5": "idx_rag_chunks_text_tsv",
    "IDX_RAG_CHUNKS_VECTOR_MD5": "idx_rag_chunks_vector",
    "RAG_CHUNKS_PRIMARY_INDEX_MD5": "rag_chunks_pkey",
}
_INDEX_PREDICATE_KEY: Final = "RAG_CHUNKS_PROFILE_REVIEWED_PREDICATE_MD5"
_TEXT_TSV_EXPRESSION_KEY: Final = "RAG_CHUNKS_TEXT_TSV_EXPRESSION_MD5"
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
    expected_keys = {
        *_FINGERPRINT_KEYS,
        *_INDEX_FINGERPRINT_KEYS,
        _INDEX_PREDICATE_KEY,
        _TEXT_TSV_EXPRESSION_KEY,
    }
    if set(values) != expected_keys:
        raise RuntimeError("SCHEMA_HEAD_003_FINGERPRINTS_INVALID")
    return values


_FINGERPRINTS = load_schema_head_003_fingerprints()
REQUIRED_PROFILE_CONSTRAINT_DEFINITIONS: Final = {
    constraint_name: [True, _FINGERPRINTS[key]]
    for key, constraint_name in _FINGERPRINT_KEYS.items()
}
REQUIRED_RAG_CHUNKS_INDEX_DEFINITIONS: Final = {
    index_name: _FINGERPRINTS[key]
    for key, index_name in _INDEX_FINGERPRINT_KEYS.items()
}
REQUIRED_PROFILE_INDEX_DEFINITION: Final = (
    REQUIRED_RAG_CHUNKS_INDEX_DEFINITIONS["idx_rag_chunks_profile_reviewed"]
)
REQUIRED_PROFILE_INDEX_PREDICATE: Final = _FINGERPRINTS[_INDEX_PREDICATE_KEY]
REQUIRED_TEXT_TSV_EXPRESSION: Final = _FINGERPRINTS[_TEXT_TSV_EXPRESSION_KEY]

_SCHEMA_HEAD_003_SQL = """
SELECT
    COALESCE((
        SELECT jsonb_object_agg(
            column_definition.column_name,
            jsonb_build_array(
                column_definition.data_type,
                column_definition.udt_name,
                column_definition.is_nullable,
                column_definition.is_generated,
                column_definition.column_default,
                format_type(attribute.atttypid, attribute.atttypmod),
                attribute.atttypmod
            )
        )
        FROM information_schema.columns AS column_definition
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = 'public.rag_chunks'::regclass
         AND attribute.attname = column_definition.column_name
         AND attribute.attnum > 0
         AND NOT attribute.attisdropped
        WHERE column_definition.table_schema = 'public'
          AND column_definition.table_name = 'rag_chunks'
    ), '{}'::jsonb),
    COALESCE((
        SELECT jsonb_object_agg(
            constraint_definition.conname,
            jsonb_build_array(
                constraint_definition.convalidated,
                md5(pg_get_constraintdef(constraint_definition.oid, true))
            )
        )
        FROM pg_constraint AS constraint_definition
        WHERE constraint_definition.conrelid = 'public.rag_chunks'::regclass
          AND constraint_definition.contype = 'c'
    ), '{}'::jsonb),
    COALESCE((
        SELECT jsonb_object_agg(
            index_relation.relname,
            md5(pg_get_indexdef(index_definition.indexrelid))
        )
        FROM pg_index AS index_definition
        JOIN pg_class AS index_relation
          ON index_relation.oid = index_definition.indexrelid
        WHERE index_definition.indrelid = 'public.rag_chunks'::regclass
          AND index_definition.indisvalid
          AND index_definition.indisready
    ), '{}'::jsonb),
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
    (
        SELECT md5(pg_get_expr(
            generated_definition.adbin,
            generated_definition.adrelid,
            true
        ))
        FROM pg_attrdef AS generated_definition
        JOIN pg_attribute AS generated_column
          ON generated_column.attrelid = generated_definition.adrelid
         AND generated_column.attnum = generated_definition.adnum
        WHERE generated_definition.adrelid = 'public.rag_chunks'::regclass
          AND generated_column.attname = 'text_tsv'
          AND generated_column.attgenerated = 's'
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

    if row is None or len(row) != 6:
        return False
    (
        columns,
        constraints,
        index_definitions,
        index_predicate,
        text_tsv_expression,
        migrations,
    ) = row
    return bool(
        columns == REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS
        and constraints == REQUIRED_PROFILE_CONSTRAINT_DEFINITIONS
        and index_definitions == REQUIRED_RAG_CHUNKS_INDEX_DEFINITIONS
        and index_predicate == REQUIRED_PROFILE_INDEX_PREDICATE
        and text_tsv_expression == REQUIRED_TEXT_TSV_EXPRESSION
        and migrations
        == [list(item) for item in expected_migration_records()]
    )


__all__ = [
    "READINESS_CONNECT_TIMEOUT_S",
    "READINESS_STATEMENT_TIMEOUT_MS",
    "REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS",
    "REQUIRED_RAG_CHUNKS_INDEX_DEFINITIONS",
    "REQUIRED_PROFILE_COLUMN_DEFINITIONS",
    "REQUIRED_PROFILE_CONSTRAINT_DEFINITIONS",
    "REQUIRED_PROFILE_INDEX_DEFINITION",
    "REQUIRED_PROFILE_INDEX_PREDICATE",
    "REQUIRED_TEXT_TSV_EXPRESSION",
    "expected_migration_records",
    "load_schema_head_003_fingerprints",
    "schema_head_003_ready",
]
