DO $nexus$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM rag_chunks
        WHERE tenant IS NOT NULL
           OR school_year IS NOT NULL
           OR candidat IS NOT NULL
           OR visibility IS NOT NULL
           OR programme_version IS NOT NULL
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_003_DATA_PRESENT';
    END IF;
END
$nexus$;

DROP INDEX idx_rag_chunks_profile_reviewed;

ALTER TABLE rag_chunks
    DROP CONSTRAINT rag_chunks_tenant_lot41_check,
    DROP CONSTRAINT rag_chunks_candidat_lot41_check,
    DROP CONSTRAINT rag_chunks_visibility_lot41_check,
    DROP CONSTRAINT rag_chunks_school_year_lot41_check,
    DROP CONSTRAINT rag_chunks_programme_version_lot41_check,
    DROP COLUMN tenant,
    DROP COLUMN candidat,
    DROP COLUMN visibility,
    DROP COLUMN school_year,
    DROP COLUMN programme_version;
