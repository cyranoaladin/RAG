ALTER TABLE rag_chunks
    ADD COLUMN IF NOT EXISTS text_tsv tsvector
    GENERATED ALWAYS AS (to_tsvector('french', coalesce(text, ''))) STORED;

CREATE INDEX IF NOT EXISTS idx_rag_chunks_text_tsv
    ON rag_chunks USING gin (text_tsv);
