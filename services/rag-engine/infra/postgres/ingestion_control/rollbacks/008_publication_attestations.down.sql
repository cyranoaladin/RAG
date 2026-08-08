-- Rollback de la migration 008 : retire ingestion_control.publication_attestations.
-- Sûr uniquement si aucune ligne n'existe — même discipline que 001-007.

LOCK TABLE ingestion_control.publication_attestations IN ACCESS EXCLUSIVE MODE;

DO $nexus$
BEGIN
    IF EXISTS (SELECT 1 FROM ingestion_control.publication_attestations) THEN
        RAISE EXCEPTION 'ROLLBACK_008_DATA_PRESENT';
    END IF;
END
$nexus$;

DROP TABLE ingestion_control.publication_attestations;
