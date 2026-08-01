DROP INDEX IF EXISTS idx_rag_chunks_text_tsv;

ALTER TABLE rag_chunks
    DROP COLUMN IF EXISTS text_tsv;
