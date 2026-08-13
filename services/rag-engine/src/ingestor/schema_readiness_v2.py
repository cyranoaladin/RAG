"""Vérification read-only du contrat PostgreSQL produit au head H2-C 004.

La sonde compare les trois relations produit, leurs colonnes, contraintes,
index, prédicats partiels, états de table et le registre de migrations. Une
relation ou un objet supplémentaire est une dérive : le résultat est faux.
"""

from __future__ import annotations

import csv
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
        apply_readiness_statement_budget,
        readiness_connect_timeout_s,
        readiness_connection_options,
    )
except ImportError:  # Image Docker aplatie sous /app.
    from readiness_db import (  # type: ignore[no-redef]
        READINESS_CONNECT_TIMEOUT_S,
        READINESS_STATEMENT_TIMEOUT_MS,
        apply_readiness_statement_budget,
        readiness_connect_timeout_s,
        readiness_connection_options,
    )

REQUIRED_MIGRATIONS: Final = (
    (1, "001_rag_chunks_v2_schema.sql"),
    (2, "002_hybrid_retrieval.sql"),
    (3, "003_profile_filtering.sql"),
    (4, "004_artifact_placements.sql"),
)
REQUIRED_PRODUCT_TABLES: Final = (
    "rag_artifact_placements",
    "rag_artifacts",
    "rag_chunks",
)

_COLUMN_CONTRACT_FIELDS: Final = (
    "table_name",
    "column_name",
    "data_type",
    "udt_name",
    "is_nullable",
    "is_generated",
    "column_default",
    "formatted_type",
    "atttypmod",
)


def _default_column_contract_path() -> Path:
    configured = os.environ.get("RAG_SCHEMA_HEAD_COLUMNS", "").strip()
    if configured:
        return Path(configured)
    packaged = Path(__file__).resolve().with_name("schema_head_004_columns.tsv")
    if packaged.is_file():
        return packaged
    return (
        Path(__file__).resolve().parents[2]
        / "infra"
        / "postgres"
        / "schema_head_004_columns.tsv"
    )


def load_product_column_definitions(
    path: Path | None = None,
) -> dict[str, dict[str, list[object]]]:
    """Lire strictement le contrat partagé des trois relations produit."""
    definitions: dict[str, dict[str, list[object]]] = {
        table: {} for table in REQUIRED_PRODUCT_TABLES
    }
    try:
        with (path or _default_column_contract_path()).open(
            encoding="utf-8", newline=""
        ) as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if tuple(reader.fieldnames or ()) != _COLUMN_CONTRACT_FIELDS:
                raise RuntimeError("SCHEMA_HEAD_004_COLUMNS_INVALID")
            for row in reader:
                if None in row or any(value is None for value in row.values()):
                    raise RuntimeError("SCHEMA_HEAD_004_COLUMNS_INVALID")
                table = row["table_name"]
                name = row["column_name"]
                if table not in definitions or not name or name in definitions[table]:
                    raise RuntimeError("SCHEMA_HEAD_004_COLUMNS_INVALID")
                try:
                    atttypmod = int(row["atttypmod"])
                except ValueError as exc:
                    raise RuntimeError("SCHEMA_HEAD_004_COLUMNS_INVALID") from exc
                column_default = row["column_default"]
                definitions[table][name] = [
                    row["data_type"],
                    row["udt_name"],
                    row["is_nullable"],
                    row["is_generated"],
                    None if column_default == r"\N" else column_default,
                    row["formatted_type"],
                    atttypmod,
                ]
    except OSError as exc:
        raise RuntimeError("SCHEMA_HEAD_004_COLUMNS_UNAVAILABLE") from exc
    expected_counts = {
        "rag_artifact_placements": 23,
        "rag_artifacts": 10,
        "rag_chunks": 32,
    }
    if {table: len(columns) for table, columns in definitions.items()} != expected_counts:
        raise RuntimeError("SCHEMA_HEAD_004_COLUMNS_INVALID")
    return definitions


def load_rag_chunks_column_definitions(
    path: Path | None = None,
) -> dict[str, list[object]]:
    """Compatibilité appelants : projeter le contrat exact de rag_chunks."""
    return load_product_column_definitions(path)["rag_chunks"]


REQUIRED_PRODUCT_COLUMN_DEFINITIONS: Final = load_product_column_definitions()
REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS: Final = (
    REQUIRED_PRODUCT_COLUMN_DEFINITIONS["rag_chunks"]
)
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

_CONSTRAINT_FINGERPRINT_KEYS: Final = {
    "RAG_CHUNKS_CANDIDAT_LOT41_CHECK_MD5": (
        "rag_chunks", "rag_chunks_candidat_lot41_check", "c"
    ),
    "RAG_CHUNKS_PROGRAMME_VERSION_LOT41_CHECK_MD5": (
        "rag_chunks", "rag_chunks_programme_version_lot41_check", "c"
    ),
    "RAG_CHUNKS_SCHOOL_YEAR_LOT41_CHECK_MD5": (
        "rag_chunks", "rag_chunks_school_year_lot41_check", "c"
    ),
    "RAG_CHUNKS_TENANT_LOT41_CHECK_MD5": (
        "rag_chunks", "rag_chunks_tenant_lot41_check", "c"
    ),
    "RAG_CHUNKS_VISIBILITY_LOT41_CHECK_MD5": (
        "rag_chunks", "rag_chunks_visibility_lot41_check", "c"
    ),
    "RAG_CHUNKS_PRIMARY_CONSTRAINT_MD5": ("rag_chunks", "rag_chunks_pkey", "p"),
    "RAG_CHUNKS_ARTIFACT_FK_MD5": (
        "rag_chunks", "rag_chunks_artifact_id_fkey", "f"
    ),
    "RAG_CHUNKS_GOVERNED_IDENTITY_CHECK_MD5": (
        "rag_chunks", "rag_chunks_governed_identity_check", "c"
    ),
    "RAG_ARTIFACTS_ARTIFACT_ID_CHECK_MD5": (
        "rag_artifacts", "rag_artifacts_artifact_id_sha256_check", "c"
    ),
    "RAG_ARTIFACTS_CONTENT_UNIQUE_MD5": (
        "rag_artifacts", "rag_artifacts_content_sha256_key", "u"
    ),
    "RAG_ARTIFACTS_IDENTITY_CHECK_MD5": (
        "rag_artifacts", "rag_artifacts_identity_is_content_sha256_check", "c"
    ),
    "RAG_ARTIFACTS_PRIMARY_CONSTRAINT_MD5": (
        "rag_artifacts", "rag_artifacts_pkey", "p"
    ),
    "RAG_ARTIFACTS_RIGHTS_CHECK_MD5": (
        "rag_artifacts", "rag_artifacts_rights_nonblank_check", "c"
    ),
    "RAG_ARTIFACTS_SOURCE_KIND_CHECK_MD5": (
        "rag_artifacts", "rag_artifacts_source_kind_nonblank_check", "c"
    ),
    "RAG_ARTIFACTS_SOURCE_LABEL_CHECK_MD5": (
        "rag_artifacts", "rag_artifacts_source_label_nonblank_check", "c"
    ),
    "RAG_ARTIFACTS_SOURCE_URI_CHECK_MD5": (
        "rag_artifacts", "rag_artifacts_source_uri_nonblank_check", "c"
    ),
    "RAG_ARTIFACTS_TYPE_DOC_CHECK_MD5": (
        "rag_artifacts", "rag_artifacts_type_doc_nonblank_check", "c"
    ),
    "PLACEMENTS_ARTIFACT_FK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_artifact_id_fkey", "f"
    ),
    "PLACEMENTS_AUDIENCE_CHECK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_audience_no_blank_check", "c"
    ),
    "PLACEMENTS_CANDIDAT_CHECK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_candidat_check", "c"
    ),
    "PLACEMENTS_CANONICAL_UNIQUE_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_canonical_scope_unique", "u"
    ),
    "PLACEMENTS_CURRENTNESS_CHECK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_currentness_check", "c"
    ),
    "PLACEMENTS_ID_CHECK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_id_sha256_check", "c"
    ),
    "PLACEMENTS_NONBLANK_CHECK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_nonblank_check", "c"
    ),
    "PLACEMENTS_PRIMARY_CONSTRAINT_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_pkey", "p"
    ),
    "PLACEMENTS_REVIEW_STATUS_CHECK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_review_status_check", "c"
    ),
    "PLACEMENTS_SCHOOL_YEAR_CHECK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_school_year_check", "c"
    ),
    "PLACEMENTS_SOURCE_UNIQUE_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_source_unique", "u"
    ),
    "PLACEMENTS_STATUS_CHECK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_status_check", "c"
    ),
    "PLACEMENTS_VISIBILITY_CHECK_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_visibility_check", "c"
    ),
}

_INDEX_FINGERPRINT_KEYS: Final = {
    "RAG_CHUNKS_PROFILE_REVIEWED_INDEX_MD5": (
        "rag_chunks", "idx_rag_chunks_profile_reviewed"
    ),
    "RAG_CHUNKS_PRIMARY_INDEX_MD5": ("rag_chunks", "rag_chunks_pkey"),
    "IDX_RAG_CHUNKS_ARTIFACT_UNIQUE_MD5": (
        "rag_chunks", "idx_rag_chunks_artifact_chunk_index_unique"
    ),
    "IDX_RAG_CHUNKS_ARTIFACT_ID_MD5": ("rag_chunks", "idx_rag_chunks_artifact_id"),
    "IDX_RAG_CHUNKS_AUDIENCE_MD5": ("rag_chunks", "idx_rag_chunks_audience"),
    "IDX_RAG_CHUNKS_COLLECTION_MD5": ("rag_chunks", "idx_rag_chunks_collection"),
    "IDX_RAG_CHUNKS_MATIERE_MD5": ("rag_chunks", "idx_rag_chunks_matiere"),
    "IDX_RAG_CHUNKS_NIVEAU_MD5": ("rag_chunks", "idx_rag_chunks_niveau"),
    "IDX_RAG_CHUNKS_REVIEW_MD5": ("rag_chunks", "idx_rag_chunks_review"),
    "IDX_RAG_CHUNKS_RIGHTS_MD5": ("rag_chunks", "idx_rag_chunks_rights"),
    "IDX_RAG_CHUNKS_TEXT_TSV_MD5": ("rag_chunks", "idx_rag_chunks_text_tsv"),
    "IDX_RAG_CHUNKS_VECTOR_MD5": ("rag_chunks", "idx_rag_chunks_vector"),
    "RAG_ARTIFACTS_CONTENT_INDEX_MD5": (
        "rag_artifacts", "rag_artifacts_content_sha256_key"
    ),
    "RAG_ARTIFACTS_PRIMARY_INDEX_MD5": ("rag_artifacts", "rag_artifacts_pkey"),
    "PLACEMENTS_ARTIFACT_INDEX_MD5": (
        "rag_artifact_placements", "idx_rag_artifact_placements_artifact_id"
    ),
    "PLACEMENTS_AUDIENCE_INDEX_MD5": (
        "rag_artifact_placements", "idx_rag_artifact_placements_audience"
    ),
    "PLACEMENTS_SCOPE_INDEX_MD5": (
        "rag_artifact_placements", "idx_rag_artifact_placements_scope_active"
    ),
    "PLACEMENTS_CANONICAL_INDEX_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_canonical_scope_unique"
    ),
    "PLACEMENTS_PRIMARY_INDEX_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_pkey"
    ),
    "PLACEMENTS_SOURCE_INDEX_MD5": (
        "rag_artifact_placements", "rag_artifact_placements_source_unique"
    ),
}

_PREDICATE_FINGERPRINT_KEYS: Final = {
    "RAG_CHUNKS_PROFILE_REVIEWED_PREDICATE_MD5": (
        "rag_chunks.idx_rag_chunks_profile_reviewed"
    ),
    "IDX_RAG_CHUNKS_ARTIFACT_PREDICATE_MD5": (
        "rag_chunks.idx_rag_chunks_artifact_chunk_index_unique"
    ),
    # Le même prédicat exact est attendu sur les deux index artifact_id.
    "IDX_RAG_CHUNKS_ARTIFACT_ID_PREDICATE_MD5": (
        "rag_chunks.idx_rag_chunks_artifact_id"
    ),
    "PLACEMENTS_SCOPE_PREDICATE_MD5": (
        "rag_artifact_placements.idx_rag_artifact_placements_scope_active"
    ),
}
_TEXT_TSV_EXPRESSION_KEY: Final = "RAG_CHUNKS_TEXT_TSV_EXPRESSION_MD5"
_MD5 = re.compile(r"[0-9a-f]{32}")


def _default_fingerprint_path() -> Path:
    configured = os.environ.get("RAG_SCHEMA_HEAD_FINGERPRINTS", "").strip()
    if configured:
        return Path(configured)
    packaged = Path(__file__).resolve().with_name("schema_head_004_fingerprints.env")
    if packaged.is_file():
        return packaged
    return (
        Path(__file__).resolve().parents[2]
        / "infra"
        / "postgres"
        / "schema_head_004_fingerprints.env"
    )


def load_schema_head_004_fingerprints(path: Path | None = None) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        for line in (path or _default_fingerprint_path()).read_text(
            encoding="utf-8"
        ).splitlines():
            key, separator, value = line.partition("=")
            if not separator or key in values or _MD5.fullmatch(value) is None:
                raise RuntimeError("SCHEMA_HEAD_004_FINGERPRINTS_INVALID")
            values[key] = value
    except OSError as exc:
        raise RuntimeError("SCHEMA_HEAD_004_FINGERPRINTS_UNAVAILABLE") from exc
    expected_keys = {
        *_CONSTRAINT_FINGERPRINT_KEYS,
        *_INDEX_FINGERPRINT_KEYS,
        *_PREDICATE_FINGERPRINT_KEYS,
        _TEXT_TSV_EXPRESSION_KEY,
    }
    if set(values) != expected_keys:
        raise RuntimeError("SCHEMA_HEAD_004_FINGERPRINTS_INVALID")
    return values


def load_schema_head_003_fingerprints(path: Path | None = None) -> dict[str, str]:
    """Alias de compatibilité ; la sémantique vérifiée est désormais 004."""
    return load_schema_head_004_fingerprints(path)


_FINGERPRINTS = load_schema_head_004_fingerprints()
REQUIRED_PRODUCT_CONSTRAINT_DEFINITIONS: Final[
    dict[str, dict[str, list[object]]]
] = {
    table: {} for table in REQUIRED_PRODUCT_TABLES
}
for key, (table, constraint_name, constraint_type) in _CONSTRAINT_FINGERPRINT_KEYS.items():
    REQUIRED_PRODUCT_CONSTRAINT_DEFINITIONS[table][constraint_name] = [
        constraint_type,
        True,
        _FINGERPRINTS[key],
    ]

REQUIRED_PRODUCT_INDEX_DEFINITIONS: Final[
    dict[str, dict[str, list[object]]]
] = {
    table: {} for table in REQUIRED_PRODUCT_TABLES
}
for key, (table, index_name) in _INDEX_FINGERPRINT_KEYS.items():
    REQUIRED_PRODUCT_INDEX_DEFINITIONS[table][index_name] = [
        _FINGERPRINTS[key],
        True,
        True,
    ]

REQUIRED_PRODUCT_INDEX_PREDICATES: Final = {
    qualified_name: _FINGERPRINTS[key]
    for key, qualified_name in _PREDICATE_FINGERPRINT_KEYS.items()
}
REQUIRED_RAG_CHUNKS_CONSTRAINT_DEFINITIONS: Final = (
    REQUIRED_PRODUCT_CONSTRAINT_DEFINITIONS["rag_chunks"]
)
REQUIRED_RAG_CHUNKS_INDEX_DEFINITIONS: Final = (
    REQUIRED_PRODUCT_INDEX_DEFINITIONS["rag_chunks"]
)
REQUIRED_PROFILE_INDEX_DEFINITION: Final = (
    REQUIRED_RAG_CHUNKS_INDEX_DEFINITIONS["idx_rag_chunks_profile_reviewed"]
)
REQUIRED_PROFILE_INDEX_PREDICATE: Final = REQUIRED_PRODUCT_INDEX_PREDICATES[
    "rag_chunks.idx_rag_chunks_profile_reviewed"
]
REQUIRED_TEXT_TSV_EXPRESSION: Final = _FINGERPRINTS[_TEXT_TSV_EXPRESSION_KEY]
REQUIRED_PRODUCT_TABLE_STATES: Final = {
    table: ["p", False, False, []] for table in REQUIRED_PRODUCT_TABLES
}
REQUIRED_RAG_CHUNKS_TABLE_STATE: Final = REQUIRED_PRODUCT_TABLE_STATES["rag_chunks"]
REQUIRED_PRODUCT_TRIGGER_DEFINITIONS: Final[
    dict[str, dict[str, list[object]]]
] = {
    table: {} for table in REQUIRED_PRODUCT_TABLES
}
REQUIRED_PRODUCT_RULE_DEFINITIONS: Final[
    dict[str, dict[str, list[object]]]
] = {
    table: {} for table in REQUIRED_PRODUCT_TABLES
}
REQUIRED_PRODUCT_INHERITANCE_DEFINITIONS: Final[list[object]] = []
REQUIRED_RAG_CHUNKS_TRIGGER_DEFINITIONS: Final[dict[str, list[str]]] = {}
REQUIRED_RAG_CHUNKS_RULE_DEFINITIONS: Final[dict[str, list[object]]] = {}
REQUIRED_RAG_CHUNKS_INHERITANCE_DEFINITIONS: Final[list[object]] = []

_SCHEMA_HEAD_004_SQL = """
WITH target_tables(table_name) AS (
    VALUES ('rag_artifact_placements'), ('rag_artifacts'), ('rag_chunks')
)
SELECT
    (SELECT jsonb_object_agg(target.table_name, COALESCE((
        SELECT jsonb_object_agg(
            column_definition.column_name,
            jsonb_build_array(
                column_definition.data_type, column_definition.udt_name,
                column_definition.is_nullable, column_definition.is_generated,
                column_definition.column_default,
                format_type(attribute.atttypid, attribute.atttypmod),
                attribute.atttypmod
            )
        )
        FROM information_schema.columns AS column_definition
        JOIN pg_attribute AS attribute
          ON attribute.attrelid = to_regclass('public.' || target.table_name)
         AND attribute.attname = column_definition.column_name
         AND attribute.attnum > 0 AND NOT attribute.attisdropped
        WHERE column_definition.table_schema = 'public'
          AND column_definition.table_name = target.table_name
    ), '{}'::jsonb)) FROM target_tables AS target),
    (SELECT jsonb_object_agg(target.table_name, COALESCE((
        SELECT jsonb_object_agg(
            constraint_definition.conname,
            jsonb_build_array(
                constraint_definition.contype,
                constraint_definition.convalidated,
                md5(pg_get_constraintdef(constraint_definition.oid, true))
            )
        )
        FROM pg_constraint AS constraint_definition
        WHERE constraint_definition.conrelid =
              to_regclass('public.' || target.table_name)
    ), '{}'::jsonb)) FROM target_tables AS target),
    (SELECT jsonb_object_agg(target.table_name, COALESCE((
        SELECT jsonb_object_agg(
            index_relation.relname,
            jsonb_build_array(
                md5(pg_get_indexdef(index_definition.indexrelid)),
                index_definition.indisvalid, index_definition.indisready
            )
        )
        FROM pg_index AS index_definition
        JOIN pg_class AS index_relation
          ON index_relation.oid = index_definition.indexrelid
        WHERE index_definition.indrelid =
              to_regclass('public.' || target.table_name)
    ), '{}'::jsonb)) FROM target_tables AS target),
    COALESCE((
        SELECT jsonb_object_agg(
            table_definition.relname || '.' || index_relation.relname,
            md5(pg_get_expr(index_definition.indpred,
                            index_definition.indrelid, true))
        )
        FROM pg_index AS index_definition
        JOIN pg_class AS index_relation
          ON index_relation.oid = index_definition.indexrelid
        JOIN pg_class AS table_definition
          ON table_definition.oid = index_definition.indrelid
        WHERE table_definition.relname IN (SELECT table_name FROM target_tables)
          AND index_definition.indpred IS NOT NULL
    ), '{}'::jsonb),
    (SELECT md5(pg_get_expr(generated_definition.adbin,
                            generated_definition.adrelid, true))
     FROM pg_attrdef AS generated_definition
     JOIN pg_attribute AS generated_column
       ON generated_column.attrelid = generated_definition.adrelid
      AND generated_column.attnum = generated_definition.adnum
     WHERE generated_definition.adrelid = 'public.rag_chunks'::regclass
       AND generated_column.attname = 'text_tsv'
       AND generated_column.attgenerated = 's'),
    COALESCE((SELECT jsonb_agg(jsonb_build_array(version, file_name, sha256)
                              ORDER BY version)
              FROM public.rag_schema_migrations), '[]'::jsonb),
    (SELECT jsonb_object_agg(target.table_name, (
        SELECT jsonb_build_array(
            table_definition.relpersistence, table_definition.relrowsecurity,
            table_definition.relforcerowsecurity,
            COALESCE((SELECT jsonb_agg(policy.polname ORDER BY policy.polname)
                      FROM pg_policy AS policy
                      WHERE policy.polrelid = table_definition.oid), '[]'::jsonb)
        )
        FROM pg_class AS table_definition
        WHERE table_definition.oid = to_regclass('public.' || target.table_name)
    )) FROM target_tables AS target),
    (SELECT jsonb_object_agg(target.table_name, COALESCE((
        SELECT jsonb_object_agg(
            trigger_definition.tgname,
            jsonb_build_array(trigger_definition.tgenabled,
                              md5(pg_get_triggerdef(trigger_definition.oid, true)))
        )
        FROM pg_trigger AS trigger_definition
        WHERE trigger_definition.tgrelid =
              to_regclass('public.' || target.table_name)
          AND NOT trigger_definition.tgisinternal
    ), '{}'::jsonb)) FROM target_tables AS target),
    (SELECT jsonb_object_agg(target.table_name, COALESCE((
        SELECT jsonb_object_agg(
            rewrite_definition.rulename,
            jsonb_build_array(
                rewrite_definition.ev_type, rewrite_definition.is_instead,
                rewrite_definition.ev_enabled,
                md5(pg_get_ruledef(rewrite_definition.oid, true))
            )
        )
        FROM pg_rewrite AS rewrite_definition
        WHERE rewrite_definition.ev_class =
              to_regclass('public.' || target.table_name)
    ), '{}'::jsonb)) FROM target_tables AS target),
    COALESCE((
        SELECT jsonb_agg(jsonb_build_array(
            inheritance_definition.inhparent::regclass::text,
            inheritance_definition.inhrelid::regclass::text,
            inheritance_definition.inhseqno,
            inheritance_definition.inhdetachpending
        ) ORDER BY inheritance_definition.inhparent,
                   inheritance_definition.inhseqno,
                   inheritance_definition.inhrelid)
        FROM pg_inherits AS inheritance_definition
        WHERE inheritance_definition.inhparent IN (
                  SELECT to_regclass('public.' || table_name) FROM target_tables
              )
           OR inheritance_definition.inhrelid IN (
                  SELECT to_regclass('public.' || table_name) FROM target_tables
              )
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
    root = migration_root or _default_migration_root()
    return tuple(
        (version, file_name, sha256((root / file_name).read_bytes()).hexdigest())
        for version, file_name in REQUIRED_MIGRATIONS
    )


def schema_head_004_ready(dsn: str) -> bool:
    """Prouver en lecture seule le registre et la forme exacte du head 004."""
    with psycopg.connect(
        dsn,
        connect_timeout=readiness_connect_timeout_s(),
        options=readiness_connection_options(),
    ) as connection:
        with connection.cursor() as cursor:
            apply_readiness_statement_budget(cursor)
            cursor.execute(_SCHEMA_HEAD_004_SQL)
            row = cursor.fetchone()

    if row is None or len(row) != 10:
        return False
    (
        columns,
        constraints,
        index_definitions,
        index_predicates,
        text_tsv_expression,
        migrations,
        table_states,
        trigger_definitions,
        rule_definitions,
        inheritance_definitions,
    ) = row
    return bool(
        columns == REQUIRED_PRODUCT_COLUMN_DEFINITIONS
        and constraints == REQUIRED_PRODUCT_CONSTRAINT_DEFINITIONS
        and index_definitions == REQUIRED_PRODUCT_INDEX_DEFINITIONS
        and index_predicates == REQUIRED_PRODUCT_INDEX_PREDICATES
        and text_tsv_expression == REQUIRED_TEXT_TSV_EXPRESSION
        and migrations == [list(item) for item in expected_migration_records()]
        and table_states == REQUIRED_PRODUCT_TABLE_STATES
        and trigger_definitions == REQUIRED_PRODUCT_TRIGGER_DEFINITIONS
        and rule_definitions == REQUIRED_PRODUCT_RULE_DEFINITIONS
        and inheritance_definitions == REQUIRED_PRODUCT_INHERITANCE_DEFINITIONS
    )


def schema_head_003_ready(dsn: str) -> bool:
    """Alias temporaire pour les appelants LOT40 ; vérifie réellement 004."""
    return schema_head_004_ready(dsn)


__all__ = [
    "READINESS_CONNECT_TIMEOUT_S",
    "READINESS_STATEMENT_TIMEOUT_MS",
    "REQUIRED_PRODUCT_COLUMN_DEFINITIONS",
    "REQUIRED_PRODUCT_CONSTRAINT_DEFINITIONS",
    "REQUIRED_PRODUCT_INDEX_DEFINITIONS",
    "REQUIRED_PRODUCT_INDEX_PREDICATES",
    "REQUIRED_PRODUCT_INHERITANCE_DEFINITIONS",
    "REQUIRED_PRODUCT_RULE_DEFINITIONS",
    "REQUIRED_PRODUCT_TABLE_STATES",
    "REQUIRED_PRODUCT_TRIGGER_DEFINITIONS",
    "REQUIRED_RAG_CHUNKS_COLUMN_DEFINITIONS",
    "REQUIRED_RAG_CHUNKS_CONSTRAINT_DEFINITIONS",
    "REQUIRED_RAG_CHUNKS_INDEX_DEFINITIONS",
    "REQUIRED_RAG_CHUNKS_INHERITANCE_DEFINITIONS",
    "REQUIRED_RAG_CHUNKS_RULE_DEFINITIONS",
    "REQUIRED_RAG_CHUNKS_TABLE_STATE",
    "REQUIRED_RAG_CHUNKS_TRIGGER_DEFINITIONS",
    "REQUIRED_PROFILE_COLUMN_DEFINITIONS",
    "REQUIRED_PROFILE_INDEX_DEFINITION",
    "REQUIRED_PROFILE_INDEX_PREDICATE",
    "REQUIRED_TEXT_TSV_EXPRESSION",
    "expected_migration_records",
    "load_product_column_definitions",
    "load_rag_chunks_column_definitions",
    "load_schema_head_003_fingerprints",
    "load_schema_head_004_fingerprints",
    "schema_head_003_ready",
    "schema_head_004_ready",
]
