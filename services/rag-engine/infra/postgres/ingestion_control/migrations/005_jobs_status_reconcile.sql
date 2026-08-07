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
--
-- Remédiation revue PR#90 (Cubic P1, deux passes) : sur une base déjà
-- peuplée où une ligne porterait malgré tout status='claimed'
-- (intervention manuelle, ancienne version du code, corrigée avant même
-- que jobs_status_valid ne l'autorise formellement), la version initiale
-- de ce backfill transformait *toute* ligne 'claimed' en 'running' sans
-- condition — y compris une ligne dont le bail était déjà expiré ou
-- absent, la rendant alors "running" mais **jamais plus réclamable** par
-- aucun worker (claim_job ne sélectionne que 'queued'), une tentative
-- d'ingestion perdue silencieusement.
--
-- Politique déterministe désormais appliquée, en deux étapes disjointes :
--   1. 'claimed' avec un bail actif (lease_token non nul ET
--      lease_expires_at réellement dans le futur) -> 'running' : c'est
--      sémantiquement un job en cours de traitement légitime, l'attente
--      du reaper suffira si le worker qui le détient meurt.
--   2. 'claimed' restant (bail absent ou déjà expiré) -> 'queued', avec
--      claimed_by/lease_token/lease_expires_at explicitement nettoyés :
--      aucun worker n'en a la charge réelle, il doit redevenir
--      immédiatement réclamable plutôt que rester bloqué dans un état
--      qui n'existera plus après cette migration.
UPDATE ingestion_control.jobs
SET status = 'running'
WHERE status = 'claimed' AND lease_token IS NOT NULL AND lease_expires_at > now();

UPDATE ingestion_control.jobs
SET status = 'queued', claimed_by = NULL, lease_token = NULL, lease_expires_at = NULL
WHERE status = 'claimed';

ALTER TABLE ingestion_control.jobs
    DROP CONSTRAINT IF EXISTS jobs_status_valid;

ALTER TABLE ingestion_control.jobs
    ADD CONSTRAINT jobs_status_valid
        CHECK (status IN (
            'queued', 'running', 'succeeded', 'failed',
            'dead_letter', 'cancelled'
        ));
