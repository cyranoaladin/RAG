-- ADR-0013: table cible rag_chunks (pas rag_chunks_pilote)
-- Alignée sur nexus-contracts ChunkMetadata + Citation (F-01)
-- Instance pgvector dédiée au RAG (séparée de nexus_prod, A-1)

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_chunks (
    -- Identifiants
    chunk_id        TEXT PRIMARY KEY,
    doc_id          TEXT NOT NULL,
    chunk_sha256    TEXT NOT NULL,

    -- Vecteur (e5-large 1024 dim, ADR-0013)
    vector          vector(1024),

    -- Classification pédagogique (contrat ChunkMetadata)
    collection      TEXT NOT NULL,           -- rag_nexus_{matiere}_{niveau}_{statut}
    niveau          TEXT NOT NULL,            -- enum Niveau
    voie            TEXT NOT NULL DEFAULT 'generale',  -- enum Voie
    audience        TEXT[] NOT NULL DEFAULT '{"tous"}',
    matiere         TEXT NOT NULL,
    statut_enseignement TEXT NOT NULL DEFAULT 'unknown',  -- enum StatutEnseignement
    notions         TEXT[] NOT NULL DEFAULT '{}',
    domain          TEXT NOT NULL DEFAULT 'education',

    -- Citations (F-01 — champs rendant la citation possible)
    source_label    TEXT NOT NULL,            -- label humain de la source
    source_uri      TEXT NOT NULL,            -- URI de la source (URL GDrive, etc.)
    rights          TEXT NOT NULL,            -- enum Rights (par provenance, A-4)
    type_doc        TEXT NOT NULL,            -- enum TypeDoc
    official        BOOLEAN NOT NULL DEFAULT false,

    -- Contenu
    text            TEXT,                     -- texte complet du chunk
    chunk_index     INTEGER NOT NULL DEFAULT 0,
    page_start      INTEGER,
    page_end        INTEGER,

    -- Gouvernance
    review_status   TEXT NOT NULL DEFAULT 'needs_review',
    model           TEXT,                     -- modèle d'embedding utilisé
    source_kind     TEXT NOT NULL DEFAULT 'unknown',

    -- Horodatage
    indexed_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index HNSW pour la recherche vectorielle (cosine)
CREATE INDEX IF NOT EXISTS idx_rag_chunks_vector
    ON rag_chunks USING hnsw (vector vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Index B-tree sur les colonnes de filtre (F-15 : recall sous filtre)
CREATE INDEX IF NOT EXISTS idx_rag_chunks_collection ON rag_chunks (collection);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_niveau ON rag_chunks (niveau);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_matiere ON rag_chunks (matiere);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_audience ON rag_chunks USING gin (audience);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_rights ON rag_chunks (rights);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_review ON rag_chunks (review_status);

-- Mapping champ → contrat nexus-contracts :
-- chunk_id       → ChunkMetadata (pas doc_id)
-- doc_id         → ChunkMetadata.doc_id (distinct de chunk_id)
-- source_label   → Citation.source_label
-- source_uri     → Citation.source_uri
-- rights         → Citation.rights
-- type_doc       → ChunkMetadata.type_doc
-- official       → ChunkMetadata.official
-- chunk_sha256   → intégrité/dédup
