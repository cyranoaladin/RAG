-- Rollback de la migration 005 : restaure la contrainte jobs_status_valid
-- à 7 valeurs (avec 'claimed') telle qu'elle existait après 004_jobs.sql.
-- Sûr sans condition de données : réintroduire une valeur autorisée
-- supplémentaire dans un CHECK ne peut jamais violer de ligne existante.

ALTER TABLE ingestion_control.jobs
    DROP CONSTRAINT IF EXISTS jobs_status_valid;

ALTER TABLE ingestion_control.jobs
    ADD CONSTRAINT jobs_status_valid
        CHECK (status IN (
            'queued', 'claimed', 'running', 'succeeded', 'failed',
            'dead_letter', 'cancelled'
        ));
