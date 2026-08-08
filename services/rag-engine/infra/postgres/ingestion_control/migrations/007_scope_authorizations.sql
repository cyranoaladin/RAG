-- Migration 007 : table scope_authorizations — LOT41A, ADR-0032.
--
-- Porte la sérialisation de nexus_contracts.scope_authorization
-- .ScopeAuthorization, plus les colonnes de révocation (même frontière
-- GitHub que l'octroi, jamais un simple UPDATE opérateur, ADR-0032 § 3).
--
-- Aucune colonne "approved"/"valid" figée : la validité n'est jamais un
-- booléen stocké ici, toujours recalculée en direct par
-- ingestor.ingestion_control.scope_authority.verify_scope_authorization
-- (ADR-0032 § 4) contre la frontière GitHub (scripts/github/
-- trusted_human_review_github.check_github_review) au moment de l'usage.
-- Cette table ne fait que transporter ce qu'une autorisation prétend être.
--
-- Écriture réservée à un rôle dédié ingestion_control_authority (least
-- privilege, distinct du rôle worker ingestion_control_app — le worker ne
-- peut jamais s'auto-écrire une autorisation), provisionné par
-- infra/scripts/provision_ingestion_control_roles.sh.
--
-- Idempotent : IF NOT EXISTS partout, sûr à rejouer.
--
-- PostgreSQL interdit une sous-requête directement dans l'expression d'une
-- contrainte CHECK ("cannot use subquery in check constraint") — la
-- vérification "aucun domaine wildcard" (nexus_contracts.scope_authorization
-- ._no_wildcard_domain, reproduite en base) est donc encapsulée dans cette
-- fonction IMMUTABLE dédiée, appelée depuis la contrainte CHECK ci-dessous.
CREATE OR REPLACE FUNCTION ingestion_control._scope_authorizations_no_wildcard_domain(domains TEXT[])
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $func$
    SELECT NOT EXISTS (
        SELECT 1 FROM unnest(domains) AS d(domain)
        WHERE btrim(d.domain) = '' OR btrim(d.domain) = '*'
            OR btrim(d.domain) LIKE '*.%'
    )
$func$;

CREATE TABLE IF NOT EXISTS ingestion_control.scope_authorizations (
    authorization_id    TEXT PRIMARY KEY,
    decision             TEXT NOT NULL,

    -- Liaison aux octets exactement revus (remédiation GATE H1, item B).
    -- protocol_version/artifact_path/authorization_digest identifient
    -- l'artefact canonique versionné dans le HEAD revu ; le digest est
    -- recalculé à chaque vérification (a) depuis les colonnes de CETTE
    -- ligne et (b) depuis le blob relu en direct à ce HEAD — toute
    -- divergence de l'un ou l'autre côté échoue fail-closed.
    protocol_version       TEXT NOT NULL DEFAULT 'LOT41A-ARTIFACT-V1',
    artifact_path          TEXT NOT NULL,
    authorization_digest   TEXT NOT NULL,

    -- Scope complet obligatoire et fail-closed — mêmes dix dimensions et
    -- mêmes contraintes que ingestion_control.resources/ingestion_runs
    -- (nexus_contracts.ingestion.ResourceScope, réutilisé tel quel).
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

    manifest_digest       TEXT NOT NULL,
    profile_id            TEXT NOT NULL,
    profile_version       TEXT NOT NULL,
    profile_fingerprint   TEXT NOT NULL,

    allowed_domains        TEXT[] NOT NULL,
    rights_categories      TEXT[] NOT NULL,
    exclusions              TEXT[] NOT NULL DEFAULT '{}',
    pii_absence_attested    BOOLEAN NOT NULL,
    pii_absence_evidence    TEXT NOT NULL,

    valid_from            TIMESTAMPTZ NOT NULL,
    valid_until           TIMESTAMPTZ NOT NULL,

    -- evidence — GitHubApprovalEvidence, mêmes champs que le readback du
    -- check "Evaluate trusted human review" (ADR-0025/LOT41V).
    evidence_repository        TEXT NOT NULL,
    evidence_pull_request      INTEGER NOT NULL,
    evidence_base_sha          TEXT NOT NULL,
    evidence_head_sha          TEXT NOT NULL,
    evidence_review_id         BIGINT NOT NULL,
    evidence_reviewer          TEXT NOT NULL,
    evidence_submitted_at      TIMESTAMPTZ NOT NULL,
    evidence_challenge         TEXT NOT NULL,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Révocation — nullable, présente seulement si révoqué. Même structure
    -- GitHubApprovalEvidence, sur une PR de révocation dédiée.
    revoked_at                            TIMESTAMPTZ,
    revoked_by                            TEXT,
    revocation_reason                     TEXT,
    -- Même liaison au contenu revu pour la révocation (item B) :
    -- authorization_id et motif font partie des octets approuvés.
    revocation_artifact_path              TEXT,
    revocation_digest                     TEXT,
    revocation_evidence_repository        TEXT,
    revocation_evidence_pull_request      INTEGER,
    revocation_evidence_base_sha          TEXT,
    revocation_evidence_head_sha          TEXT,
    revocation_evidence_review_id         BIGINT,
    revocation_evidence_reviewer          TEXT,
    revocation_evidence_submitted_at      TIMESTAMPTZ,
    revocation_evidence_challenge         TEXT,

    CONSTRAINT scope_authorizations_authorization_id_not_blank
        CHECK (btrim(authorization_id) <> ''),
    CONSTRAINT scope_authorizations_protocol_version_valid
        CHECK (protocol_version = 'LOT41A-ARTIFACT-V1'),
    CONSTRAINT scope_authorizations_artifact_path_canonical
        CHECK (artifact_path = 'governance/authorizations/' || authorization_id || '.json'),
    CONSTRAINT scope_authorizations_authorization_digest_valid
        CHECK (authorization_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT scope_authorizations_revocation_digest_valid
        CHECK (revocation_digest IS NULL OR revocation_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT scope_authorizations_revocation_artifact_path_canonical
        CHECK (
            revocation_artifact_path IS NULL
            OR revocation_artifact_path = 'governance/revocations/' || authorization_id || '.json'
        ),
    CONSTRAINT scope_authorizations_decision_valid
        CHECK (decision = 'AUTHORIZE_INGESTION_SCOPE'),
    CONSTRAINT scope_authorizations_tenant_not_blank
        CHECK (btrim(tenant) <> ''),
    CONSTRAINT scope_authorizations_collection_not_blank
        CHECK (btrim(collection) <> ''),
    CONSTRAINT scope_authorizations_niveau_not_blank
        CHECK (btrim(niveau) <> ''),
    CONSTRAINT scope_authorizations_voie_not_blank
        CHECK (btrim(voie) <> ''),
    CONSTRAINT scope_authorizations_matiere_not_blank
        CHECK (btrim(matiere) <> ''),
    CONSTRAINT scope_authorizations_candidat_valid
        CHECK (candidat IN (
            'scolarise', 'individuel', 'libre', 'cned_reglemente',
            'cned_libre', 'aefe', 'both'
        )),
    CONSTRAINT scope_authorizations_audience_not_empty
        CHECK (cardinality(audience) > 0),
    CONSTRAINT scope_authorizations_visibility_valid
        CHECK (visibility IN ('public', 'internal', 'restricted', 'private')),
    CONSTRAINT scope_authorizations_school_year_valid
        CHECK (
            school_year ~ '^[0-9]{4}-[0-9]{4}$'
            AND split_part(school_year, '-', 2)::integer
                = split_part(school_year, '-', 1)::integer + 1
        ),
    CONSTRAINT scope_authorizations_programme_version_not_blank
        CHECK (btrim(programme_version) <> ''),
    CONSTRAINT scope_authorizations_manifest_digest_valid
        CHECK (manifest_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT scope_authorizations_profile_id_not_blank
        CHECK (btrim(profile_id) <> ''),
    CONSTRAINT scope_authorizations_profile_version_not_blank
        CHECK (btrim(profile_version) <> ''),
    CONSTRAINT scope_authorizations_profile_fingerprint_valid
        CHECK (profile_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT scope_authorizations_allowed_domains_not_empty
        CHECK (cardinality(allowed_domains) > 0),
    -- Jamais un wildcard — même invariant que
    -- nexus_contracts.scope_authorization._no_wildcard_domain, reproduit en
    -- base pour qu'une insertion hors du chemin Python contrôlé (ex.
    -- intervention manuelle) ne puisse pas non plus l'introduire.
    CONSTRAINT scope_authorizations_allowed_domains_no_wildcard
        CHECK (ingestion_control._scope_authorizations_no_wildcard_domain(allowed_domains)),
    CONSTRAINT scope_authorizations_rights_categories_not_empty
        CHECK (cardinality(rights_categories) > 0),
    CONSTRAINT scope_authorizations_pii_absence_attested_true
        CHECK (pii_absence_attested = true),
    CONSTRAINT scope_authorizations_pii_absence_evidence_not_blank
        CHECK (btrim(pii_absence_evidence) <> ''),
    CONSTRAINT scope_authorizations_validity_window_coherent
        CHECK (valid_until > valid_from),
    CONSTRAINT scope_authorizations_evidence_repository_not_blank
        CHECK (btrim(evidence_repository) <> ''),
    CONSTRAINT scope_authorizations_evidence_pull_request_positive
        CHECK (evidence_pull_request > 0),
    CONSTRAINT scope_authorizations_evidence_base_sha_valid
        CHECK (evidence_base_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT scope_authorizations_evidence_head_sha_valid
        CHECK (evidence_head_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT scope_authorizations_evidence_review_id_positive
        CHECK (evidence_review_id > 0),
    CONSTRAINT scope_authorizations_evidence_reviewer_not_blank
        CHECK (btrim(evidence_reviewer) <> ''),
    CONSTRAINT scope_authorizations_evidence_challenge_valid
        CHECK (evidence_challenge ~ '^NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}$'),
    -- Révocation : tout ou rien — soit les 11 colonnes de révocation sont
    -- toutes NULL (jamais révoqué), soit toutes renseignées (révoqué avec
    -- preuve complète). Jamais un état intermédiaire (ex. revoked_at
    -- renseigné sans evidence) qui laisserait une révocation non prouvée.
    CONSTRAINT scope_authorizations_revocation_all_or_nothing
        CHECK (
            num_nulls(
                revoked_at, revoked_by, revocation_reason,
                revocation_artifact_path, revocation_digest,
                revocation_evidence_repository, revocation_evidence_pull_request,
                revocation_evidence_base_sha, revocation_evidence_head_sha,
                revocation_evidence_review_id, revocation_evidence_reviewer,
                revocation_evidence_submitted_at, revocation_evidence_challenge
            ) IN (0, 13)
        ),
    CONSTRAINT scope_authorizations_revocation_base_sha_valid
        CHECK (revocation_evidence_base_sha IS NULL OR revocation_evidence_base_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT scope_authorizations_revocation_head_sha_valid
        CHECK (revocation_evidence_head_sha IS NULL OR revocation_evidence_head_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT scope_authorizations_revocation_challenge_valid
        CHECK (
            revocation_evidence_challenge IS NULL
            OR revocation_evidence_challenge ~ '^NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}$'
        )
);

-- Recherche de l'autorisation active la plus récente pour un scope/
-- collection donné — prédicat exact de verify_scope_authorization.
CREATE INDEX IF NOT EXISTS idx_ingestion_control_scope_authorizations_lookup
    ON ingestion_control.scope_authorizations (
        collection, tenant, niveau, voie, matiere, candidat,
        visibility, school_year, programme_version, valid_until DESC
    )
    WHERE revoked_at IS NULL;
