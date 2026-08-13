-- Migration 011 : point de linéarisation de l'autorité GitHub externe.
--
-- PostgreSQL ne peut pas verrouiller GitHub. Après une vérification live
-- réussie, le publisher persiste donc l'instantané exact des deux revues
-- externes (LOT41A et LOT42) avant d'ouvrir la transaction produit. La
-- publication produit nomme déjà publication_attestation_id dans chaque
-- placement : cette clé est aussi la clé immuable du pin ci-dessous.
--
-- Une évolution GitHub postérieure est ordonnée après ce point de
-- linéarisation. Toute nouvelle tentative doit néanmoins refaire les deux
-- vérifications live et prouver que son instantané est identique à ce pin.

CREATE TABLE IF NOT EXISTS ingestion_control.publication_commit_pins (
    publication_attestation_id UUID PRIMARY KEY
        REFERENCES ingestion_control.publication_attestations (attestation_id),
    resource_id UUID NOT NULL
        REFERENCES ingestion_control.resources (resource_id),
    content_sha256 TEXT NOT NULL,
    attestation_digest TEXT NOT NULL,
    publication_artifact_blob_sha TEXT NOT NULL,
    publication_review_repository TEXT NOT NULL,
    publication_review_pull_request INTEGER NOT NULL,
    publication_review_base_sha TEXT NOT NULL,
    publication_review_head_sha TEXT NOT NULL,
    publication_review_review_id BIGINT NOT NULL,
    publication_review_reviewer TEXT NOT NULL,
    publication_review_submitted_at TIMESTAMPTZ NOT NULL,
    publication_review_challenge TEXT NOT NULL,
    publication_protocol_version TEXT NOT NULL,

    scope_authorization_id TEXT NOT NULL
        REFERENCES ingestion_control.scope_authorizations (authorization_id),
    authorization_digest TEXT NOT NULL,
    authorization_artifact_blob_sha TEXT NOT NULL,
    authorization_review_repository TEXT NOT NULL,
    authorization_review_pull_request INTEGER NOT NULL,
    authorization_review_base_sha TEXT NOT NULL,
    authorization_review_head_sha TEXT NOT NULL,
    authorization_review_review_id BIGINT NOT NULL,
    authorization_review_reviewer TEXT NOT NULL,
    authorization_review_submitted_at TIMESTAMPTZ NOT NULL,
    authorization_review_challenge TEXT NOT NULL,
    authorization_protocol_version TEXT NOT NULL,

    pin_digest TEXT NOT NULL UNIQUE,
    pinned_at TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT publication_commit_pins_content_sha256_valid
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT publication_commit_pins_attestation_digest_valid
        CHECK (attestation_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT publication_commit_pins_publication_blob_sha_valid
        CHECK (publication_artifact_blob_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT publication_commit_pins_publication_repository_not_blank
        CHECK (btrim(publication_review_repository) <> ''),
    CONSTRAINT publication_commit_pins_publication_pr_positive
        CHECK (publication_review_pull_request > 0),
    CONSTRAINT publication_commit_pins_publication_base_sha_valid
        CHECK (publication_review_base_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT publication_commit_pins_publication_head_sha_valid
        CHECK (publication_review_head_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT publication_commit_pins_publication_review_id_positive
        CHECK (publication_review_review_id > 0),
    CONSTRAINT publication_commit_pins_publication_reviewer_not_blank
        CHECK (btrim(publication_review_reviewer) <> ''),
    CONSTRAINT publication_commit_pins_publication_challenge_valid
        CHECK (publication_review_challenge ~ '^NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}$'),
    CONSTRAINT publication_commit_pins_publication_protocol_valid
        CHECK (publication_protocol_version = 'LOT42-V1'),
    CONSTRAINT publication_commit_pins_authorization_id_not_blank
        CHECK (btrim(scope_authorization_id) <> ''),
    CONSTRAINT publication_commit_pins_authorization_digest_valid
        CHECK (authorization_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT publication_commit_pins_authorization_blob_sha_valid
        CHECK (authorization_artifact_blob_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT publication_commit_pins_authorization_repository_not_blank
        CHECK (btrim(authorization_review_repository) <> ''),
    CONSTRAINT publication_commit_pins_authorization_pr_positive
        CHECK (authorization_review_pull_request > 0),
    CONSTRAINT publication_commit_pins_authorization_base_sha_valid
        CHECK (authorization_review_base_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT publication_commit_pins_authorization_head_sha_valid
        CHECK (authorization_review_head_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT publication_commit_pins_authorization_review_id_positive
        CHECK (authorization_review_review_id > 0),
    CONSTRAINT publication_commit_pins_authorization_reviewer_not_blank
        CHECK (btrim(authorization_review_reviewer) <> ''),
    CONSTRAINT publication_commit_pins_authorization_challenge_valid
        CHECK (authorization_review_challenge ~ '^NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}$'),
    CONSTRAINT publication_commit_pins_authorization_protocol_v2
        CHECK (authorization_protocol_version = 'LOT41A-V2'),
    CONSTRAINT publication_commit_pins_pin_digest_valid
        CHECK (pin_digest ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_publication_commit_pins_resource
    ON ingestion_control.publication_commit_pins (resource_id);

CREATE INDEX IF NOT EXISTS idx_publication_commit_pins_authorization
    ON ingestion_control.publication_commit_pins (scope_authorization_id);
