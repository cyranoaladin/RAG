-- Migration 004 : table jobs, et fermeture de la dette FK sur
-- workflow_events.job_id (LOT44e).
--
-- Dette héritée de LOT44b/ADR-0025, reformulée par ADR-0026 : "job_id sans
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
ALTER TABLE ingestion_control.workflow_events
    ADD CONSTRAINT workflow_events_job_id_fkey
    FOREIGN KEY (job_id) REFERENCES ingestion_control.jobs (job_id);
