-- Remédiation revue PR#90 (Cubic P1) : voir 001_ingestion_control_schema.
-- down.sql pour la justification complète du LOCK TABLE avant vérification.
LOCK TABLE ingestion_control.workflow_events IN ACCESS EXCLUSIVE MODE;

DO $nexus$
BEGIN
    IF EXISTS (SELECT 1 FROM ingestion_control.workflow_events) THEN
        RAISE EXCEPTION 'ROLLBACK_003_DATA_PRESENT';
    END IF;
END
$nexus$;

DROP TABLE ingestion_control.workflow_events;
