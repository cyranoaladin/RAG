-- Migration 001: rag_chunks v1 → v2 schema (idempotent)
--
-- Behavior:
--   1. Ensure vector extension exists.
--   2. If rag_chunks does NOT exist → create v2 schema.
--   3. If rag_chunks exists WITH chunk_id (already v2) → ensure indexes only.
--   4. If rag_chunks exists WITHOUT chunk_id (legacy v1):
--      a. If COUNT(*) > 0 → RAISE EXCEPTION (refuse destructive migration).
--      b. If COUNT(*) = 0 → rename to rag_chunks_legacy_pre_v2_001, create v2.
--
-- Safe to re-run: all operations are IF NOT EXISTS or guarded.

CREATE EXTENSION IF NOT EXISTS vector;

DO $$
DECLARE
    has_chunk_id BOOLEAN;
    row_count BIGINT;
BEGIN
    -- Check if rag_chunks exists at all
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = 'rag_chunks'
    ) THEN
        RAISE NOTICE 'rag_chunks does not exist, will create v2 schema';
    ELSE
        -- Check if it's already v2 (has chunk_id column)
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'rag_chunks'
              AND column_name = 'chunk_id'
        ) INTO has_chunk_id;

        IF has_chunk_id THEN
            RAISE NOTICE 'rag_chunks already has v2 schema (chunk_id present), skipping table creation';
            RETURN;
        END IF;

        -- Legacy schema detected (no chunk_id). Check for data.
        EXECUTE 'SELECT COUNT(*) FROM rag_chunks' INTO row_count;

        IF row_count > 0 THEN
            RAISE EXCEPTION 'MIGRATION BLOCKED: rag_chunks has legacy schema with % rows. Manual migration required.', row_count;
        END IF;

        -- Empty legacy table: free the primary-key constraint/index before rename
        -- to avoid rag_chunks_pkey collision when creating the new table.
        IF EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'rag_chunks_pkey' AND conrelid = 'rag_chunks'::regclass
        ) THEN
            RAISE NOTICE 'Renaming legacy constraint rag_chunks_pkey';
            ALTER INDEX rag_chunks_pkey RENAME TO rag_chunks_legacy_pre_v2_001_pkey;
        END IF;

        RAISE NOTICE 'Renaming empty legacy rag_chunks to rag_chunks_legacy_pre_v2_001';
        ALTER TABLE rag_chunks RENAME TO rag_chunks_legacy_pre_v2_001;
    END IF;
END
$$;

-- Create v2 rag_chunks (only runs if table was absent or renamed above)
CREATE TABLE IF NOT EXISTS rag_chunks (
    chunk_id            TEXT PRIMARY KEY,
    doc_id              TEXT NOT NULL,
    chunk_sha256        TEXT NOT NULL,
    vector              vector(1024),
    collection          TEXT NOT NULL,
    niveau              TEXT NOT NULL,
    voie                TEXT NOT NULL DEFAULT 'generale',
    audience            TEXT[] NOT NULL DEFAULT '{"tous"}',
    matiere             TEXT NOT NULL,
    statut_enseignement TEXT NOT NULL DEFAULT 'unknown',
    notions             TEXT[] NOT NULL DEFAULT '{}',
    domain              TEXT NOT NULL DEFAULT 'education',
    source_label        TEXT NOT NULL,
    source_uri          TEXT NOT NULL,
    rights              TEXT NOT NULL,
    type_doc            TEXT NOT NULL,
    official            BOOLEAN NOT NULL DEFAULT false,
    text                TEXT,
    chunk_index         INTEGER NOT NULL DEFAULT 0,
    page_start          INTEGER,
    page_end            INTEGER,
    review_status       TEXT NOT NULL DEFAULT 'needs_review',
    model               TEXT,
    source_kind         TEXT NOT NULL DEFAULT 'unknown',
    indexed_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes (idempotent)
CREATE INDEX IF NOT EXISTS idx_rag_chunks_vector
    ON rag_chunks USING hnsw (vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

CREATE INDEX IF NOT EXISTS idx_rag_chunks_collection ON rag_chunks (collection);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_niveau ON rag_chunks (niveau);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_matiere ON rag_chunks (matiere);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_audience ON rag_chunks USING gin (audience);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_rights ON rag_chunks (rights);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_review ON rag_chunks (review_status);
