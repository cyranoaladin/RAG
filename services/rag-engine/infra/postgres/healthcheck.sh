#!/usr/bin/env bash
# Readiness PostgreSQL du head canonique 003, sans mutation.
set -euo pipefail

migration_root=/docker-entrypoint-migrations
fingerprints_file=/schema-head-003-fingerprints.env
migration_001_file=001_rag_chunks_v2_schema.sql
migration_002_file=002_hybrid_retrieval.sql
migration_003_file=003_profile_filtering.sql
postgres_user="${POSTGRES_USER:-postgres}"
postgres_db="${POSTGRES_DB:-$postgres_user}"

if [[ ! -r "$fingerprints_file" ]]; then
    printf '%s\n' "ERROR: empreintes du schema head 003 absentes." >&2
    exit 1
fi
# shellcheck disable=SC1091
source "$fingerprints_file"

pg_isready \
    --username "$postgres_user" \
    --dbname "$postgres_db" \
    --timeout 3 >/dev/null

migration_001_sha="$(sha256sum "$migration_root/$migration_001_file" | cut -d' ' -f1)"
migration_002_sha="$(sha256sum "$migration_root/$migration_002_file" | cut -d' ' -f1)"
migration_003_sha="$(sha256sum "$migration_root/$migration_003_file" | cut -d' ' -f1)"

psql \
    --username "$postgres_user" \
    --dbname "$postgres_db" \
    --set ON_ERROR_STOP=1 \
    --set "migration_001_sha=$migration_001_sha" \
    --set "migration_002_sha=$migration_002_sha" \
    --set "migration_003_sha=$migration_003_sha" \
    --set "candidat_constraint_md5=$RAG_CHUNKS_CANDIDAT_LOT41_CHECK_MD5" \
    --set "programme_constraint_md5=$RAG_CHUNKS_PROGRAMME_VERSION_LOT41_CHECK_MD5" \
    --set "school_year_constraint_md5=$RAG_CHUNKS_SCHOOL_YEAR_LOT41_CHECK_MD5" \
    --set "tenant_constraint_md5=$RAG_CHUNKS_TENANT_LOT41_CHECK_MD5" \
    --set "visibility_constraint_md5=$RAG_CHUNKS_VISIBILITY_LOT41_CHECK_MD5" \
    --set "profile_index_md5=$RAG_CHUNKS_PROFILE_REVIEWED_INDEX_MD5" \
    --set "profile_predicate_md5=$RAG_CHUNKS_PROFILE_REVIEWED_PREDICATE_MD5" \
    --set "rag_chunks_primary_index_md5=$RAG_CHUNKS_PRIMARY_INDEX_MD5" \
    --set "audience_index_md5=$IDX_RAG_CHUNKS_AUDIENCE_MD5" \
    --set "collection_index_md5=$IDX_RAG_CHUNKS_COLLECTION_MD5" \
    --set "matiere_index_md5=$IDX_RAG_CHUNKS_MATIERE_MD5" \
    --set "niveau_index_md5=$IDX_RAG_CHUNKS_NIVEAU_MD5" \
    --set "review_index_md5=$IDX_RAG_CHUNKS_REVIEW_MD5" \
    --set "rights_index_md5=$IDX_RAG_CHUNKS_RIGHTS_MD5" \
    --set "text_tsv_index_md5=$IDX_RAG_CHUNKS_TEXT_TSV_MD5" \
    --set "vector_index_md5=$IDX_RAG_CHUNKS_VECTOR_MD5" \
    --set "text_tsv_expression_md5=$RAG_CHUNKS_TEXT_TSV_EXPRESSION_MD5" \
    --tuples-only \
    --no-align <<'SQL' | grep -qx t
SELECT
    (SELECT count(*) = 31
     FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'rag_chunks')
    AND NOT EXISTS (
        SELECT 1
        FROM (VALUES
            ('chunk_id', 'text', 'text', 'NO', 'NEVER'),
            ('doc_id', 'text', 'text', 'NO', 'NEVER'),
            ('chunk_sha256', 'text', 'text', 'NO', 'NEVER'),
            ('vector', 'USER-DEFINED', 'vector', 'YES', 'NEVER'),
            ('collection', 'text', 'text', 'NO', 'NEVER'),
            ('niveau', 'text', 'text', 'NO', 'NEVER'),
            ('voie', 'text', 'text', 'NO', 'NEVER'),
            ('audience', 'ARRAY', '_text', 'NO', 'NEVER'),
            ('matiere', 'text', 'text', 'NO', 'NEVER'),
            ('statut_enseignement', 'text', 'text', 'NO', 'NEVER'),
            ('notions', 'ARRAY', '_text', 'NO', 'NEVER'),
            ('domain', 'text', 'text', 'NO', 'NEVER'),
            ('source_label', 'text', 'text', 'NO', 'NEVER'),
            ('source_uri', 'text', 'text', 'NO', 'NEVER'),
            ('rights', 'text', 'text', 'NO', 'NEVER'),
            ('type_doc', 'text', 'text', 'NO', 'NEVER'),
            ('official', 'boolean', 'bool', 'NO', 'NEVER'),
            ('text', 'text', 'text', 'YES', 'NEVER'),
            ('chunk_index', 'integer', 'int4', 'NO', 'NEVER'),
            ('page_start', 'integer', 'int4', 'YES', 'NEVER'),
            ('page_end', 'integer', 'int4', 'YES', 'NEVER'),
            ('review_status', 'text', 'text', 'NO', 'NEVER'),
            ('model', 'text', 'text', 'YES', 'NEVER'),
            ('source_kind', 'text', 'text', 'NO', 'NEVER'),
            ('indexed_at', 'timestamp with time zone', 'timestamptz', 'NO', 'NEVER'),
            ('text_tsv', 'tsvector', 'tsvector', 'YES', 'ALWAYS'),
            ('tenant', 'text', 'text', 'YES', 'NEVER'),
            ('candidat', 'text', 'text', 'YES', 'NEVER'),
            ('visibility', 'text', 'text', 'YES', 'NEVER'),
            ('school_year', 'text', 'text', 'YES', 'NEVER'),
            ('programme_version', 'text', 'text', 'YES', 'NEVER')
        ) AS expected(column_name, data_type, udt_name, is_nullable, is_generated)
        LEFT JOIN information_schema.columns AS actual
          ON actual.table_schema = 'public'
         AND actual.table_name = 'rag_chunks'
         AND actual.column_name = expected.column_name
        WHERE actual.column_name IS NULL
           OR actual.data_type IS DISTINCT FROM expected.data_type
           OR actual.udt_name IS DISTINCT FROM expected.udt_name
           OR actual.is_nullable IS DISTINCT FROM expected.is_nullable
           OR actual.is_generated IS DISTINCT FROM expected.is_generated
    )
    AND (SELECT count(*) = 5
         FROM pg_constraint
         WHERE conrelid = 'public.rag_chunks'::regclass
           AND convalidated
           AND (conname, md5(pg_get_constraintdef(oid, true))) IN (
               ('rag_chunks_candidat_lot41_check',
                :'candidat_constraint_md5'),
               ('rag_chunks_programme_version_lot41_check',
                :'programme_constraint_md5'),
               ('rag_chunks_school_year_lot41_check',
                :'school_year_constraint_md5'),
               ('rag_chunks_tenant_lot41_check',
                :'tenant_constraint_md5'),
               ('rag_chunks_visibility_lot41_check',
                :'visibility_constraint_md5')
           ))
    AND (SELECT count(*) = 10
         FROM pg_index AS index_definition
         JOIN pg_class AS index_relation
           ON index_relation.oid = index_definition.indexrelid
         WHERE index_definition.indrelid = 'public.rag_chunks'::regclass
           AND index_definition.indisvalid
           AND index_definition.indisready
           AND (index_relation.relname,
                md5(pg_get_indexdef(index_definition.indexrelid))) IN (
               ('idx_rag_chunks_audience', :'audience_index_md5'),
               ('idx_rag_chunks_collection', :'collection_index_md5'),
               ('idx_rag_chunks_matiere', :'matiere_index_md5'),
               ('idx_rag_chunks_niveau', :'niveau_index_md5'),
               ('idx_rag_chunks_profile_reviewed', :'profile_index_md5'),
               ('idx_rag_chunks_review', :'review_index_md5'),
               ('idx_rag_chunks_rights', :'rights_index_md5'),
               ('idx_rag_chunks_text_tsv', :'text_tsv_index_md5'),
               ('idx_rag_chunks_vector', :'vector_index_md5'),
               ('rag_chunks_pkey', :'rag_chunks_primary_index_md5')
           ))
    AND (SELECT md5(pg_get_expr(indpred, indrelid, true)) =
                    :'profile_predicate_md5'
         FROM pg_index
         WHERE indexrelid =
             to_regclass('public.idx_rag_chunks_profile_reviewed'))
    AND (SELECT md5(pg_get_expr(definition.adbin, definition.adrelid, true)) =
                    :'text_tsv_expression_md5'
         FROM pg_attrdef AS definition
         JOIN pg_attribute AS generated_column
           ON generated_column.attrelid = definition.adrelid
          AND generated_column.attnum = definition.adnum
         WHERE definition.adrelid = 'public.rag_chunks'::regclass
           AND generated_column.attname = 'text_tsv'
           AND generated_column.attgenerated = 's')
    AND (SELECT count(*) = 3 FROM rag_schema_migrations)
    AND EXISTS (
        SELECT 1 FROM rag_schema_migrations
        WHERE version = 1
          AND file_name = '001_rag_chunks_v2_schema.sql'
          AND sha256 = :'migration_001_sha'
    )
    AND EXISTS (
        SELECT 1 FROM rag_schema_migrations
        WHERE version = 2
          AND file_name = '002_hybrid_retrieval.sql'
          AND sha256 = :'migration_002_sha'
    )
    AND EXISTS (
        SELECT 1 FROM rag_schema_migrations
        WHERE version = 3
          AND file_name = '003_profile_filtering.sql'
          AND sha256 = :'migration_003_sha'
    );
SQL
