-- ═══════════════════════════════════════════════════════════
-- RAG Service v2 — Initialisation PostgreSQL + pgvector
-- ═══════════════════════════════════════════════════════════
-- Aligné sur nexus-contracts ChunkMetadata + Citation (F-01, ADR-0013)

-- Activation des extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE EXTENSION IF NOT EXISTS btree_gin;

-- ═══════════════════════════
-- TABLE PRINCIPALE v2
-- ═══════════════════════════

CREATE TABLE IF NOT EXISTS rag_chunks (
    -- Identifiants
    chunk_id        TEXT PRIMARY KEY,
    doc_id          TEXT NOT NULL,
    chunk_sha256    TEXT NOT NULL,

    -- Vecteur (e5-large 1024 dim, ADR-0013)
    vector          vector(1024),

    -- Classification pédagogique (contrat ChunkMetadata)
    collection      TEXT NOT NULL,
    niveau          TEXT NOT NULL,
    voie            TEXT NOT NULL DEFAULT 'generale',
    audience        TEXT[] NOT NULL DEFAULT '{"tous"}',
    matiere         TEXT NOT NULL,
    statut_enseignement TEXT NOT NULL DEFAULT 'unknown',
    notions         TEXT[] NOT NULL DEFAULT '{}',
    domain          TEXT NOT NULL DEFAULT 'education',

    -- Citations (F-01)
    source_label    TEXT NOT NULL,
    source_uri      TEXT NOT NULL,
    rights          TEXT NOT NULL,
    type_doc        TEXT NOT NULL,
    official        BOOLEAN NOT NULL DEFAULT false,

    -- Contenu
    text            TEXT,
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    page_start      INTEGER,
    page_end        INTEGER,

    -- Gouvernance
    review_status   TEXT NOT NULL DEFAULT 'needs_review',
    model           TEXT,
    source_kind     TEXT NOT NULL DEFAULT 'unknown',

    -- Horodatage
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ═══════════════════════════
-- INDEX v2
-- ═══════════════════════════

-- HNSW pour la recherche vectorielle (cosine)
CREATE INDEX IF NOT EXISTS idx_rag_chunks_vector
    ON rag_chunks USING hnsw (vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Index sur les colonnes de filtre
CREATE INDEX IF NOT EXISTS idx_rag_chunks_collection ON rag_chunks (collection);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_niveau ON rag_chunks (niveau);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_matiere ON rag_chunks (matiere);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_audience ON rag_chunks USING gin (audience);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_rights ON rag_chunks (rights);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_review ON rag_chunks (review_status);

-- ═══════════════════════════
-- TABLES AUXILIAIRES
-- ═══════════════════════════

-- API keys (sécurité)
CREATE TABLE IF NOT EXISTS rag_api_keys (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant VARCHAR(64) NOT NULL,
    key_hash VARCHAR(128) NOT NULL UNIQUE,
    label VARCHAR(128),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT true
);

-- Métriques qualité RAG (évaluation)
CREATE TABLE IF NOT EXISTS rag_eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant VARCHAR(64) NOT NULL,
    run_at TIMESTAMPTZ DEFAULT NOW(),
    embed_model VARCHAR(128),
    precision_at_5 FLOAT,
    recall_at_5 FLOAT,
    mrr FLOAT,
    ndcg FLOAT,
    avg_latency_ms FLOAT,
    gold_set_version VARCHAR(32),
    metadata JSONB DEFAULT '{}'
);
