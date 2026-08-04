-- Migration 002 : rattachement candidat-ressource et artefacts téléchargés.
--
-- resource_candidates matérialise le rattachement traçable et idempotent
-- entre un candidat découvert et sa ressource (nexus_contracts.ingestion.
-- ResourceCandidate, LOT44a) : resource_id est NOT NULL — un candidat
-- accepté possède toujours une ressource provisoire rattachée dès sa
-- création (jamais de fenêtre orpheline).
--
-- Idempotent : IF NOT EXISTS partout.

CREATE TABLE IF NOT EXISTS ingestion_control.resource_candidates (
    candidate_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id        UUID NOT NULL
        REFERENCES ingestion_control.resources (resource_id),
    run_id             UUID NOT NULL
        REFERENCES ingestion_control.ingestion_runs (run_id),

    dedup_key          TEXT NOT NULL,
    source_url         TEXT NOT NULL,
    canonical_url      TEXT NOT NULL,
    domain             TEXT NOT NULL,
    proposed_type_doc  TEXT NOT NULL,
    discovered_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT resource_candidates_dedup_key_not_blank
        CHECK (btrim(dedup_key) <> ''),
    CONSTRAINT resource_candidates_source_url_not_blank
        CHECK (btrim(source_url) <> ''),
    CONSTRAINT resource_candidates_canonical_url_not_blank
        CHECK (btrim(canonical_url) <> ''),
    CONSTRAINT resource_candidates_domain_not_blank
        CHECK (btrim(domain) <> ''),
    -- Un même candidat (même ressource, même run) ne peut être rattaché
    -- qu'une seule fois — deux rattachements concurrents identiques
    -- (deux workers découvrant la même URL dans le même run) convergent
    -- vers une unique ligne via INSERT ... ON CONFLICT DO NOTHING.
    CONSTRAINT resource_candidates_resource_run_unique
        UNIQUE (resource_id, run_id)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_control_resource_candidates_run_id
    ON ingestion_control.resource_candidates (run_id);

CREATE TABLE IF NOT EXISTS ingestion_control.artifacts (
    artifact_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id        UUID NOT NULL
        REFERENCES ingestion_control.resources (resource_id),
    run_id             UUID NOT NULL
        REFERENCES ingestion_control.ingestion_runs (run_id),

    sha256             TEXT NOT NULL,
    size_bytes         BIGINT NOT NULL,
    mime_declared      TEXT NOT NULL,
    mime_detected      TEXT NOT NULL,
    original_url       TEXT NOT NULL,
    final_url          TEXT NOT NULL,
    collected_at       TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT artifacts_sha256_valid
        CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT artifacts_size_bytes_non_negative
        CHECK (size_bytes >= 0),
    CONSTRAINT artifacts_mime_declared_not_blank
        CHECK (btrim(mime_declared) <> ''),
    CONSTRAINT artifacts_mime_detected_not_blank
        CHECK (btrim(mime_detected) <> ''),
    CONSTRAINT artifacts_original_url_not_blank
        CHECK (btrim(original_url) <> ''),
    CONSTRAINT artifacts_final_url_not_blank
        CHECK (btrim(final_url) <> ''),
    -- Déduplication de contenu (post-fetch) : le même hash pour la même
    -- ressource n'est jamais dupliqué. La déduplication *inter-ressources*
    -- (même contenu, deux ressources différentes) reste une décision de
    -- routage explicite (RoutingDecision.decision = 'DUPLICATE'), pas une
    -- contrainte de base — hors périmètre de cette migration.
    CONSTRAINT artifacts_resource_sha256_unique
        UNIQUE (resource_id, sha256)
);

CREATE INDEX IF NOT EXISTS idx_ingestion_control_artifacts_run_id
    ON ingestion_control.artifacts (run_id);
