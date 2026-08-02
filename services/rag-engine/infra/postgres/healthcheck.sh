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
    --tuples-only \
    --no-align <<'SQL' | grep -qx t
SELECT
    (SELECT count(*) = 5
     FROM information_schema.columns
     WHERE table_schema = 'public'
       AND table_name = 'rag_chunks'
       AND column_name IN (
           'tenant', 'candidat', 'visibility', 'school_year', 'programme_version'
       )
       AND data_type = 'text'
       AND is_nullable = 'YES'
       AND column_default IS NULL)
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
    AND (SELECT md5(pg_get_indexdef(indexrelid)) =
                    :'profile_index_md5'
                AND md5(pg_get_expr(indpred, indrelid, true)) =
                    :'profile_predicate_md5'
                AND indisvalid
                AND indisready
         FROM pg_index
         WHERE indexrelid =
             to_regclass('public.idx_rag_chunks_profile_reviewed'))
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
