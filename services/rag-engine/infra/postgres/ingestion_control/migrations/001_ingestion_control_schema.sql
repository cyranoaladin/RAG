-- Migration 001 : schéma ingestion_control — schéma logique dédié, table
-- ingestion_runs, et table resources (identité maîtresse + machine d'état).
--
-- Décision D1 : même instance PostgreSQL/pgvector que le reste du projet,
-- schéma logique séparé "ingestion_control" — aucune table de contrôle dans
-- "public"/rag_chunks, aucune jointure implicite entre schémas.
--
-- Machine d'état reprise à l'identique de nexus_contracts.resource_state
-- (LOT44a, ADR-0026) : 20 valeurs, PUBLISHED explicitement absent. CANDIDATE
-- et STAGED restent non adjacentes (7 états intermédiaires obligatoires).
--
-- Idempotent : IF NOT EXISTS partout, sûr à rejouer.

CREATE SCHEMA IF NOT EXISTS ingestion_control;

CREATE TABLE IF NOT EXISTS ingestion_control.ingestion_runs (
    run_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Scope complet obligatoire et fail-closed (dix dimensions, aucun défaut).
    tenant              TEXT NOT NULL,
    collection          TEXT NOT NULL,
    niveau              TEXT NOT NULL,
    voie                TEXT NOT NULL,
    matiere             TEXT NOT NULL,
    candidat            TEXT NOT NULL,
    audience            TEXT[] NOT NULL,
    visibility          TEXT NOT NULL,
    school_year         TEXT NOT NULL,
    programme_version   TEXT NOT NULL,

    profile_version     TEXT NOT NULL,
    trigger             TEXT NOT NULL,
    mode                TEXT NOT NULL DEFAULT 'auto_stage',
    status              TEXT NOT NULL DEFAULT 'planned',

    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT ingestion_runs_tenant_not_blank
        CHECK (btrim(tenant) <> ''),
    CONSTRAINT ingestion_runs_collection_not_blank
        CHECK (btrim(collection) <> ''),
    CONSTRAINT ingestion_runs_niveau_not_blank
        CHECK (btrim(niveau) <> ''),
    CONSTRAINT ingestion_runs_voie_not_blank
        CHECK (btrim(voie) <> ''),
    CONSTRAINT ingestion_runs_matiere_not_blank
        CHECK (btrim(matiere) <> ''),
    CONSTRAINT ingestion_runs_candidat_valid
        CHECK (candidat IN (
            'scolarise', 'individuel', 'libre', 'cned_reglemente',
            'cned_libre', 'aefe', 'both'
        )),
    CONSTRAINT ingestion_runs_audience_not_empty
        CHECK (cardinality(audience) > 0),
    CONSTRAINT ingestion_runs_visibility_valid
        CHECK (visibility IN ('public', 'internal', 'restricted', 'private')),
    CONSTRAINT ingestion_runs_school_year_valid
        CHECK (
            school_year ~ '^[0-9]{4}-[0-9]{4}$'
            AND split_part(school_year, '-', 2)::integer
                = split_part(school_year, '-', 1)::integer + 1
        ),
    CONSTRAINT ingestion_runs_programme_version_not_blank
        CHECK (btrim(programme_version) <> ''),
    CONSTRAINT ingestion_runs_profile_version_not_blank
        CHECK (btrim(profile_version) <> ''),
    CONSTRAINT ingestion_runs_trigger_valid
        CHECK (trigger IN ('scheduled', 'manual')),
    -- mode : verrouillé à 'auto_stage' — aucune notion de publication ou
    -- d'auto-publication n'est représentable ici (LOT44a, PublicationPolicy
    -- verrouillée au type ; ce même verrouillage est reproduit en base).
    CONSTRAINT ingestion_runs_mode_valid
        CHECK (mode = 'auto_stage'),
    CONSTRAINT ingestion_runs_status_valid
        CHECK (status IN (
            'planned', 'running', 'succeeded', 'failed', 'partial', 'cancelled'
        )),
    CONSTRAINT ingestion_runs_finished_after_started
        CHECK (started_at IS NULL OR finished_at IS NULL OR finished_at >= started_at)
);

CREATE TABLE IF NOT EXISTS ingestion_control.resources (
    resource_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id               UUID NOT NULL
        REFERENCES ingestion_control.ingestion_runs (run_id),

    -- Clé de déduplication déterministe (sha256(collection || url_canonique)),
    -- réservée à la déduplication/l'idempotence — jamais utilisée comme
    -- identifiant primaire (resource_id, UUID, reste l'identifiant).
    dedup_key            TEXT NOT NULL,

    -- Scope complet obligatoire et fail-closed — dix dimensions, aucun défaut.
    tenant               TEXT NOT NULL,
    collection           TEXT NOT NULL,
    niveau               TEXT NOT NULL,
    voie                 TEXT NOT NULL,
    matiere              TEXT NOT NULL,
    candidat             TEXT NOT NULL,
    audience             TEXT[] NOT NULL,
    visibility           TEXT NOT NULL,
    school_year          TEXT NOT NULL,
    programme_version    TEXT NOT NULL,

    -- Machine d'état (nexus_contracts.resource_state, LOT44a) : 20 valeurs,
    -- PUBLISHED explicitement absent de cette liste et de tout ce schéma.
    resource_state       TEXT NOT NULL DEFAULT 'DISCOVERED',
    state_version        BIGINT NOT NULL DEFAULT 0,

    -- Rattachement à une ressource dupliquée (contenu, constaté après fetch) —
    -- jamais renseigné pour une simple collision d'identité (dedup_key), qui
    -- est résolue par la contrainte UNIQUE ci-dessous sans jamais créer deux
    -- lignes "resources" pour la même identité.
    duplicate_of_resource_id UUID
        REFERENCES ingestion_control.resources (resource_id),

    -- Claim / lease — primitive de concurrence (cf. 003 pour workflow_events
    -- qui journalise chaque claim/transition).
    claimed_by           TEXT,
    lease_token          UUID,
    lease_expires_at     TIMESTAMPTZ,

    -- Retry / backoff.
    attempt_count        INTEGER NOT NULL DEFAULT 0,
    max_attempts         INTEGER NOT NULL DEFAULT 3,
    next_attempt_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_error           TEXT,

    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT resources_dedup_key_not_blank
        CHECK (btrim(dedup_key) <> ''),
    CONSTRAINT resources_tenant_not_blank
        CHECK (btrim(tenant) <> ''),
    CONSTRAINT resources_collection_not_blank
        CHECK (btrim(collection) <> ''),
    CONSTRAINT resources_niveau_not_blank
        CHECK (btrim(niveau) <> ''),
    CONSTRAINT resources_voie_not_blank
        CHECK (btrim(voie) <> ''),
    CONSTRAINT resources_matiere_not_blank
        CHECK (btrim(matiere) <> ''),
    CONSTRAINT resources_candidat_valid
        CHECK (candidat IN (
            'scolarise', 'individuel', 'libre', 'cned_reglemente',
            'cned_libre', 'aefe', 'both'
        )),
    CONSTRAINT resources_audience_not_empty
        CHECK (cardinality(audience) > 0),
    CONSTRAINT resources_visibility_valid
        CHECK (visibility IN ('public', 'internal', 'restricted', 'private')),
    CONSTRAINT resources_school_year_valid
        CHECK (
            school_year ~ '^[0-9]{4}-[0-9]{4}$'
            AND split_part(school_year, '-', 2)::integer
                = split_part(school_year, '-', 1)::integer + 1
        ),
    CONSTRAINT resources_programme_version_not_blank
        CHECK (btrim(programme_version) <> ''),
    -- 20 valeurs exactes de nexus_contracts.resource_state. PUBLISHED est
    -- délibérément absent : toute tentative d'y insérer cette valeur est
    -- rejetée par cette contrainte, jamais seulement par convention Python.
    CONSTRAINT resources_state_valid
        CHECK (resource_state IN (
            'DISCOVERED', 'CANDIDATE', 'FETCHED', 'STORED', 'EXTRACTED',
            'CLASSIFIED', 'RIGHTS_CHECKED', 'QUALITY_CHECKED', 'ROUTED',
            'STAGED', 'NEEDS_REVIEW', 'REVIEWED', 'RETRIEVAL_ELIGIBLE',
            'FAILED', 'DEAD_LETTER', 'CANCELLED', 'REJECTED', 'QUARANTINED',
            'DUPLICATE', 'SUPERSEDED'
        )),
    CONSTRAINT resources_state_version_non_negative
        CHECK (state_version >= 0),
    CONSTRAINT resources_attempt_count_non_negative
        CHECK (attempt_count >= 0),
    CONSTRAINT resources_max_attempts_positive
        CHECK (max_attempts > 0),
    CONSTRAINT resources_lease_token_requires_expiry
        CHECK ((lease_token IS NULL) = (lease_expires_at IS NULL)),
    -- Déduplication déterministe par identité : deux candidats de même
    -- collection et même dedup_key ne peuvent jamais produire deux lignes
    -- "resources" — la seconde tentative récupère la première via
    -- INSERT ... ON CONFLICT (cf. primitive attach_candidate côté Python).
    CONSTRAINT resources_collection_dedup_key_unique
        UNIQUE (collection, dedup_key)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_control_resources_run_id
    ON ingestion_control.resources (run_id);

-- Index de claim : les lignes éligibles à une réclamation sont celles dont
-- le bail est expiré/absent et dont la prochaine tentative est due — cet
-- index couvre exactement le prédicat WHERE de la primitive claim_resource.
CREATE INDEX IF NOT EXISTS idx_ingestion_control_resources_claimable
    ON ingestion_control.resources (resource_state, next_attempt_at)
    WHERE lease_token IS NULL;

CREATE INDEX IF NOT EXISTS idx_ingestion_control_resources_lease_expiry
    ON ingestion_control.resources (lease_expires_at)
    WHERE lease_token IS NOT NULL;
