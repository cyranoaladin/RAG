-- Rollback 016 : retrait de l'identité de release des attestations.
--
-- Ce rollback DÉTRUIT l'identité de release des attestations batch : elles
-- deviendraient invérifiables plutôt qu'invalides, ce qui est pire. Il n'est
-- donc applicable que sur une base ne portant AUCUNE ligne batch, et refuse
-- sinon — un rollback qui laisse des lignes sans leur autorité n'est pas un
-- retour en arrière, c'est une perte.

BEGIN;

DO $$
DECLARE
    restantes BIGINT;
BEGIN
    SELECT count(*) INTO restantes
      FROM ingestion_control.publication_attestations
     WHERE protocol_version = 'LOT42-RELEASE-BATCH-V1';
    IF restantes > 0 THEN
        RAISE EXCEPTION
            'rollback 016 refused: % batch attestation(s) would lose their '
            'release identity and become unverifiable', restantes;
    END IF;
END
$$;

DROP INDEX IF EXISTS ingestion_control.publication_attestations_release_batch_review_idx;
DROP INDEX IF EXISTS ingestion_control.publication_attestations_release_idx;

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_release_identity_by_protocol;

ALTER TABLE ingestion_control.publication_attestations
    DROP COLUMN IF EXISTS release_batch_review_digest,
    DROP COLUMN IF EXISTS artifact_transfer_manifest_sha256,
    DROP COLUMN IF EXISTS candidate_inventory_sha256,
    DROP COLUMN IF EXISTS artifacts_release_sha256,
    DROP COLUMN IF EXISTS release_manifest_sha256,
    DROP COLUMN IF EXISTS release_id;

COMMIT;
