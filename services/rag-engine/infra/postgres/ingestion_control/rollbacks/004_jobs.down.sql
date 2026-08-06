-- Rollback de la migration 004 : retire la FK workflow_events.job_id puis
-- la table jobs. Sûr sans donnée : la FK ajoutée par 004 n'a jamais pu
-- être violée (toutes les lignes workflow_events antérieures ont job_id
-- NULL par construction LOT44b/44c/44d), donc son retrait ne dépend
-- d'aucune donnée existante — seule la table jobs elle-même est gardée.

-- Remédiation revue PR#90 (Cubic P1) : même motif que 001/002/003 —
-- LOCK TABLE avant vérification, dans la même transaction que le DROP.
LOCK TABLE ingestion_control.jobs IN ACCESS EXCLUSIVE MODE;

DO $nexus$
BEGIN
    IF EXISTS (SELECT 1 FROM ingestion_control.jobs) THEN
        RAISE EXCEPTION 'ROLLBACK_004_DATA_PRESENT';
    END IF;
END
$nexus$;

ALTER TABLE ingestion_control.workflow_events
    DROP CONSTRAINT IF EXISTS workflow_events_job_id_fkey;

DROP TABLE ingestion_control.jobs;
