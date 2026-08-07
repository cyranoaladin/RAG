-- Migration 004 : table jobs, et fermeture de la dette FK sur
-- workflow_events.job_id (LOT44e).
--
-- Dette héritée de LOT44b/ADR-0027, reformulée par ADR-0028 : "job_id sans
-- table jobs ni contrainte FK — aucune intégrité référentielle sur
-- l'identifiant de tentative d'exécution métier". Condition d'acceptation
-- documentée : "Table ingestion_control.jobs (ou équivalent) + FK réelle
-- depuis workflow_events.job_id, avec un ADR dédié" — fermée ici par une
-- migration additive, jamais en réécrivant 001/002/003 (gelées).
--
-- job_id reste un identifiant libre de tentative d'exécution métier,
-- distinct de resources.lease_token (bail de concurrence, LOT44b) — cette
-- distinction, déjà actée par 003_workflow_events.sql, n'est pas remise en
-- cause : un job peut réclamer/relâcher plusieurs baux de ressources au
-- cours de son exécution, ce sont deux concepts orthogonaux.
--
-- job_type n'est volontairement pas contraint par une liste CHECK : aucun
-- contrat "IngestionJob" canonique n'existe dans nexus_contracts (LOT44a),
-- et en créer un serait une évolution de contrat hors périmètre de ce lot
-- (AGENTS.md : toute évolution de packages/contracts passe par un ADR
-- dédié). Seule la non-vacuité est vérifiée ici ; la validation de valeurs
-- précises reste une responsabilité applicative Python (LOT44e).
--
-- resource_id reste nullable : un job peut exister avant qu'aucune
-- ressource ne soit découverte (ex. job de planification/recherche,
-- Planner) — jamais forcé à NOT NULL, par le même raisonnement que
-- workflow_events.resource_id (003).
--
-- Idempotent : IF NOT EXISTS partout, sûr à rejouer.

CREATE TABLE IF NOT EXISTS ingestion_control.jobs (
    job_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL
        REFERENCES ingestion_control.ingestion_runs (run_id),
    resource_id         UUID
        REFERENCES ingestion_control.resources (resource_id),

    job_type            TEXT NOT NULL,
    status               TEXT NOT NULL DEFAULT 'queued',

    -- Claim / lease — même primitive de concurrence que resources (LOT44b),
    -- dupliquée ici plutôt que partagée : jobs et resources sont deux files
    -- réclamables indépendantes, jamais le même verrou.
    claimed_by           TEXT,
    lease_token          UUID,
    lease_expires_at     TIMESTAMPTZ,

    -- Retry / backoff — mêmes colonnes que resources (LOT44b), même
    -- sémantique, file indépendante.
    attempt_count        INTEGER NOT NULL DEFAULT 0,
    max_attempts         INTEGER NOT NULL DEFAULT 3,
    next_attempt_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error           TEXT,

    -- Entrée libre du job (ex. pour un job créé depuis /ingest/v2 :
    -- source_type/source_path/tenant/options) — jamais interprétée par le
    -- schéma lui-même, uniquement par la couche Python appelante.
    payload              JSONB NOT NULL DEFAULT '{}'::jsonb,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT jobs_job_type_not_blank
        CHECK (btrim(job_type) <> ''),
    CONSTRAINT jobs_status_valid
        CHECK (status IN (
            'queued', 'claimed', 'running', 'succeeded', 'failed',
            'dead_letter', 'cancelled'
        )),
    CONSTRAINT jobs_attempt_count_non_negative
        CHECK (attempt_count >= 0),
    CONSTRAINT jobs_max_attempts_positive
        CHECK (max_attempts > 0),
    CONSTRAINT jobs_lease_token_requires_expiry
        CHECK ((lease_token IS NULL) = (lease_expires_at IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_ingestion_control_jobs_run_id
    ON ingestion_control.jobs (run_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_control_jobs_resource_id
    ON ingestion_control.jobs (resource_id)
    WHERE resource_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_ingestion_control_jobs_claimable
    ON ingestion_control.jobs (status, next_attempt_at)
    WHERE lease_token IS NULL;

CREATE INDEX IF NOT EXISTS idx_ingestion_control_jobs_lease_expiry
    ON ingestion_control.jobs (lease_expires_at)
    WHERE lease_token IS NOT NULL;

-- Fermeture de la dette FK : job_id référence désormais réellement une
-- ligne jobs quand il est renseigné. NULL reste toujours valide (aucune
-- ligne workflow_events existante, toutes à job_id NULL par construction
-- LOT44b/44c/44d, n'est affectée par l'ajout de cette contrainte).
--
-- Remédiation revue PR#90 (Cubic P2, puis P1 en revue incrémentale) :
-- PostgreSQL ne supporte pas ``ADD CONSTRAINT IF NOT EXISTS`` — sans cette
-- garde explicite, rejouer cette migration (registre absent/reconstruit,
-- ou script rejoué à la main pour un diagnostic) échouait sur une
-- contrainte déjà présente, contredisant la documentation "idempotent" du
-- reste de ce dépôt.
--
-- Un nom de contrainte PostgreSQL n'est unique **que par table**, jamais
-- par schéma : la première version de cette garde ne filtrait que sur
-- ``conname`` + ``connamespace``, donc une contrainte same-named sur une
-- **autre** table de ce schéma (``jobs``, ``resources``, etc.) aurait fait
-- passer ce garde-fou comme "déjà présent" et sauté silencieusement la
-- création de la vraie FK sur ``workflow_events`` — le bootstrap aurait
-- alors enregistré la migration comme appliquée avec succès alors que
-- ``workflow_events.job_id`` resterait sans contrainte réelle, acceptant
-- des valeurs invalides indéfiniment. ``conrelid`` scope désormais
-- explicitement la recherche à ``ingestion_control.workflow_events``, et
-- ``pg_get_constraintdef`` vérifie que la contrainte trouvée est bien
-- exactement la FK attendue vers ``ingestion_control.jobs(job_id)`` —
-- jamais une contrainte homonyme portant une définition différente.
DO $nexus$
DECLARE
    existing_def text;
    expected_def text := 'FOREIGN KEY (job_id) REFERENCES ingestion_control.jobs(job_id)';
BEGIN
    SELECT pg_get_constraintdef(oid) INTO existing_def
    FROM pg_constraint
    WHERE conname = 'workflow_events_job_id_fkey'
      AND conrelid = 'ingestion_control.workflow_events'::regclass
      AND contype = 'f';

    IF existing_def IS NULL THEN
        ALTER TABLE ingestion_control.workflow_events
            ADD CONSTRAINT workflow_events_job_id_fkey
            FOREIGN KEY (job_id) REFERENCES ingestion_control.jobs (job_id);
    ELSIF existing_def IS DISTINCT FROM expected_def THEN
        RAISE EXCEPTION 'MIGRATION_004_FK_MISMATCH: workflow_events_job_id_fkey '
            'exists on ingestion_control.workflow_events but its definition '
            '(%) does not match the expected FK (%) — refusing to silently '
            'accept a differently-defined constraint of the same name',
            existing_def, expected_def;
    END IF;
END
$nexus$;
