-- Migration 016 : identité de release sur une attestation batch (lot CU).
--
-- La migration 014 a ouvert `protocol_version` à `LOT42-RELEASE-BATCH-V1` et
-- rendu `canonical_url` et `attributed_facts_digest` conditionnels. Mais
-- `publication_attestations` ne portait AUCUNE colonne nommant une release :
-- `grep release_id` sur toutes les migrations rendait zéro, et la base le
-- confirme. Une ligne batch ne pouvait donc pas dire QUELLE release elle
-- atteste, et `require_release_batch_review_matches_release` n'avait aucune
-- donnée persistée à relire.
--
-- Une colonne `release_id` non vide ne suffirait pas : l'attestation doit
-- désigner la release *effectivement couverte*, c'est-à-dire son identité ET
-- les quatre digests qui la scellent. C'est ce que cette migration ajoute,
-- **conditionnellement au protocole** — les chemins unitaires ne portent rien
-- de tout cela et n'ont le droit d'en porter aucun.
--
-- Aucune colonne existante n'est relâchée.

BEGIN;

-- ---------------------------------------------------------------------
-- 1. Les colonnes, toutes NULLables : les lignes unitaires existantes
--    doivent rester valides, et c'est la contrainte conditionnelle qui
--    les rend obligatoires pour le batch.
-- ---------------------------------------------------------------------

ALTER TABLE ingestion_control.publication_attestations
    ADD COLUMN IF NOT EXISTS release_id TEXT,
    ADD COLUMN IF NOT EXISTS release_manifest_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS artifacts_release_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS candidate_inventory_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS artifact_transfer_manifest_sha256 TEXT,
    ADD COLUMN IF NOT EXISTS release_batch_review_digest TEXT;

-- ---------------------------------------------------------------------
-- 2. La règle conditionnelle.
--
--    ATTENTION à la logique ternaire : une contrainte CHECK dont
--    l'expression vaut NULL est ACCEPTÉE par PostgreSQL — seul FALSE
--    rejette. Une écriture de la forme
--        (protocol_version = 'X' AND col ~ '...')
--    vaudrait donc NULL — donc accepterait — dès que `col` est NULL.
--    Chaque branche porte pour cette raison son `IS NOT NULL` explicite,
--    et la branche unitaire ses `IS NULL` explicites.
-- ---------------------------------------------------------------------

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_release_identity_by_protocol;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_release_identity_by_protocol
    CHECK (
        (
            protocol_version = 'LOT42-RELEASE-BATCH-V1'
            AND release_id IS NOT NULL
            AND btrim(release_id) <> ''
            AND release_manifest_sha256 IS NOT NULL
            AND release_manifest_sha256 ~ '^[0-9a-f]{64}$'
            AND artifacts_release_sha256 IS NOT NULL
            AND artifacts_release_sha256 ~ '^[0-9a-f]{64}$'
            AND candidate_inventory_sha256 IS NOT NULL
            AND candidate_inventory_sha256 ~ '^[0-9a-f]{64}$'
            AND artifact_transfer_manifest_sha256 IS NOT NULL
            AND artifact_transfer_manifest_sha256 ~ '^[0-9a-f]{64}$'
            AND release_batch_review_digest IS NOT NULL
            AND release_batch_review_digest ~ '^[0-9a-f]{64}$'
        )
        OR
        (
            protocol_version IN ('LOT42-V1', 'LOT42-V2')
            AND release_id IS NULL
            AND release_manifest_sha256 IS NULL
            AND artifacts_release_sha256 IS NULL
            AND candidate_inventory_sha256 IS NULL
            AND artifact_transfer_manifest_sha256 IS NULL
            AND release_batch_review_digest IS NULL
        )
    );

-- ---------------------------------------------------------------------
-- 3. Une revue batch couvre PLUSIEURS ressources. Les lignes issues d'une
--    même revue doivent donc partager la même identité de release et le
--    même digest d'artefact de revue : c'est ce qui rend la couverture
--    vérifiable, et ce qui empêche d'ajouter après coup une ressource
--    sous l'autorité d'une revue qui ne la nommait pas.
-- ---------------------------------------------------------------------

CREATE INDEX IF NOT EXISTS publication_attestations_release_batch_review_idx
    ON ingestion_control.publication_attestations (release_batch_review_digest)
    WHERE protocol_version = 'LOT42-RELEASE-BATCH-V1';

CREATE INDEX IF NOT EXISTS publication_attestations_release_idx
    ON ingestion_control.publication_attestations (release_id)
    WHERE protocol_version = 'LOT42-RELEASE-BATCH-V1';

COMMIT;
