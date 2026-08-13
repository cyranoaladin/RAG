-- Migration 004 : identité produit liée au contenu et placements 1:N.
--
-- Strictement additive : aucune ligne historique de rag_chunks n'est
-- réécrite et aucun vecteur n'est recalculé. Les chunks historiques gardent
-- artifact_id=NULL et continuent d'utiliser leur scope scalarisé.

CREATE TABLE public.rag_artifacts (
    artifact_id                    TEXT PRIMARY KEY,
    content_sha256                 TEXT NOT NULL UNIQUE,
    source_label                   TEXT NOT NULL,
    source_uri                     TEXT NOT NULL,
    rights                         TEXT NOT NULL,
    official                       BOOLEAN NOT NULL DEFAULT false,
    source_kind                    TEXT NOT NULL,
    type_doc                       TEXT NOT NULL,
    ingestion_artifact_id          UUID NOT NULL,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT rag_artifacts_identity_is_content_sha256_check
        CHECK (artifact_id = content_sha256),
    CONSTRAINT rag_artifacts_artifact_id_sha256_check
        CHECK (artifact_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT rag_artifacts_source_label_nonblank_check
        CHECK (btrim(source_label) <> ''),
    CONSTRAINT rag_artifacts_source_uri_nonblank_check
        CHECK (btrim(source_uri) <> ''),
    CONSTRAINT rag_artifacts_rights_nonblank_check
        CHECK (btrim(rights) <> ''),
    CONSTRAINT rag_artifacts_source_kind_nonblank_check
        CHECK (btrim(source_kind) <> ''),
    CONSTRAINT rag_artifacts_type_doc_nonblank_check
        CHECK (btrim(type_doc) <> '')
);

CREATE TABLE public.rag_artifact_placements (
    placement_id                   TEXT PRIMARY KEY,
    artifact_id                    TEXT NOT NULL
        REFERENCES public.rag_artifacts (artifact_id) ON DELETE RESTRICT,
    collection                     TEXT NOT NULL,
    tenant                         TEXT NOT NULL,
    niveau                         TEXT NOT NULL,
    voie                           TEXT NOT NULL,
    audience                       TEXT[] NOT NULL,
    matiere                        TEXT NOT NULL,
    statut_enseignement            TEXT NOT NULL,
    candidat                       TEXT NOT NULL,
    visibility                     TEXT NOT NULL,
    school_year                    TEXT NOT NULL,
    programme_version              TEXT NOT NULL,
    currentness                    TEXT NOT NULL,
    placement_status               TEXT NOT NULL,
    review_status                  TEXT NOT NULL,
    source_scope                   TEXT NOT NULL,
    source_placement_id            TEXT NOT NULL,
    source_path                    TEXT NOT NULL,
    source_uri                     TEXT NOT NULL,
    authorization_id               TEXT NOT NULL,
    publication_attestation_id     UUID NOT NULL,
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT rag_artifact_placements_id_sha256_check
        CHECK (placement_id ~ '^[0-9a-f]{64}$'),
    CONSTRAINT rag_artifact_placements_nonblank_check
        CHECK (
            btrim(collection) <> ''
            AND btrim(tenant) <> ''
            AND btrim(niveau) <> ''
            AND btrim(voie) <> ''
            AND cardinality(audience) > 0
            AND btrim(matiere) <> ''
            AND btrim(statut_enseignement) <> ''
            AND btrim(candidat) <> ''
            AND btrim(visibility) <> ''
            AND btrim(programme_version) <> ''
            AND btrim(source_scope) <> ''
            AND btrim(source_placement_id) <> ''
            AND btrim(source_path) <> ''
            AND btrim(source_uri) <> ''
            AND btrim(authorization_id) <> ''
        ),
    CONSTRAINT rag_artifact_placements_audience_no_blank_check
        CHECK (array_position(audience, '') IS NULL),
    CONSTRAINT rag_artifact_placements_school_year_check
        CHECK (
            school_year ~ '^[0-9]{4}-[0-9]{4}$'
            AND split_part(school_year, '-', 2)::integer
                = split_part(school_year, '-', 1)::integer + 1
        ),
    CONSTRAINT rag_artifact_placements_candidat_check
        CHECK (candidat IN (
            'scolarise', 'individuel', 'libre', 'cned_reglemente',
            'cned_libre', 'aefe', 'both'
        )),
    CONSTRAINT rag_artifact_placements_visibility_check
        CHECK (visibility IN ('public', 'internal', 'restricted', 'private')),
    CONSTRAINT rag_artifact_placements_currentness_check
        CHECK (currentness IN ('current', 'archive', 'review_required')),
    CONSTRAINT rag_artifact_placements_status_check
        CHECK (placement_status IN ('active', 'disabled')),
    CONSTRAINT rag_artifact_placements_review_status_check
        CHECK (review_status IN ('needs_review', 'reviewed')),
    CONSTRAINT rag_artifact_placements_canonical_scope_unique
        UNIQUE (
            artifact_id, collection, tenant, niveau, voie, audience, matiere,
            statut_enseignement, candidat, visibility, school_year,
            programme_version
        ),
    CONSTRAINT rag_artifact_placements_source_unique
        UNIQUE (artifact_id, source_placement_id, collection)
);

ALTER TABLE public.rag_chunks
    ADD COLUMN artifact_id TEXT,
    ADD CONSTRAINT rag_chunks_artifact_id_fkey
        FOREIGN KEY (artifact_id)
        REFERENCES public.rag_artifacts (artifact_id)
        ON DELETE RESTRICT,
    ADD CONSTRAINT rag_chunks_governed_identity_check
        CHECK (artifact_id IS NULL OR doc_id = artifact_id) NOT VALID;

ALTER TABLE public.rag_chunks
    VALIDATE CONSTRAINT rag_chunks_governed_identity_check;

CREATE UNIQUE INDEX idx_rag_chunks_artifact_chunk_index_unique
    ON public.rag_chunks (artifact_id, chunk_index)
    WHERE artifact_id IS NOT NULL;

CREATE INDEX idx_rag_chunks_artifact_id
    ON public.rag_chunks (artifact_id)
    WHERE artifact_id IS NOT NULL;

CREATE INDEX idx_rag_artifact_placements_scope_active
    ON public.rag_artifact_placements (
        collection, tenant, niveau, voie, matiere, statut_enseignement,
        candidat, school_year, programme_version, artifact_id
    )
    WHERE placement_status = 'active'
      AND currentness = 'current'
      AND review_status = 'reviewed';

CREATE INDEX idx_rag_artifact_placements_audience
    ON public.rag_artifact_placements USING gin (audience);

CREATE INDEX idx_rag_artifact_placements_artifact_id
    ON public.rag_artifact_placements (artifact_id);
