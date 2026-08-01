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
      AND c.relkind IN ('r', 'p');
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: rag_chunks table';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM unnest(ARRAY[
        'chunk_id', 'doc_id', 'chunk_sha256', 'vector', 'collection',
        'niveau', 'voie', 'audience', 'matiere', 'statut_enseignement',
        'notions', 'domain', 'source_label', 'source_uri', 'rights',
        'type_doc', 'official', 'text', 'chunk_index', 'page_start',
        'page_end', 'review_status', 'model', 'source_kind', 'indexed_at'
    ]::text[]) AS required(column_name)
    WHERE NOT EXISTS (
        SELECT 1
        FROM information_schema.columns actual
        WHERE actual.table_schema = 'public'
          AND actual.table_name = 'rag_chunks'
          AND actual.column_name = required.column_name
    );
    IF invalid_count <> 0 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: required columns';
    END IF;

    SELECT count(*) INTO invalid_count
    FROM pg_attribute a
    WHERE a.attrelid = 'public.rag_chunks'::regclass
      AND a.attname = 'vector'
      AND NOT a.attisdropped
      AND format_type(a.atttypid, a.atttypmod) = 'vector(1024)';
    IF invalid_count <> 1 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: vector(1024)';
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

    SELECT count(DISTINCT index_class.relname) INTO invalid_count
    FROM pg_index i
    JOIN pg_class table_class ON table_class.oid = i.indrelid
    JOIN pg_namespace table_namespace ON table_namespace.oid = table_class.relnamespace
    JOIN pg_class index_class ON index_class.oid = i.indexrelid
    WHERE table_namespace.nspname = 'public'
      AND table_class.relname = 'rag_chunks'
      AND i.indisvalid
      AND index_class.relname = ANY (ARRAY[
          'rag_chunks_pkey',
          'idx_rag_chunks_vector',
          'idx_rag_chunks_collection',
          'idx_rag_chunks_niveau',
          'idx_rag_chunks_matiere',
          'idx_rag_chunks_audience',
          'idx_rag_chunks_rights',
          'idx_rag_chunks_review'
      ]::text[]);
    IF invalid_count <> 8 THEN
        RAISE EXCEPTION 'SCHEMA_HEAD_001_INVALID: eight indexes';
    END IF;
END
$nexus$;
SQL
}

validate_002_sql() {
    cat <<'SQL'
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
