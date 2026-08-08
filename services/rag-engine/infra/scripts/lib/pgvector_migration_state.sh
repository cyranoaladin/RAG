#!/usr/bin/env bash
# Shared, side-effect-free pgvector migration manifest and SQL validators.

discover_manifest() {
    local migrations_dir="$1"
    local head_file="$2"
    local entry basename number stem expected digest head_raw
    local -a candidates=()
    local -a manifest_entries=()
    local -A seen_versions=()

    export LC_ALL=C
    MIGRATION_VERSIONS=()
    MIGRATION_NAMES=()
    MIGRATION_FILES=()
    MIGRATION_SHA256=()

    if [[ ! -d "$migrations_dir" ]]; then
        echo "MIGRATION_DIRECTORY_MISSING" >&2
        return 1
    fi
    if [[ ! -f "$head_file" || -L "$head_file" ]]; then
        echo "MIGRATION_HEAD_MISSING" >&2
        return 1
    fi

    shopt -s nullglob
    manifest_entries=("$migrations_dir"/*.sql)
    shopt -u nullglob
    if [[ ${#manifest_entries[@]} -eq 0 ]]; then
        echo "MIGRATION_MANIFEST_EMPTY" >&2
        return 1
    fi

    for entry in "${manifest_entries[@]}"; do
        if [[ ! -f "$entry" || -L "$entry" ]]; then
            echo "MIGRATION_FILE_NOT_REGULAR: $(basename "$entry")" >&2
            return 1
        fi
        basename="$(basename "$entry")"
        if [[ ! "$basename" =~ ^[0-9]{3}_[a-z0-9_]+\.sql$ ]]; then
            echo "MIGRATION_NAME_INVALID: $basename" >&2
            return 1
        fi
    done

    mapfile -t candidates < <(
        find "$migrations_dir" -maxdepth 1 -type f \
            -name '[0-9][0-9][0-9]_*.sql' -print | LC_ALL=C sort
    )
    expected=1
    for entry in "${candidates[@]}"; do
        basename="$(basename "$entry")"
        if [[ ! "$basename" =~ ^([0-9]{3})_([a-z0-9_]+)\.sql$ ]]; then
            echo "MIGRATION_NAME_INVALID: $basename" >&2
            return 1
        fi
        number=$((10#${BASH_REMATCH[1]}))
        if [[ -n "${seen_versions[$number]:-}" ]]; then
            echo "MIGRATION_DUPLICATE: $number" >&2
            return 1
        fi
        seen_versions[$number]=1
        if (( number != expected )); then
            echo "MIGRATION_GAP: expected $(printf '%03d' "$expected"), got $(printf '%03d' "$number")" >&2
            return 1
        fi
        digest="$(sha256sum "$entry" | awk '{print $1}')"
        if [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
            echo "MIGRATION_SHA256_INVALID: $basename" >&2
            return 1
        fi
        MIGRATION_VERSIONS+=("$number")
        MIGRATION_NAMES+=("$basename")
        MIGRATION_FILES+=("$entry")
        MIGRATION_SHA256+=("$digest")
        expected=$((expected + 1))
    done

    stem="${MIGRATION_NAMES[${#MIGRATION_NAMES[@]} - 1]%.sql}"
    head_raw="$(cat "$head_file"; printf x)"
    head_raw="${head_raw%x}"
    if [[ "$head_raw" != "$stem" && "$head_raw" != "$stem"$'\n' ]]; then
        echo "MIGRATION_HEAD_INVALID: expected $stem" >&2
        return 1
    fi
    MIGRATION_DECLARED_HEAD="$stem"
}

create_manifest_snapshot() {
    local source_dir="$1"
    local source_head="$2"
    local source_rollback="${3:-}"
    local index snapshot_file rollback_dir

    MIGRATION_SOURCE_FILES=("${MIGRATION_FILES[@]}")
    MIGRATION_SOURCE_SHA256=("${MIGRATION_SHA256[@]}")
    MIGRATION_SOURCE_HEAD_FILE="$source_head"
    MIGRATION_SOURCE_ROLLBACK_FILE="$source_rollback"
    MIGRATION_SNAPSHOT_FILES=()
    MIGRATION_SNAPSHOT_DIR="$(mktemp -d)"
    chmod 700 "$MIGRATION_SNAPSHOT_DIR"

    for ((index = 0; index < ${#MIGRATION_SOURCE_FILES[@]}; index++)); do
        snapshot_file="$MIGRATION_SNAPSHOT_DIR/${MIGRATION_NAMES[$index]}"
        MIGRATION_SNAPSHOT_FILES+=("$snapshot_file")
        cp -- "${MIGRATION_SOURCE_FILES[$index]}" "$snapshot_file"
        chmod 400 "$snapshot_file"
    done

    snapshot_file="$MIGRATION_SNAPSHOT_DIR/HEAD"
    MIGRATION_SNAPSHOT_FILES+=("$snapshot_file")
    cp -- "$source_head" "$snapshot_file"
    chmod 400 "$snapshot_file"

    MIGRATION_ROLLBACK_FILE=""
    MIGRATION_ROLLBACK_SHA256=""
    if [[ -n "$source_rollback" ]]; then
        if [[ ! -f "$source_rollback" || -L "$source_rollback" ]]; then
            echo "ROLLBACK_FILE_INVALID" >&2
            return 1
        fi
        rollback_dir="$MIGRATION_SNAPSHOT_DIR/rollback"
        mkdir "$rollback_dir"
        chmod 700 "$rollback_dir"
        MIGRATION_ROLLBACK_FILE="$rollback_dir/$(basename "$source_rollback")"
        MIGRATION_SNAPSHOT_FILES+=("$MIGRATION_ROLLBACK_FILE")
        cp -- "$source_rollback" "$MIGRATION_ROLLBACK_FILE"
        chmod 400 "$MIGRATION_ROLLBACK_FILE"
        MIGRATION_ROLLBACK_SHA256="$(sha256sum "$MIGRATION_ROLLBACK_FILE" | awk '{print $1}')"
        chmod 500 "$rollback_dir"
    fi

    chmod 500 "$MIGRATION_SNAPSHOT_DIR"
    discover_manifest "$MIGRATION_SNAPSHOT_DIR" "$MIGRATION_SNAPSHOT_DIR/HEAD"
    if [[ "$source_dir" != "$(dirname "${MIGRATION_SOURCE_FILES[0]}")" ]]; then
        echo "MIGRATION_SOURCE_INVALID" >&2
        return 1
    fi
}

cleanup_manifest_snapshot() {
    local snapshot_dir="${MIGRATION_SNAPSHOT_DIR:-}"
    local snapshot_file rollback_dir

    [[ -n "$snapshot_dir" ]] || return 0
    if [[ ! -d "$snapshot_dir" || "$(basename "$snapshot_dir")" != tmp.* ]]; then
        echo "MIGRATION_SNAPSHOT_CLEANUP_REFUSED" >&2
        return 1
    fi

    chmod 700 "$snapshot_dir"
    rollback_dir="$snapshot_dir/rollback"
    if [[ -d "$rollback_dir" ]]; then
        chmod 700 "$rollback_dir"
    fi
    for snapshot_file in "${MIGRATION_SNAPSHOT_FILES[@]}"; do
        if [[ "$snapshot_file" != "$snapshot_dir/"* ]]; then
            echo "MIGRATION_SNAPSHOT_CLEANUP_REFUSED" >&2
            return 1
        fi
        [[ -e "$snapshot_file" ]] || continue
        if [[ ! -f "$snapshot_file" || -L "$snapshot_file" ]]; then
            echo "MIGRATION_SNAPSHOT_CLEANUP_REFUSED" >&2
            return 1
        fi
        chmod 600 "$snapshot_file"
        rm -f -- "$snapshot_file"
    done
    if [[ -d "$rollback_dir" ]]; then
        rmdir "$rollback_dir"
    fi
    rmdir "$snapshot_dir"
    MIGRATION_SNAPSHOT_DIR=""
    MIGRATION_SNAPSHOT_FILES=()
    MIGRATION_ROLLBACK_FILE=""
    MIGRATION_ROLLBACK_SHA256=""
}

advisory_lock_sql() {
    cat <<'SQL'
SELECT pg_advisory_xact_lock(hashtext('nexus-rag-schema-migrations'));
SQL
}

registry_schema_sql() {
    cat <<'SQL'
CREATE TABLE IF NOT EXISTS rag_schema_migrations (
    version integer PRIMARY KEY CHECK (version > 0),
    file_name text NOT NULL UNIQUE CHECK (btrim(file_name) <> ''),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT now()
);
SQL
}

validate_001_sql() {
    cat <<'SQL'
-- NEXUS_VALIDATE_SCHEMA_001
DO $nexus$
DECLARE
    invalid_count integer;
BEGIN
    SELECT count(*) INTO invalid_count
    FROM pg_extension
    WHERE extname = 'vector';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: vector extension';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relname = 'rag_chunks'
      AND c.relkind = 'r'
      AND c.relpersistence = 'p';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: rag_chunks table';
    END IF;

    WITH expected_columns(
        attname,
        formatted_type,
        not_null,
        default_expression,
        generated,
        identity_kind
    ) AS (
        VALUES
            ('chunk_id', 'text', true, '<none>', '', ''),
            ('doc_id', 'text', true, '<none>', '', ''),
            ('chunk_sha256', 'text', true, '<none>', '', ''),
            ('vector', 'vector(1024)', false, '<none>', '', ''),
            ('collection', 'text', true, '<none>', '', ''),
            ('niveau', 'text', true, '<none>', '', ''),
            ('voie', 'text', true, '''generale''', '', ''),
            ('audience', 'text[]', true, '''{tous}''', '', ''),
            ('matiere', 'text', true, '<none>', '', ''),
            ('statut_enseignement', 'text', true, '''unknown''', '', ''),
            ('notions', 'text[]', true, '''{}''', '', ''),
            ('domain', 'text', true, '''education''', '', ''),
            ('source_label', 'text', true, '<none>', '', ''),
            ('source_uri', 'text', true, '<none>', '', ''),
            ('rights', 'text', true, '<none>', '', ''),
            ('type_doc', 'text', true, '<none>', '', ''),
            ('official', 'boolean', true, 'false', '', ''),
            ('text', 'text', false, '<none>', '', ''),
            ('chunk_index', 'integer', true, '0', '', ''),
            ('page_start', 'integer', false, '<none>', '', ''),
            ('page_end', 'integer', false, '<none>', '', ''),
            ('review_status', 'text', true, '''needs_review''', '', ''),
            ('model', 'text', false, '<none>', '', ''),
            ('source_kind', 'text', true, '''unknown''', '', ''),
            ('indexed_at', 'timestamp with time zone', true, 'now()', '', '')
    ),
    actual_columns AS (
        SELECT
            attribute.attname,
            format_type(attribute.atttypid, attribute.atttypmod) AS formatted_type,
            attribute.attnotnull AS not_null,
            coalesce(
                regexp_replace(
                    lower(pg_get_expr(default_value.adbin, default_value.adrelid)),
                    '(::text\[\]|::text|[[:space:]])',
                    '',
                    'g'
                ),
                '<none>'
            ) AS default_expression,
            attribute.attgenerated AS generated,
            attribute.attidentity AS identity_kind,
            attribute.attcollation AS collation_oid,
            type_definition.typcollation AS default_collation
        FROM pg_attribute attribute
        JOIN pg_type type_definition ON type_definition.oid = attribute.atttypid
        LEFT JOIN pg_attrdef default_value
          ON default_value.adrelid = attribute.attrelid
         AND default_value.adnum = attribute.attnum
        WHERE attribute.attrelid = 'public.rag_chunks'::regclass
          AND attribute.attnum > 0
          AND NOT attribute.attisdropped
    )
    SELECT count(*) INTO invalid_count
    FROM expected_columns expected
    LEFT JOIN actual_columns actual USING (attname)
    WHERE actual.attname IS NULL
       OR actual.formatted_type IS DISTINCT FROM expected.formatted_type
       OR actual.not_null IS DISTINCT FROM expected.not_null
       OR actual.default_expression IS DISTINCT FROM expected.default_expression
       OR actual.generated IS DISTINCT FROM expected.generated
       OR actual.identity_kind IS DISTINCT FROM expected.identity_kind
       OR actual.collation_oid IS DISTINCT FROM actual.default_collation;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: exact column catalog matrix';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_attribute attribute
    WHERE attribute.attrelid = 'public.rag_chunks'::regclass
      AND attribute.attnum > 0
      AND NOT attribute.attisdropped
      AND attribute.attname NOT IN (
          'chunk_id', 'doc_id', 'chunk_sha256', 'vector', 'collection',
          'niveau', 'voie', 'audience', 'matiere', 'statut_enseignement',
          'notions', 'domain', 'source_label', 'source_uri', 'rights',
          'type_doc', 'official', 'text', 'chunk_index', 'page_start',
          'page_end', 'review_status', 'model', 'source_kind', 'indexed_at',
          'text_tsv', 'tenant', 'candidat', 'visibility', 'school_year',
          'programme_version', 'artifact_id'
      );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: unexpected columns';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint c
    WHERE c.conrelid = 'public.rag_chunks'::regclass
      AND c.contype = 'p'
      AND c.conname = 'rag_chunks_pkey'
      AND pg_get_constraintdef(c.oid, true) = 'PRIMARY KEY (chunk_id)';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: PRIMARY KEY (chunk_id)';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint constraint_definition
    WHERE constraint_definition.conrelid = 'public.rag_chunks'::regclass
      AND NOT (
          constraint_definition.contype = 'p'
          AND constraint_definition.conname = 'rag_chunks_pkey'
          AND pg_get_constraintdef(constraint_definition.oid, true) = 'PRIMARY KEY (chunk_id)'
      )
      AND constraint_definition.conname NOT IN (
          'rag_chunks_tenant_lot41_check',
          'rag_chunks_candidat_lot41_check',
          'rag_chunks_visibility_lot41_check',
          'rag_chunks_school_year_lot41_check',
          'rag_chunks_programme_version_lot41_check',
          'rag_chunks_artifact_id_fkey',
          'rag_chunks_governed_identity_check'
      );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: unexpected constraints';
    END IF;

    WITH expected_indexes(
        index_name,
        amname,
        is_unique,
        is_primary,
        key_column,
        opcname,
        index_options
    ) AS (
        VALUES
            ('rag_chunks_pkey', 'btree', true, true, 'chunk_id', 'text_ops', ''),
            ('idx_rag_chunks_vector', 'hnsw', false, false, 'vector', 'vector_cosine_ops', 'ef_construction=64,m=16'),
            ('idx_rag_chunks_collection', 'btree', false, false, 'collection', 'text_ops', ''),
            ('idx_rag_chunks_niveau', 'btree', false, false, 'niveau', 'text_ops', ''),
            ('idx_rag_chunks_matiere', 'btree', false, false, 'matiere', 'text_ops', ''),
            ('idx_rag_chunks_audience', 'gin', false, false, 'audience', 'array_ops', ''),
            ('idx_rag_chunks_rights', 'btree', false, false, 'rights', 'text_ops', ''),
            ('idx_rag_chunks_review', 'btree', false, false, 'review_status', 'text_ops', '')
    ),
    actual_indexes AS (
        SELECT
            index_class.relname AS index_name,
            access_method.amname,
            index_definition.indisunique AS is_unique,
            index_definition.indisprimary AS is_primary,
            key_attribute.attname AS key_column,
            operator_class.opcname,
            coalesce(
                (
                    SELECT string_agg(option_value, ',' ORDER BY option_value)
                    FROM unnest(index_class.reloptions) AS options(option_value)
                ),
                ''
            ) AS index_options,
            index_definition.indnkeyatts,
            index_definition.indnatts,
            index_definition.indisvalid,
            index_definition.indisready,
            index_definition.indisexclusion,
            index_definition.indnullsnotdistinct,
            index_definition.indoption[0] AS key_options,
            index_definition.indcollation[0] AS key_collation,
            key_attribute.attcollation AS column_collation,
            index_class.reltablespace,
            index_definition.indexprs,
            index_definition.indpred
        FROM pg_index index_definition
        JOIN pg_class table_class ON table_class.oid = index_definition.indrelid
        JOIN pg_namespace table_namespace ON table_namespace.oid = table_class.relnamespace
        JOIN pg_class index_class ON index_class.oid = index_definition.indexrelid
        JOIN pg_am access_method ON access_method.oid = index_class.relam
        JOIN pg_attribute key_attribute
          ON key_attribute.attrelid = table_class.oid
         AND key_attribute.attnum = index_definition.indkey[0]
        JOIN pg_opclass operator_class
          ON operator_class.oid = index_definition.indclass[0]
        WHERE table_namespace.nspname = 'public'
          AND table_class.relname = 'rag_chunks'
    )
    SELECT count(*) INTO invalid_count
    FROM expected_indexes expected
    LEFT JOIN actual_indexes actual USING (index_name)
    WHERE actual.index_name IS NULL
       OR actual.amname IS DISTINCT FROM expected.amname
       OR actual.is_unique IS DISTINCT FROM expected.is_unique
       OR actual.is_primary IS DISTINCT FROM expected.is_primary
       OR actual.key_column IS DISTINCT FROM expected.key_column
       OR actual.opcname IS DISTINCT FROM expected.opcname
       OR actual.index_options IS DISTINCT FROM expected.index_options
       OR actual.indnkeyatts IS DISTINCT FROM 1
       OR actual.indnatts IS DISTINCT FROM 1
       OR actual.indisvalid IS DISTINCT FROM true
       OR actual.indisready IS DISTINCT FROM true
       OR actual.indisexclusion IS DISTINCT FROM false
       OR actual.indnullsnotdistinct IS DISTINCT FROM false
       OR actual.key_options IS DISTINCT FROM 0
       OR actual.key_collation IS DISTINCT FROM actual.column_collation
       OR actual.reltablespace IS DISTINCT FROM 0::oid
       OR actual.indexprs IS NOT NULL
       OR actual.indpred IS NOT NULL;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: exact index catalog matrix';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_index index_definition
    JOIN pg_class table_class ON table_class.oid = index_definition.indrelid
    JOIN pg_namespace table_namespace ON table_namespace.oid = table_class.relnamespace
    JOIN pg_class index_class ON index_class.oid = index_definition.indexrelid
    WHERE table_namespace.nspname = 'public'
      AND table_class.relname = 'rag_chunks'
      AND index_class.relname NOT IN (
          'rag_chunks_pkey',
          'idx_rag_chunks_vector',
          'idx_rag_chunks_collection',
          'idx_rag_chunks_niveau',
          'idx_rag_chunks_matiere',
          'idx_rag_chunks_audience',
          'idx_rag_chunks_rights',
          'idx_rag_chunks_review',
          'idx_rag_chunks_text_tsv',
          'idx_rag_chunks_profile_reviewed',
          'idx_rag_chunks_artifact_chunk_index_unique',
          'idx_rag_chunks_artifact_id'
      );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: unexpected indexes';
    END IF;
END
$nexus$;
SQL
}

validate_002_sql() {
    cat <<'SQL'
-- NEXUS_VALIDATE_SCHEMA_002
DO $nexus$
DECLARE
    invalid_count integer;
BEGIN
    SELECT count(*) INTO invalid_count
    FROM pg_attribute a
    JOIN pg_attrdef d
      ON d.adrelid = a.attrelid
     AND d.adnum = a.attnum
    WHERE a.attrelid = 'public.rag_chunks'::regclass
      AND a.attname = 'text_tsv'
      AND a.attgenerated = 's'
      AND NOT a.attisdropped
      AND regexp_replace(
          lower(pg_get_expr(d.adbin, d.adrelid)),
          '(::regconfig|::text|[[:space:]])',
          '',
          'g'
      ) = 'to_tsvector(''french'',coalesce(text,''''))';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_002_INVALID: generated french text_tsv';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_index i
    JOIN pg_class table_class ON table_class.oid = i.indrelid
    JOIN pg_namespace table_namespace ON table_namespace.oid = table_class.relnamespace
    JOIN pg_class index_class ON index_class.oid = i.indexrelid
    JOIN pg_am access_method ON access_method.oid = index_class.relam
    WHERE table_namespace.nspname = 'public'
      AND table_class.relname = 'rag_chunks'
      AND index_class.relname = 'idx_rag_chunks_text_tsv'
      AND access_method.amname = 'gin'
      AND i.indisvalid
      AND regexp_replace(
          lower(pg_get_indexdef(i.indexrelid)),
          '[[:space:]]+',
          ' ',
          'g'
      ) = ANY (ARRAY[
          'create index idx_rag_chunks_text_tsv on public.rag_chunks using gin (text_tsv)',
          'create index idx_rag_chunks_text_tsv on rag_chunks using gin (text_tsv)'
      ]::text[]);
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_002_INVALID: exact GIN index';
    END IF;
END
$nexus$;
SQL
}

validate_002_absent_sql() {
    cat <<'SQL'
-- NEXUS_VALIDATE_SCHEMA_002_ABSENT
DO $nexus$
DECLARE
    invalid_count integer;
BEGIN
    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_chunks'
      AND column_name = 'text_tsv';
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: text_tsv still present';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_class index_class
    JOIN pg_namespace n ON n.oid = index_class.relnamespace
    WHERE n.nspname = 'public'
      AND index_class.relname = 'idx_rag_chunks_text_tsv';
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: hybrid GIN still present';
    END IF;
END
$nexus$;
SQL
}

validate_003_sql() {
    cat <<'SQL'
-- NEXUS_VALIDATE_SCHEMA_003
DO $nexus$
DECLARE
    invalid_count integer;
BEGIN
    WITH expected_columns(column_name) AS (
        VALUES
            ('tenant'),
            ('candidat'),
            ('visibility'),
            ('school_year'),
            ('programme_version')
    )
    SELECT count(*) INTO invalid_count
    FROM expected_columns expected
    LEFT JOIN information_schema.columns actual
      ON actual.table_schema = 'public'
     AND actual.table_name = 'rag_chunks'
     AND actual.column_name = expected.column_name
    WHERE actual.column_name IS NULL
       OR actual.data_type IS DISTINCT FROM 'text'
       OR actual.is_nullable IS DISTINCT FROM 'YES'
       OR actual.column_default IS NOT NULL;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_003_INVALID: exact nullable columns';
    END IF;

    WITH expected_constraints(constraint_name, column_name) AS (
        VALUES
            ('rag_chunks_tenant_lot41_check', 'tenant'),
            ('rag_chunks_candidat_lot41_check', 'candidat'),
            ('rag_chunks_visibility_lot41_check', 'visibility'),
            ('rag_chunks_school_year_lot41_check', 'school_year'),
            ('rag_chunks_programme_version_lot41_check', 'programme_version')
    ),
    actual_constraints AS (
        SELECT
            constraint_definition.conname AS constraint_name,
            attribute.attname AS column_name,
            constraint_definition.contype,
            constraint_definition.convalidated,
            cardinality(constraint_definition.conkey) AS key_count
        FROM pg_constraint constraint_definition
        JOIN pg_attribute attribute
          ON attribute.attrelid = constraint_definition.conrelid
         AND attribute.attnum = constraint_definition.conkey[1]
        WHERE constraint_definition.conrelid = 'public.rag_chunks'::regclass
    )
    SELECT count(*) INTO invalid_count
    FROM expected_constraints expected
    LEFT JOIN actual_constraints actual USING (constraint_name, column_name)
    WHERE actual.constraint_name IS NULL
       OR actual.contype IS DISTINCT FROM 'c'::"char"
       OR actual.convalidated IS DISTINCT FROM true
       OR actual.key_count IS DISTINCT FROM 1;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_003_INVALID: validated domain constraints';
    END IF;

    WITH actual_index AS (
        SELECT
            access_method.amname,
            index_definition.indisunique,
            index_definition.indisprimary,
            index_definition.indisvalid,
            index_definition.indisready,
            index_definition.indnkeyatts,
            index_definition.indnatts,
            index_definition.indexprs,
            regexp_replace(
                lower(pg_get_expr(
                    index_definition.indpred,
                    index_definition.indrelid
                )),
                '(::text|[[:space:]()])',
                '',
                'g'
            ) AS predicate,
            array_agg(attribute.attname ORDER BY key.ordinality) AS key_columns
        FROM pg_index index_definition
        JOIN pg_class index_class
          ON index_class.oid = index_definition.indexrelid
        JOIN pg_am access_method ON access_method.oid = index_class.relam
        JOIN unnest(index_definition.indkey)
             WITH ORDINALITY AS key(attnum, ordinality) ON true
        JOIN pg_attribute attribute
          ON attribute.attrelid = index_definition.indrelid
         AND attribute.attnum = key.attnum
        WHERE index_definition.indrelid = 'public.rag_chunks'::regclass
          AND index_class.relname = 'idx_rag_chunks_profile_reviewed'
        GROUP BY
            access_method.amname,
            index_definition.indisunique,
            index_definition.indisprimary,
            index_definition.indisvalid,
            index_definition.indisready,
            index_definition.indnkeyatts,
            index_definition.indnatts,
            index_definition.indexprs,
            index_definition.indpred,
            index_definition.indrelid
    )
    SELECT count(*) INTO invalid_count
    FROM actual_index
    WHERE amname <> 'btree'
       OR indisunique
       OR indisprimary
       OR NOT indisvalid
       OR NOT indisready
       OR indnkeyatts <> 11
       OR indnatts <> 11
       OR indexprs IS NOT NULL
       OR predicate <> 'review_status=''reviewed'''
       OR key_columns <> ARRAY[
            'collection', 'tenant', 'niveau', 'voie', 'matiere',
            'statut_enseignement', 'candidat', 'school_year',
            'programme_version', 'rights', 'visibility'
       ]::name[];
    IF invalid_count <> 0 OR NOT EXISTS (
        SELECT 1
        FROM pg_class index_class
        JOIN pg_index index_definition
          ON index_definition.indexrelid = index_class.oid
        WHERE index_definition.indrelid = 'public.rag_chunks'::regclass
          AND index_class.relname = 'idx_rag_chunks_profile_reviewed'
    ) THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_003_INVALID: exact partial profile index';
    END IF;
END
$nexus$;
SQL
}

validate_003_absent_sql() {
    cat <<'SQL'
-- NEXUS_VALIDATE_SCHEMA_003_ABSENT
DO $nexus$
DECLARE
    invalid_count integer;
BEGIN
    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_chunks'
      AND column_name IN (
          'tenant', 'candidat', 'visibility', 'school_year',
          'programme_version'
      );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_002_INVALID: LOT41 columns still present';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint constraint_definition
    WHERE constraint_definition.conrelid = 'public.rag_chunks'::regclass
      AND constraint_definition.conname IN (
          'rag_chunks_tenant_lot41_check',
          'rag_chunks_candidat_lot41_check',
          'rag_chunks_visibility_lot41_check',
          'rag_chunks_school_year_lot41_check',
          'rag_chunks_programme_version_lot41_check'
      );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_002_INVALID: LOT41 constraints still present';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_class index_class
    JOIN pg_namespace namespace_definition
      ON namespace_definition.oid = index_class.relnamespace
    WHERE namespace_definition.nspname = 'public'
      AND index_class.relname = 'idx_rag_chunks_profile_reviewed';
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_002_INVALID: LOT41 index still present';
    END IF;
END
$nexus$;
SQL
}

validate_004_sql() {
    cat <<'SQL'
-- NEXUS_VALIDATE_SCHEMA_004
DO $nexus$
DECLARE
    invalid_count integer;
BEGIN
    IF to_regclass('public.rag_artifacts') IS NULL
       OR to_regclass('public.rag_artifact_placements') IS NULL THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: product tables missing';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_chunks'
      AND column_name = 'artifact_id'
      AND data_type = 'text'
      AND is_nullable = 'YES'
      AND column_default IS NULL;
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: rag_chunks artifact_id';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_artifacts';
    IF invalid_count <> 10 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: rag_artifacts column count';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_artifact_placements';
    IF invalid_count <> 22 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: placements column count';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint
    WHERE conrelid IN (
        'public.rag_chunks'::regclass,
        'public.rag_artifacts'::regclass,
        'public.rag_artifact_placements'::regclass
    )
      AND convalidated
      AND conname IN (
        'rag_chunks_artifact_id_fkey',
        'rag_chunks_governed_identity_check',
        'rag_artifacts_pkey',
        'rag_artifacts_content_sha256_key',
        'rag_artifacts_identity_is_content_sha256_check',
        'rag_artifacts_artifact_id_sha256_check',
        'rag_artifact_placements_pkey',
        'rag_artifact_placements_artifact_id_fkey',
        'rag_artifact_placements_canonical_scope_unique',
        'rag_artifact_placements_source_unique',
        'rag_artifact_placements_currentness_check',
        'rag_artifact_placements_status_check',
        'rag_artifact_placements_review_status_check'
      );
    IF invalid_count <> 13 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: exact core constraints';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint
    WHERE conrelid = 'public.rag_artifacts'::regclass;
    IF invalid_count <> 9 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: rag_artifacts constraints';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint
    WHERE conrelid = 'public.rag_artifact_placements'::regclass;
    IF invalid_count <> 13 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: placement constraints';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint
    WHERE conrelid = 'public.rag_chunks'::regclass;
    IF invalid_count <> 8 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: rag_chunks constraints';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_class index_class
    JOIN pg_namespace namespace_definition
      ON namespace_definition.oid = index_class.relnamespace
    JOIN pg_index index_definition
      ON index_definition.indexrelid = index_class.oid
    WHERE namespace_definition.nspname = 'public'
      AND index_class.relname IN (
        'idx_rag_chunks_artifact_chunk_index_unique',
        'idx_rag_chunks_artifact_id',
        'idx_rag_artifact_placements_scope_active',
        'idx_rag_artifact_placements_audience',
        'idx_rag_artifact_placements_artifact_id'
      )
      AND index_definition.indisvalid
      AND index_definition.indisready;
    IF invalid_count <> 5 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: product indexes';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_index
    WHERE indrelid = 'public.rag_artifacts'::regclass;
    IF invalid_count <> 2 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: rag_artifacts indexes';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_index
    WHERE indrelid = 'public.rag_artifact_placements'::regclass;
    IF invalid_count <> 6 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: placement indexes';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_index
    WHERE indrelid = 'public.rag_chunks'::regclass;
    IF invalid_count <> 12 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: rag_chunks indexes';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_index index_definition
    JOIN pg_class index_class ON index_class.oid = index_definition.indexrelid
    WHERE index_definition.indrelid = 'public.rag_chunks'::regclass
      AND index_class.relname = 'idx_rag_chunks_artifact_chunk_index_unique'
      AND index_definition.indisunique
      AND pg_get_expr(index_definition.indpred, index_definition.indrelid)
            = '(artifact_id IS NOT NULL)';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_004_INVALID: governed chunk uniqueness';
    END IF;
END
$nexus$;
SQL
}

validate_004_absent_sql() {
    cat <<'SQL'
-- NEXUS_VALIDATE_SCHEMA_004_ABSENT
DO $nexus$
DECLARE
    invalid_count integer;
BEGIN
    IF to_regclass('public.rag_artifacts') IS NOT NULL
       OR to_regclass('public.rag_artifact_placements') IS NOT NULL THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_003_INVALID: product tables still present';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_chunks'
      AND column_name = 'artifact_id';
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_003_INVALID: artifact_id still present';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_class index_class
    JOIN pg_namespace namespace_definition
      ON namespace_definition.oid = index_class.relnamespace
    WHERE namespace_definition.nspname = 'public'
      AND index_class.relname IN (
        'idx_rag_chunks_artifact_chunk_index_unique',
        'idx_rag_chunks_artifact_id',
        'idx_rag_artifact_placements_scope_active',
        'idx_rag_artifact_placements_audience',
        'idx_rag_artifact_placements_artifact_id'
      );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_003_INVALID: product indexes still present';
    END IF;
END
$nexus$;
SQL
}

validate_registry_sql() {
    local expected_head="$1"
    local expected_json="["
    local separator=""
    local index

    if (( expected_head < 1 || expected_head > ${#MIGRATION_VERSIONS[@]} )); then
        echo "MIGRATION_HEAD_INVALID: $expected_head" >&2
        return 1
    fi
    for ((index = 0; index < ${#MIGRATION_VERSIONS[@]}; index++)); do
        expected_json+="${separator}{\"version\":${MIGRATION_VERSIONS[$index]},\"file_name\":\"${MIGRATION_NAMES[$index]}\",\"sha256\":\"${MIGRATION_SHA256[$index]}\"}"
        separator=","
    done
    expected_json+="]"

    cat <<SQL
-- NEXUS_VALIDATE_REGISTRY
DO \$nexus\$
DECLARE
    expected_manifest jsonb := '$expected_json'::jsonb;
    expected_head integer := $expected_head;
    invalid_count integer;
    actual_count integer;
    actual_min integer;
    actual_max integer;
BEGIN
    IF to_regclass('public.rag_schema_migrations') IS NULL THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_MISSING';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_schema_migrations';
    IF invalid_count <> 4 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: column count';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_schema_migrations'
      AND column_name = 'version'
      AND data_type = 'integer'
      AND is_nullable = 'NO';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: version column';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint constraint_definition
    WHERE constraint_definition.conrelid = 'public.rag_schema_migrations'::regclass
      AND constraint_definition.contype = 'p'
      AND pg_get_constraintdef(constraint_definition.oid, true) = 'PRIMARY KEY (version)';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: version primary key';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint constraint_definition
    WHERE constraint_definition.conrelid = 'public.rag_schema_migrations'::regclass
      AND constraint_definition.contype = 'c'
      AND regexp_replace(
          lower(pg_get_expr(
              constraint_definition.conbin,
              constraint_definition.conrelid
          )),
          '(::text|[[:space:]])',
          '',
          'g'
      ) = \$constraint\$(version>0)\$constraint\$;
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: version positive check';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_schema_migrations'
      AND column_name = 'file_name'
      AND data_type = 'text'
      AND is_nullable = 'NO';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: file_name column';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint constraint_definition
    WHERE constraint_definition.conrelid = 'public.rag_schema_migrations'::regclass
      AND constraint_definition.contype = 'u'
      AND pg_get_constraintdef(constraint_definition.oid, true) = 'UNIQUE (file_name)';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: file_name unique';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint constraint_definition
    WHERE constraint_definition.conrelid = 'public.rag_schema_migrations'::regclass
      AND constraint_definition.contype = 'c'
      AND regexp_replace(
          lower(pg_get_expr(
              constraint_definition.conbin,
              constraint_definition.conrelid
          )),
          '(::text|[[:space:]])',
          '',
          'g'
      ) = \$constraint\$(btrim(file_name)<>'')\$constraint\$;
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: file_name nonblank check';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_schema_migrations'
      AND column_name = 'sha256'
      AND data_type = 'text'
      AND is_nullable = 'NO';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: sha256 column';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_constraint constraint_definition
    WHERE constraint_definition.conrelid = 'public.rag_schema_migrations'::regclass
      AND constraint_definition.contype = 'c'
      AND regexp_replace(
          lower(pg_get_expr(
              constraint_definition.conbin,
              constraint_definition.conrelid
          )),
          '(::text|[[:space:]])',
          '',
          'g'
      ) = \$constraint\$(sha256~'^[0-9a-f]{64}$')\$constraint\$;
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: sha256 lowercase64 check';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_attribute column_definition
    JOIN pg_attrdef default_definition
      ON default_definition.adrelid = column_definition.attrelid
     AND default_definition.adnum = column_definition.attnum
    WHERE column_definition.attrelid = 'public.rag_schema_migrations'::regclass
      AND column_definition.attname = 'applied_at'
      AND NOT column_definition.attisdropped
      AND column_definition.attnotnull
      AND format_type(
          column_definition.atttypid,
          column_definition.atttypmod
      ) = 'timestamp with time zone'
      AND pg_get_expr(
          default_definition.adbin,
          default_definition.adrelid
      ) = 'now()';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'MIGRATION_REGISTRY_SCHEMA_INVALID: applied_at contract';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM rag_schema_migrations actual
    WHERE NOT EXISTS (
        SELECT 1
        FROM jsonb_to_recordset(expected_manifest)
             AS expected(version integer, file_name text, sha256 text)
        WHERE expected.version = actual.version
    ) OR NOT EXISTS (
        SELECT 1
        FROM jsonb_to_recordset(expected_manifest)
             AS expected(version integer, file_name text, sha256 text)
        WHERE expected.file_name = actual.file_name
    );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'MIGRATION_UNKNOWN';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM rag_schema_migrations actual
    JOIN jsonb_to_recordset(expected_manifest)
         AS expected(version integer, file_name text, sha256 text)
      ON expected.version = actual.version
     AND expected.file_name = actual.file_name
    WHERE expected.sha256 <> actual.sha256;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'MIGRATION_CHECKSUM_MISMATCH';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM rag_schema_migrations actual
    JOIN jsonb_to_recordset(expected_manifest)
         AS expected(version integer, file_name text, sha256 text)
      ON expected.version = actual.version
    WHERE expected.file_name <> actual.file_name;
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'MIGRATION_ORDER_INVALID';
    END IF;

    SELECT count(*), min(version), max(version)
      INTO actual_count, actual_min, actual_max
    FROM rag_schema_migrations;
    SELECT count(*) INTO invalid_count
    FROM generate_series(1, expected_head) AS required(version)
    WHERE NOT EXISTS (
        SELECT 1
        FROM rag_schema_migrations actual
        WHERE actual.version = required.version
    );
    IF actual_count <> expected_head
       OR actual_min <> 1
       OR actual_max <> expected_head
       OR invalid_count <> 0 THEN
        RAISE EXCEPTION 'MIGRATION_GAP';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM rag_schema_migrations actual
    JOIN jsonb_to_recordset(expected_manifest)
         AS expected(version integer, file_name text, sha256 text)
      ON expected.version = actual.version
    WHERE actual.version <= expected_head
      AND (
          actual.file_name <> expected.file_name
          OR actual.sha256 <> expected.sha256
      );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'MIGRATION_HEAD_INVALID';
    END IF;
END
\$nexus\$;
SQL
}

read_migration_state_sql() {
    cat <<'SQL'
-- NEXUS_READ_MIGRATION_STATE
SELECT to_regclass('public.rag_schema_migrations') IS NOT NULL AS registry_present,
       to_regclass('public.rag_chunks') IS NOT NULL AS rag_chunks_present
\gset
\if :registry_present
\echo REGISTRY_PRESENT|1
\else
\echo REGISTRY_PRESENT|0
\endif
\if :rag_chunks_present
\echo RAG_CHUNKS_PRESENT|1
\else
\echo RAG_CHUNKS_PRESENT|0
\endif
\if :registry_present
SELECT 'MIGRATION|' || version || '|' || file_name || '|' || sha256
FROM rag_schema_migrations
ORDER BY version;
\endif
SQL
}

read_unregistered_hybrid_state_sql() {
    cat <<'SQL'
-- NEXUS_READ_UNREGISTERED_HYBRID_STATE
SELECT EXISTS (
           SELECT 1
           FROM information_schema.columns
           WHERE table_schema = 'public'
             AND table_name = 'rag_chunks'
             AND column_name = 'text_tsv'
       ) AS hybrid_column_present,
       to_regclass('public.idx_rag_chunks_text_tsv') IS NOT NULL
           AS hybrid_index_present
\gset
\if :hybrid_column_present
\echo HYBRID_COLUMN_PRESENT|1
\else
\echo HYBRID_COLUMN_PRESENT|0
\endif
\if :hybrid_index_present
\echo HYBRID_INDEX_PRESENT|1
\else
\echo HYBRID_INDEX_PRESENT|0
\endif
SQL
}

validate_registry_state() {
    local registry_present="$1"
    local index version expected_index

    EFFECTIVE_HEAD=0
    if [[ "$registry_present" == "0" ]]; then
        if [[ ${#APPLIED_VERSIONS[@]} -ne 0 ]]; then
            echo "MIGRATION_REGISTRY_STATE_INVALID" >&2
            return 1
        fi
        return 0
    fi
    if [[ "$registry_present" != "1" ]]; then
        echo "MIGRATION_REGISTRY_STATE_INVALID" >&2
        return 1
    fi
    if [[ ${#APPLIED_VERSIONS[@]} -eq 0 ]]; then
        echo "MIGRATION_GAP: empty registry" >&2
        return 1
    fi
    if [[ ${#APPLIED_VERSIONS[@]} -ne ${#APPLIED_NAMES[@]}
       || ${#APPLIED_VERSIONS[@]} -ne ${#APPLIED_SHA256[@]} ]]; then
        echo "MIGRATION_REGISTRY_STATE_INVALID" >&2
        return 1
    fi

    for ((index = 0; index < ${#APPLIED_VERSIONS[@]}; index++)); do
        version="${APPLIED_VERSIONS[$index]}"
        if [[ ! "$version" =~ ^[1-9][0-9]*$ ]]; then
            echo "MIGRATION_UNKNOWN: version $version" >&2
            return 1
        fi
        expected_index=$((version - 1))
        if (( expected_index >= ${#MIGRATION_VERSIONS[@]} )); then
            echo "MIGRATION_UNKNOWN: version $version" >&2
            return 1
        fi
        if [[ "${APPLIED_NAMES[$index]}" != "${MIGRATION_NAMES[$expected_index]}" ]]; then
            if [[ " ${MIGRATION_NAMES[*]} " == *" ${APPLIED_NAMES[$index]} "* ]]; then
                echo "MIGRATION_ORDER_INVALID: ${APPLIED_NAMES[$index]}" >&2
            else
                echo "MIGRATION_UNKNOWN: ${APPLIED_NAMES[$index]}" >&2
            fi
            return 1
        fi
        if [[ "${APPLIED_SHA256[$index]}" != "${MIGRATION_SHA256[$expected_index]}" ]]; then
            echo "MIGRATION_CHECKSUM_MISMATCH: ${APPLIED_NAMES[$index]}" >&2
            return 1
        fi
        if (( version != index + 1 )); then
            echo "MIGRATION_GAP: expected $((index + 1)), got $version" >&2
            return 1
        fi
        EFFECTIVE_HEAD="$version"
    done
}
