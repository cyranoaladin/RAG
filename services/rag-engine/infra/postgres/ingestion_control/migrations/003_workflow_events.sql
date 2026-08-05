-- Migration 003 : journal d'événements append-only.
--
-- run_id est la seule colonne de rattachement obligatoire : un événement
-- vit toujours dans un run, mais peut ne concerner ni un job/claim précis
-- (job_id NULL) ni une ressource précise (resource_id NULL) — par exemple
-- un événement "run_started"/"run_completed". Ne jamais forcer resource_id
-- à NOT NULL : cela empêcherait de journaliser les événements de run.
--
-- job_id : LOT44a ne définit aucun contrat "IngestionJob" séparé, et ce
-- schéma ne crée pas de table "jobs" (aucun concept non justifié). job_id
-- reste NULL par défaut et n'est JAMAIS rempli automatiquement par les
-- primitives de ce lot (ni par claim_resource, ni par cas_transition) — en
-- particulier, il n'est jamais assigné à partir de resources.lease_token :
-- ce sont deux identités distinctes (lease_token = possession temporaire
-- d'un verrou de concurrence, secret et changeant à chaque réclamation ;
-- job_id = identifiant libre d'une éventuelle tentative d'exécution
-- métier, réservé à un futur contrat IngestionJob). Aucune contrainte FK
-- n'est posée sur job_id puisqu'aucune table jobs n'existe dans ce lot.
--
-- La protection append-only réelle (REVOKE UPDATE, DELETE) est appliquée
-- par infra/scripts/provision_ingestion_control_roles.sh sur le rôle
-- runtime, pas par cette migration — cohérent avec la convention déjà en
-- place dans ce dépôt (privilèges gérés hors des fichiers de migration
-- numérotés, cf. infra/scripts/test_hybrid_integration.sh::provision_app_role).
--
-- Idempotent : IF NOT EXISTS partout.

CREATE TABLE IF NOT EXISTS ingestion_control.workflow_events (
    event_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id             UUID NOT NULL
        REFERENCES ingestion_control.ingestion_runs (run_id),
    job_id             UUID,
    resource_id        UUID
        REFERENCES ingestion_control.resources (resource_id),

    event_type         TEXT NOT NULL,
    from_state         TEXT,
    to_state           TEXT,
    occurred_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor              TEXT NOT NULL,
    payload            JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- Réservée aux événements susceptibles d'être dupliqués par un rejeu
    -- applicatif (ex. "claim réclamé") — NULL pour les transitions
    -- ordinaires, dont l'unicité est déjà garantie par la transaction CAS
    -- elle-même. Aucune clé n'est attribuée artificiellement.
    idempotency_key    TEXT,

    CONSTRAINT workflow_events_event_type_not_blank
        CHECK (btrim(event_type) <> ''),
    CONSTRAINT workflow_events_actor_not_blank
        CHECK (btrim(actor) <> ''),
    -- 20 valeurs exactes, PUBLISHED explicitement absent — comme pour
    -- resources_state_valid (001). NULL autorisé (événements non liés à
    -- une transition, ex. "candidate_attached").
    CONSTRAINT workflow_events_from_state_valid
        CHECK (from_state IS NULL OR from_state IN (
            'DISCOVERED', 'CANDIDATE', 'FETCHED', 'STORED', 'EXTRACTED',
            'CLASSIFIED', 'RIGHTS_CHECKED', 'QUALITY_CHECKED', 'ROUTED',
            'STAGED', 'NEEDS_REVIEW', 'REVIEWED', 'RETRIEVAL_ELIGIBLE',
            'FAILED', 'DEAD_LETTER', 'CANCELLED', 'REJECTED', 'QUARANTINED',
            'DUPLICATE', 'SUPERSEDED'
        )),
    CONSTRAINT workflow_events_to_state_valid
        CHECK (to_state IS NULL OR to_state IN (
            'DISCOVERED', 'CANDIDATE', 'FETCHED', 'STORED', 'EXTRACTED',
            'CLASSIFIED', 'RIGHTS_CHECKED', 'QUALITY_CHECKED', 'ROUTED',
            'STAGED', 'NEEDS_REVIEW', 'REVIEWED', 'RETRIEVAL_ELIGIBLE',
            'FAILED', 'DEAD_LETTER', 'CANCELLED', 'REJECTED', 'QUARANTINED',
            'DUPLICATE', 'SUPERSEDED'
        ))
);

CREATE INDEX IF NOT EXISTS idx_ingestion_control_workflow_events_run_id
    ON ingestion_control.workflow_events (run_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_control_workflow_events_resource_id
    ON ingestion_control.workflow_events (resource_id)
    WHERE resource_id IS NOT NULL;

-- Unicité partielle : seules les clés d'idempotence non nulles sont
-- contraintes à l'unicité. Deux événements avec idempotency_key = NULL ne
-- sont jamais en conflit (NULL <> NULL en SQL) ; deux événements portant la
-- même clé non nulle entrent en conflit, ce qui est le comportement
-- recherché.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_control_workflow_events_idempotency_key
    ON ingestion_control.workflow_events (idempotency_key)
    WHERE idempotency_key IS NOT NULL;
