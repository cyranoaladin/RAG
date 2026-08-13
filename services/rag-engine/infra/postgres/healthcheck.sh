#!/usr/bin/env bash
# Readiness PostgreSQL du head canonique 004, sans mutation.
set -euo pipefail

migration_root=/docker-entrypoint-migrations
fingerprints_file=/schema-head-004-fingerprints.env
columns_file=/schema-head-004-columns.tsv
validator_library=/pgvector-migration-state.sh
postgres_user="${POSTGRES_USER:-postgres}"
postgres_db="${POSTGRES_DB:-$postgres_user}"

for required_file in \
    "$fingerprints_file" \
    "$columns_file" \
    "$validator_library" \
    "$migration_root/HEAD"; do
    if [[ ! -r "$required_file" ]]; then
        printf '%s\n' "ERROR: contrat du schema head 004 absent." >&2
        exit 1
    fi
done

# La source d'empreintes est chargée pour refuser immédiatement une source
# malformée ; les définitions structurelles sont ensuite revérifiées par les
# validateurs SQL partagés avec l'upgrade/rollback.
# shellcheck disable=SC1091
source "$fingerprints_file"
# shellcheck disable=SC1091
source "$validator_library"
discover_manifest "$migration_root" "$migration_root/HEAD"
if [[ "$MIGRATION_DECLARED_HEAD" != "004_artifact_placements" ]]; then
    printf '%s\n' "ERROR: HEAD PostgreSQL inattendu." >&2
    exit 1
fi

pg_isready \
    --username "$postgres_user" \
    --dbname "$postgres_db" \
    --timeout 3 >/dev/null

{
    validate_001_sql
    validate_002_sql
    validate_003_sql
    validate_004_sql
    validate_registry_sql 4
    cat <<'SQL'
BEGIN;
CREATE TEMP TABLE expected_product_columns (
    table_name text,
    column_name text,
    data_type text,
    udt_name text,
    is_nullable text,
    is_generated text,
    column_default text,
    formatted_type text,
    atttypmod integer,
    PRIMARY KEY (table_name, column_name)
) ON COMMIT DROP;
\copy expected_product_columns FROM '/schema-head-004-columns.tsv' WITH (FORMAT csv, DELIMITER E'\t', NULL '\N', HEADER true)

DO $nexus$
DECLARE
    invalid_count integer;
BEGIN
    SELECT count(*) INTO invalid_count
    FROM information_schema.columns actual
    WHERE actual.table_schema = 'public'
      AND actual.table_name IN (
          'rag_chunks', 'rag_artifacts', 'rag_artifact_placements'
      );
    IF invalid_count <> (SELECT count(*) FROM expected_product_columns) THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: exact column count';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM expected_product_columns expected
    LEFT JOIN information_schema.columns actual
      ON actual.table_schema = 'public'
     AND actual.table_name = expected.table_name
     AND actual.column_name = expected.column_name
    LEFT JOIN pg_attribute attribute
      ON attribute.attrelid = to_regclass('public.' || expected.table_name)
     AND attribute.attname = expected.column_name
     AND attribute.attnum > 0
     AND NOT attribute.attisdropped
    WHERE actual.column_name IS NULL
       OR actual.data_type IS DISTINCT FROM expected.data_type
       OR actual.udt_name IS DISTINCT FROM expected.udt_name
       OR actual.is_nullable IS DISTINCT FROM expected.is_nullable
       OR actual.is_generated IS DISTINCT FROM expected.is_generated
       OR actual.column_default IS DISTINCT FROM expected.column_default
       OR format_type(attribute.atttypid, attribute.atttypmod)
            IS DISTINCT FROM expected.formatted_type
       OR attribute.atttypmod IS DISTINCT FROM expected.atttypmod;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: exact column matrix';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_class table_definition
    WHERE table_definition.oid IN (
        'public.rag_chunks'::regclass,
        'public.rag_artifacts'::regclass,
        'public.rag_artifact_placements'::regclass
    )
      AND table_definition.relpersistence = 'p'
      AND NOT table_definition.relrowsecurity
      AND NOT table_definition.relforcerowsecurity;
    IF invalid_count <> 3 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: table state';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_policy
    WHERE polrelid IN (
        'public.rag_chunks'::regclass,
        'public.rag_artifacts'::regclass,
        'public.rag_artifact_placements'::regclass
    );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: unexpected policy';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_trigger
    WHERE tgrelid IN (
        'public.rag_chunks'::regclass,
        'public.rag_artifacts'::regclass,
        'public.rag_artifact_placements'::regclass
    ) AND NOT tgisinternal;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: unexpected trigger';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_inherits
    WHERE inhparent IN (
        'public.rag_chunks'::regclass,
        'public.rag_artifacts'::regclass,
        'public.rag_artifact_placements'::regclass
    ) OR inhrelid IN (
        'public.rag_chunks'::regclass,
        'public.rag_artifacts'::regclass,
        'public.rag_artifact_placements'::regclass
    );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: unexpected inheritance';
    END IF;
END
$nexus$;
COMMIT;
SQL
} | psql \
    --username "$postgres_user" \
    --dbname "$postgres_db" \
    --set ON_ERROR_STOP=1 \
    --quiet >/dev/null
