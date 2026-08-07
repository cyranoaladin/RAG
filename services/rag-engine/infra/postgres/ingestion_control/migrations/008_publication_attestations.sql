-- Migration 008 : table publication_attestations — LOT42, ADR-0033.
--
-- Porte la sérialisation de nexus_contracts.publication_attestation
-- .PublicationAttestation. Comme scope_authorizations (007), aucune colonne
-- de confiance figée ("valid") : la validité est toujours recalculée en
-- direct par ingestor.ingestion_control.publication_attestation
-- .verify_publication_attestation (ADR-0033 § 4), jamais un statut mis en
-- cache — invalidated_at/invalidated_reason enregistrent seulement le
-- résultat d'une invalidation déjà détectée par cette relecture live,
-- jamais une source de vérité en eux-mêmes.
--
-- Écriture réservée à un rôle dédié ingestion_control_attestor (least
-- privilege, distinct de ingestion_control_app et de
-- ingestion_control_authority), provisionné par
-- infra/scripts/provision_ingestion_control_roles.sh.
--
-- Idempotent : IF NOT EXISTS partout, sûr à rejouer.

CREATE TABLE IF NOT EXISTS ingestion_control.publication_attestations (
    attestation_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    resource_id           UUID NOT NULL
        REFERENCES ingestion_control.resources (resource_id),
    artifact_id            UUID NOT NULL
        REFERENCES ingestion_control.artifacts (artifact_id),

    content_sha256         TEXT NOT NULL,
    canonical_url           TEXT NOT NULL,
    collection               TEXT NOT NULL,
    scope_authorization_id   TEXT NOT NULL
        REFERENCES ingestion_control.scope_authorizations (authorization_id),

    profile_id              TEXT NOT NULL,
    profile_version          TEXT NOT NULL,
    profile_fingerprint      TEXT NOT NULL,
    manifest_digest           TEXT NOT NULL,

    rights_status             TEXT NOT NULL,
    rights_assessed_at         TIMESTAMPTZ NOT NULL,

    quality_passed              BOOLEAN NOT NULL,
    quality_score                 DOUBLE PRECISION NOT NULL,
    quality_assessed_at            TIMESTAMPTZ NOT NULL,

    gate_passed                     BOOLEAN NOT NULL,
    gate_name                        TEXT NOT NULL,
    gate_evaluated_at                 TIMESTAMPTZ NOT NULL,

    -- human_review — HumanReviewEvidence, alias exact de
    -- GitHubApprovalEvidence (ADR-0033 § 3, jamais une seconde frontière).
    human_review_repository            TEXT NOT NULL,
    human_review_pull_request           INTEGER NOT NULL,
    human_review_base_sha                TEXT NOT NULL,
    human_review_head_sha                 TEXT NOT NULL,
    human_review_review_id                 BIGINT NOT NULL,
    human_review_reviewer                   TEXT NOT NULL,
    human_review_submitted_at                TIMESTAMPTZ NOT NULL,
    human_review_challenge                    TEXT NOT NULL,

    protocol_version           TEXT NOT NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Invalidation — nullable, renseignée seulement après détection live
    -- d'une des cinq conditions d'ADR-0033 § 4. Jamais renseignée à
    -- l'écriture initiale.
    invalidated_at               TIMESTAMPTZ,
    invalidated_reason            TEXT,

    CONSTRAINT publication_attestations_content_sha256_valid
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT publication_attestations_canonical_url_not_blank
        CHECK (btrim(canonical_url) <> ''),
    CONSTRAINT publication_attestations_collection_not_blank
        CHECK (btrim(collection) <> ''),
    CONSTRAINT publication_attestations_scope_authorization_id_not_blank
        CHECK (btrim(scope_authorization_id) <> ''),
    CONSTRAINT publication_attestations_profile_id_not_blank
        CHECK (btrim(profile_id) <> ''),
    CONSTRAINT publication_attestations_profile_version_not_blank
        CHECK (btrim(profile_version) <> ''),
    CONSTRAINT publication_attestations_profile_fingerprint_valid
        CHECK (profile_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT publication_attestations_manifest_digest_valid
        CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT publication_attestations_rights_status_valid
        CHECK (rights_status IN (
            'officiel_public', 'public_allowed', 'nexus_proprietaire',
            'usage_interne', 'student_private', 'parent_private',
            'commercial_confidential', 'restricted', 'unknown'
        )),
    CONSTRAINT publication_attestations_quality_score_range
        CHECK (quality_score >= 0 AND quality_score <= 1),
    CONSTRAINT publication_attestations_gate_name_not_blank
        CHECK (btrim(gate_name) <> ''),
    CONSTRAINT publication_attestations_human_review_repository_not_blank
        CHECK (btrim(human_review_repository) <> ''),
    CONSTRAINT publication_attestations_human_review_pull_request_positive
        CHECK (human_review_pull_request > 0),
    CONSTRAINT publication_attestations_human_review_base_sha_valid
        CHECK (human_review_base_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT publication_attestations_human_review_head_sha_valid
        CHECK (human_review_head_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT publication_attestations_human_review_review_id_positive
        CHECK (human_review_review_id > 0),
    CONSTRAINT publication_attestations_human_review_reviewer_not_blank
        CHECK (btrim(human_review_reviewer) <> ''),
    CONSTRAINT publication_attestations_human_review_challenge_valid
        CHECK (human_review_challenge ~ '^NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}$'),
    CONSTRAINT publication_attestations_protocol_version_valid
        CHECK (protocol_version = 'LOT42-V1'),
    CONSTRAINT publication_attestations_invalidation_all_or_nothing
        CHECK ((invalidated_at IS NULL) = (invalidated_reason IS NULL))
);

CREATE INDEX IF NOT EXISTS idx_ingestion_control_pub_attestations_resource_id
    ON ingestion_control.publication_attestations (resource_id);

CREATE INDEX IF NOT EXISTS idx_ingestion_control_pub_attestations_scope_auth_id
    ON ingestion_control.publication_attestations (scope_authorization_id);

-- Au plus une attestation active (non invalidée) par ressource — une
-- nouvelle attestation ne peut être construite pour la même ressource
-- qu'après invalidation explicite de la précédente, jamais en parallèle.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ingestion_control_pub_attestations_resource_active_uniq
    ON ingestion_control.publication_attestations (resource_id)
    WHERE invalidated_at IS NULL;
