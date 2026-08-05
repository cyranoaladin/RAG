DO $nexus$
BEGIN
    IF EXISTS (SELECT 1 FROM ingestion_control.workflow_events) THEN
        RAISE EXCEPTION 'ROLLBACK_003_DATA_PRESENT';
    END IF;
END
$nexus$;

DROP TABLE ingestion_control.workflow_events;
