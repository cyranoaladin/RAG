-- Migration 015 : preuve de revue SCELLÉE et registre de révocation (ADR-0058).
--
-- Le modèle de revue change de temps, pas de sévérité. Jusqu'ici, l'usage
-- d'une autorisation revérifiait en direct que la pull request d'autorité
-- était encore OUVERTE. Or l'artefact d'autorisation doit être sur `main`
-- pour être relu, donc la PR doit être fusionnée : les deux ne peuvent pas
-- être vraies au même moment. Mesuré sur la PR #233, l'usage répondait
-- `pull_request_not_open` alors que la revue humaine avait bien eu lieu.
--
-- Désormais : tout reste exigé en direct à l'ENREGISTREMENT, et c'est cette
-- preuve-là qui est vérifiée à l'USAGE.
--
-- `review_evidence` est NULLABLE, et c'est délibéré : les lignes écrites
-- sous l'ancien modèle n'en ont pas, et n'en auront jamais rétroactivement.
-- Aucun backfill n'est possible — une preuve de revue ne se reconstitue pas
-- après coup. Ces lignes deviennent donc inutilisables à l'usage, ce qui est
-- le comportement voulu : pas de preuve, pas d'autorisation. Les rendre
-- NOT NULL ici échouerait simplement l'application de la migration ; les
-- laisser passer sans preuve serait pire.
--
-- Idempotent : IF NOT EXISTS partout, contraintes DROP puis ADD, sûr à
-- rejouer. Aucun BEGIN/COMMIT : le bootstrap applique déjà chaque migration
-- dans sa propre transaction (`--single-transaction`).

-- ---------------------------------------------------------------------
-- 1. La preuve scellée, portée par l'autorisation qu'elle justifie.
-- ---------------------------------------------------------------------

ALTER TABLE ingestion_control.scope_authorizations
    ADD COLUMN IF NOT EXISTS review_evidence JSONB;

ALTER TABLE ingestion_control.scope_authorizations
    ADD COLUMN IF NOT EXISTS review_evidence_digest TEXT;

ALTER TABLE ingestion_control.scope_authorizations
    DROP CONSTRAINT IF EXISTS scope_authorizations_review_evidence_paired;

-- Les deux colonnes vont ensemble ou pas du tout : une preuve sans digest
-- ne serait liée à rien, un digest sans preuve ne prouverait rien.
--
-- `review_evidence_digest IS NOT NULL` n'est PAS redondant avec le motif qui
-- suit, et l'omettre rendait cette contrainte inopérante : en logique
-- ternaire, `NULL ~ '...'` vaut NULL, la seconde branche valait donc NULL,
-- et `FALSE OR NULL` vaut NULL — qu'un CHECK PostgreSQL **accepte**, car
-- seul FALSE rejette. Une preuve sans digest passait. Le test sur base
-- réelle l'a montré ; le motif seul ne l'aurait jamais montré.
ALTER TABLE ingestion_control.scope_authorizations
    ADD CONSTRAINT scope_authorizations_review_evidence_paired
    CHECK (
        (review_evidence IS NULL AND review_evidence_digest IS NULL)
        OR (
            review_evidence IS NOT NULL
            AND review_evidence_digest IS NOT NULL
            AND review_evidence_digest ~ '^[0-9a-f]{64}$'
            AND jsonb_typeof(review_evidence) = 'object'
            AND review_evidence <> '{}'::jsonb
        )
    );

ALTER TABLE ingestion_control.scope_authorizations
    DROP CONSTRAINT IF EXISTS scope_authorizations_review_evidence_protocol;

-- Le protocole est nommé DANS la preuve. Une preuve d'un autre protocole ne
-- peut pas se glisser ici en se présentant comme celle-ci.
ALTER TABLE ingestion_control.scope_authorizations
    ADD CONSTRAINT scope_authorizations_review_evidence_protocol
    CHECK (
        review_evidence IS NULL
        OR review_evidence ->> 'protocol_version'
           = 'NEXUS-SEALED-TRUSTED-REVIEW-EVIDENCE-V1'
    );

CREATE INDEX IF NOT EXISTS idx_ingestion_control_scope_auth_review_evidence_digest
    ON ingestion_control.scope_authorizations (review_evidence_digest)
    WHERE review_evidence_digest IS NOT NULL;

-- ---------------------------------------------------------------------
-- 2. Le registre de révocation des preuves.
--
--    Une preuve scellée ne s'éteint pas d'elle-même : sans ce registre,
--    elle serait une autorisation éternelle. Révoquer la preuve invalide
--    d'un coup toutes les autorisations qui s'en réclament, sans avoir à
--    les révoquer une par une — ce que `scope_authorizations.revoked_at`
--    continue de permettre pour le cas unitaire.
-- ---------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS ingestion_control.revoked_review_evidence (
    review_evidence_digest  TEXT PRIMARY KEY,

    revoked_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_by              TEXT NOT NULL,
    reason                  TEXT NOT NULL,

    -- La révocation est elle-même une décision humaine gouvernée : elle
    -- porte sa propre preuve de revue, comme l'autorisation qu'elle éteint.
    evidence_repository     TEXT NOT NULL,
    evidence_pull_request   INTEGER NOT NULL,
    evidence_head_sha       TEXT NOT NULL,
    evidence_reviewer       TEXT NOT NULL,
    evidence_challenge      TEXT NOT NULL,

    CONSTRAINT revoked_review_evidence_digest_valid
        CHECK (review_evidence_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT revoked_review_evidence_revoked_by_not_blank
        CHECK (btrim(revoked_by) <> ''),
    CONSTRAINT revoked_review_evidence_reason_not_blank
        CHECK (btrim(reason) <> ''),
    CONSTRAINT revoked_review_evidence_head_sha_valid
        CHECK (evidence_head_sha ~ '^[0-9a-f]{40}$'),
    CONSTRAINT revoked_review_evidence_pull_request_positive
        CHECK (evidence_pull_request > 0),
    CONSTRAINT revoked_review_evidence_reviewer_not_blank
        CHECK (btrim(evidence_reviewer) <> ''),
    CONSTRAINT revoked_review_evidence_challenge_not_blank
        CHECK (btrim(evidence_challenge) <> '')
);
