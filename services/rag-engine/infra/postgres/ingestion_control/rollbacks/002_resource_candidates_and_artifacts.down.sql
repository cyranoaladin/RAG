DO $nexus$
BEGIN
    IF EXISTS (SELECT 1 FROM ingestion_control.resource_candidates)
       OR EXISTS (SELECT 1 FROM ingestion_control.artifacts) THEN
        RAISE EXCEPTION 'ROLLBACK_002_DATA_PRESENT';
    END IF;
END
$nexus$;

DROP TABLE ingestion_control.artifacts;
DROP TABLE ingestion_control.resource_candidates;
