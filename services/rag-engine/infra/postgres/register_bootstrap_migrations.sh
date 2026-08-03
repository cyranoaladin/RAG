#!/usr/bin/env bash
# Enregistrer le head canonique après le bootstrap Docker d'un volume neuf.
set -euo pipefail

migration_root=/docker-entrypoint-migrations
migration_001_file=001_rag_chunks_v2_schema.sql
migration_002_file=002_hybrid_retrieval.sql
migration_003_file=003_profile_filtering.sql

for migration_file in \
    "$migration_001_file" \
    "$migration_002_file" \
    "$migration_003_file"; do
    test -f "$migration_root/$migration_file"
done

migration_001_sha="$(sha256sum "$migration_root/$migration_001_file" | cut -d' ' -f1)"
migration_002_sha="$(sha256sum "$migration_root/$migration_002_file" | cut -d' ' -f1)"
migration_003_sha="$(sha256sum "$migration_root/$migration_003_file" | cut -d' ' -f1)"

psql \
    --username "$POSTGRES_USER" \
    --dbname "${POSTGRES_DB:-$POSTGRES_USER}" \
    --set ON_ERROR_STOP=1 \
    --set "migration_001_file=$migration_001_file" \
    --set "migration_001_sha=$migration_001_sha" \
    --set "migration_002_file=$migration_002_file" \
    --set "migration_002_sha=$migration_002_sha" \
    --set "migration_003_file=$migration_003_file" \
    --set "migration_003_sha=$migration_003_sha" <<'SQL'
BEGIN;

CREATE TABLE rag_schema_migrations (
    version integer PRIMARY KEY CHECK (version > 0),
    file_name text NOT NULL UNIQUE CHECK (btrim(file_name) <> ''),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO rag_schema_migrations (version, file_name, sha256)
VALUES
    (1, :'migration_001_file', :'migration_001_sha'),
    (2, :'migration_002_file', :'migration_002_sha'),
    (3, :'migration_003_file', :'migration_003_sha');

COMMIT;
SQL
