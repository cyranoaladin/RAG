-- Migration 020 : identités de contrôle distinctes pour une adoption V2.
--
-- `resource_id` et `artifact_id` conservent exactement le sens de 018 :
-- les identités acquises du prédécesseur. V2 ajoute, sans backfill de V1,
-- les identités du successeur. Les deux couples artifact/resource sont
-- contrôlés par des clés étrangères composites déclaratives.
-- La transaction et schema_migrations appartiennent au runner canonique.

SET LOCAL lock_timeout = '5s';
LOCK TABLE ingestion_control.artifacts,
    ingestion_control.sealed_release_adoptions IN ACCESS EXCLUSIVE MODE;

-- Refuser une version historique inconnue avant de poser le nouveau contrat.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ingestion_control.sealed_release_adoptions
        WHERE adoption_version <> 'SEALED-RELEASE-ADOPTION-V1'
    ) THEN
        RAISE EXCEPTION 'migration 020 refused: unknown historical adoption version';
    END IF;
END
$$;

-- artifact_id est déjà une PK ; cette clé candidate redondante est nécessaire
-- à la FK composite qui prouve le propriétaire réel de chaque artefact.
ALTER TABLE ingestion_control.artifacts
    ADD CONSTRAINT artifacts_identity_owner_unique
    UNIQUE (artifact_id, resource_id);

ALTER TABLE ingestion_control.sealed_release_adoptions
    ADD COLUMN successor_resource_id UUID,
    ADD COLUMN successor_artifact_id UUID,
    ADD CONSTRAINT sealed_release_adoptions_version_identity_shape
    CHECK (
        (adoption_version = 'SEALED-RELEASE-ADOPTION-V1'
            AND successor_resource_id IS NULL
            AND successor_artifact_id IS NULL)
        OR
        (adoption_version = 'SEALED-RELEASE-ADOPTION-V2'
            AND successor_resource_id IS NOT NULL
            AND successor_artifact_id IS NOT NULL
            AND successor_resource_id <> resource_id
            AND successor_artifact_id <> artifact_id)
    ),
    ADD CONSTRAINT sealed_release_adoptions_predecessor_artifact_owner
    FOREIGN KEY (artifact_id, resource_id)
        REFERENCES ingestion_control.artifacts (artifact_id, resource_id),
    ADD CONSTRAINT sealed_release_adoptions_successor_artifact_owner
    FOREIGN KEY (successor_artifact_id, successor_resource_id)
        REFERENCES ingestion_control.artifacts (artifact_id, resource_id);

-- Une identité de contrôle V2 ne peut être affectée à deux adoptions,
-- même dans des releases distinctes. L'index V1 de 018 reste intact.
CREATE UNIQUE INDEX sealed_release_adoptions_v2_resource_uniq
    ON ingestion_control.sealed_release_adoptions (successor_resource_id)
    WHERE adoption_version = 'SEALED-RELEASE-ADOPTION-V2';

CREATE UNIQUE INDEX sealed_release_adoptions_v2_artifact_uniq
    ON ingestion_control.sealed_release_adoptions (successor_artifact_id)
    WHERE adoption_version = 'SEALED-RELEASE-ADOPTION-V2';

CREATE UNIQUE INDEX sealed_release_adoptions_v2_identity_uniq
    ON ingestion_control.sealed_release_adoptions
        (release_id, successor_resource_id, successor_artifact_id)
    WHERE adoption_version = 'SEALED-RELEASE-ADOPTION-V2';
