-- Migration 005 : réconciliation de jobs_status_valid avec JobStatus (LOT44f).
--
-- Dette constatée par l'audit go-live (docs/reports/rag_project_global_state_2026-08-04.md,
-- section 16.3) : jobs_status_valid (004_jobs.sql) autorisait 7 valeurs
-- ('queued', 'claimed', 'running', 'succeeded', 'failed', 'dead_letter',
-- 'cancelled') alors que le type Python JobStatus (ingestion_control/jobs.py)
-- n'en déclare que 6 (sans 'claimed'), et que le code n'écrit jamais
-- 'claimed' : claim_job() fait transitionner directement 'queued' -> 'running'
-- (jobs.py:141-150) ; l'information "réclamé" est déjà portée entièrement par
-- lease_token/lease_expires_at, pas par un état 'claimed' distinct. 'claimed'
-- est donc supprimé ici plutôt qu'ajouté côté Python (option retenue parmi
-- les trois proposées par la mission go-live : "supprimer l'état SQL
-- inutile" — ajouter un état 'claimed' réellement traversé aurait exigé une
-- transition supplémentaire jamais émise par aucun appelant actuel, pure
-- sur-ingénierie).
--
-- 'failed' reste déclaré des deux côtés (SQL et Python) bien qu'aucun
-- appelant actuel ne l'écrive : ce n'est pas une divergence inter-couches
-- (les deux couches sont d'accord), seulement un état terminal réservé pour
-- une classification d'échec non-retryable future — hors périmètre de cette
-- migration (cf. ADR-0029).
--
-- Additive au sens migrations : ne réécrit pas 004 (gelée), ALTER seulement.
-- Idempotent : DROP CONSTRAINT IF EXISTS puis ADD CONSTRAINT, sûr à rejouer.

ALTER TABLE ingestion_control.jobs
    DROP CONSTRAINT IF EXISTS jobs_status_valid;

ALTER TABLE ingestion_control.jobs
    ADD CONSTRAINT jobs_status_valid
        CHECK (status IN (
            'queued', 'running', 'succeeded', 'failed',
            'dead_letter', 'cancelled'
        ));
