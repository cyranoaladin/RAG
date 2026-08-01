ALTER TABLE rag_chunks
    ADD COLUMN tenant TEXT,
    ADD COLUMN candidat TEXT,
    ADD COLUMN visibility TEXT,
    ADD COLUMN school_year TEXT,
    ADD COLUMN programme_version TEXT;

ALTER TABLE rag_chunks
    ADD CONSTRAINT rag_chunks_tenant_lot41_check
        CHECK (tenant IS NULL OR btrim(tenant) <> '') NOT VALID,
    ADD CONSTRAINT rag_chunks_candidat_lot41_check
        CHECK (candidat IS NULL OR candidat IN (
            'scolarise', 'individuel', 'libre', 'cned_reglemente',
            'cned_libre', 'aefe', 'both'
        )) NOT VALID,
    ADD CONSTRAINT rag_chunks_visibility_lot41_check
        CHECK (
            visibility IS NULL
            OR visibility IN ('public', 'internal', 'restricted', 'private')
        ) NOT VALID,
    ADD CONSTRAINT rag_chunks_school_year_lot41_check
        CHECK (
            CASE
                WHEN school_year IS NULL THEN true
                WHEN school_year ~ '^[0-9]{4}-[0-9]{4}$' THEN
                    split_part(school_year, '-', 2)::integer
                        = split_part(school_year, '-', 1)::integer + 1
                ELSE false
            END
        ) NOT VALID,
    ADD CONSTRAINT rag_chunks_programme_version_lot41_check
        CHECK (programme_version IS NULL OR btrim(programme_version) <> '') NOT VALID;

ALTER TABLE rag_chunks VALIDATE CONSTRAINT rag_chunks_tenant_lot41_check;
ALTER TABLE rag_chunks VALIDATE CONSTRAINT rag_chunks_candidat_lot41_check;
ALTER TABLE rag_chunks VALIDATE CONSTRAINT rag_chunks_visibility_lot41_check;
ALTER TABLE rag_chunks VALIDATE CONSTRAINT rag_chunks_school_year_lot41_check;
ALTER TABLE rag_chunks VALIDATE CONSTRAINT rag_chunks_programme_version_lot41_check;

CREATE INDEX idx_rag_chunks_profile_reviewed
    ON rag_chunks (
        collection,
        tenant,
        niveau,
        voie,
        matiere,
        statut_enseignement,
        candidat,
        school_year,
        programme_version,
        rights,
        visibility
    )
    WHERE review_status = 'reviewed';
