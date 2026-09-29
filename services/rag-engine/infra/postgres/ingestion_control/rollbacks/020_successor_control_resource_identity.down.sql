-- Rollback 020 : autorisé uniquement avant toute preuve V2.
-- Le runner tient une transaction unique et met schema_migrations à jour.
-- Le verrou précède la garde, sans fenêtre de course entre contrôle et ALTER.

SET LOCAL lock_timeout = '5s';
LOCK TABLE ingestion_control.sealed_release_adoptions IN ACCESS EXCLUSIVE MODE;

DO $$
DECLARE
    preuves BIGINT;
BEGIN
    SELECT count(*) INTO preuves
    FROM ingestion_control.sealed_release_adoptions
    WHERE adoption_version = 'SEALED-RELEASE-ADOPTION-V2'
       OR successor_resource_id IS NOT NULL
       OR successor_artifact_id IS NOT NULL;
    IF preuves > 0 THEN
        RAISE EXCEPTION 'rollback 020 refused: % successor adoption proof(s) exist', preuves;
    END IF;
END
$$;

DROP INDEX ingestion_control.sealed_release_adoptions_v2_identity_uniq;
DROP INDEX ingestion_control.sealed_release_adoptions_v2_artifact_uniq;
DROP INDEX ingestion_control.sealed_release_adoptions_v2_resource_uniq;

ALTER TABLE ingestion_control.sealed_release_adoptions
    DROP CONSTRAINT sealed_release_adoptions_successor_artifact_owner,
    DROP CONSTRAINT sealed_release_adoptions_predecessor_artifact_owner,
    DROP CONSTRAINT sealed_release_adoptions_version_identity_shape,
    DROP COLUMN successor_artifact_id,
    DROP COLUMN successor_resource_id;

ALTER TABLE ingestion_control.artifacts
    DROP CONSTRAINT artifacts_identity_owner_unique;
