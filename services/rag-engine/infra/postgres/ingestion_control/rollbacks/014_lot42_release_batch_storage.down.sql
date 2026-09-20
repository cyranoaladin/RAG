-- Rollback 014 : retour au schéma « URL canonique obligatoire partout ».
--
-- Fail-closed, exactement comme le rollback 013. Revenir en arrière signifie
-- réimposer `canonical_url NOT NULL` sur `resource_candidates` et
-- `publication_attestations`. Si des lignes de release scellée existent —
-- elles portent délibérément `canonical_url IS NULL` —, il n'y a que trois
-- issues, et deux sont interdites :
--
--   * leur inventer une URL canonique pour satisfaire le NOT NULL : c'est
--     précisément ce qu'ADR-0056 interdit, et le rollback deviendrait le
--     chemin par lequel la fabrication entre ;
--   * les supprimer : destruction de ressources et d'attestations réelles ;
--   * refuser le rollback : seule issue honnête, retenue ici.
--
-- Le refus est levé AVANT toute modification de contrainte, et les tables
-- sont verrouillées pendant la vérification : aucune ligne de release ne
-- peut apparaître entre le contrôle et la bascule. Le rollback ne modifie
-- donc jamais un seul octet quand il refuse.
--
-- Sur une base sans donnée de release scellée, le rollback est intégral et
-- sans perte : il restaure exactement les contraintes de 008 et de 013.

BEGIN;

LOCK TABLE ingestion_control.resource_candidates IN ACCESS EXCLUSIVE MODE;
LOCK TABLE ingestion_control.resources IN ACCESS EXCLUSIVE MODE;
LOCK TABLE ingestion_control.publication_attestations IN ACCESS EXCLUSIVE MODE;

DO $$
DECLARE
    candidats  BIGINT;
    ressources BIGINT;
    attestations BIGINT;
BEGIN
    SELECT count(*) INTO candidats
    FROM ingestion_control.resource_candidates
    WHERE pipeline_kind = 'sealed_release_pipeline';

    SELECT count(*) INTO ressources
    FROM ingestion_control.resources
    WHERE pipeline_kind = 'sealed_release_pipeline';

    SELECT count(*) INTO attestations
    FROM ingestion_control.publication_attestations
    WHERE protocol_version = 'LOT42-RELEASE-BATCH-V1';

    IF candidats > 0 OR ressources > 0 OR attestations > 0 THEN
        RAISE EXCEPTION
            'rollback 014 refusé : % candidat(s), % ressource(s) et % '
            'attestation(s) de release scellée existent. Les réétiqueter ou '
            'leur inventer une canonical_url violerait ADR-0056 ; les '
            'supprimer détruirait des preuves. Aucune contrainte n''a été '
            'modifiée.',
            candidats, ressources, attestations;
    END IF;
END
$$;

-- ---------------------------------------------------------------------
-- Restauration des contraintes antérieures. Atteinte uniquement quand la
-- base ne porte aucune donnée de release scellée.
-- ---------------------------------------------------------------------

ALTER TABLE ingestion_control.publication_commit_pins
    DROP CONSTRAINT IF EXISTS publication_commit_pins_publication_protocol_valid;

ALTER TABLE ingestion_control.publication_commit_pins
    ADD CONSTRAINT publication_commit_pins_publication_protocol_valid
    CHECK (publication_protocol_version IN ('LOT42-V1', 'LOT42-V2'));

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_canonical_url_by_protocol;

ALTER TABLE ingestion_control.publication_attestations
    ALTER COLUMN canonical_url SET NOT NULL;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_canonical_url_not_blank
    CHECK (btrim(canonical_url) <> '');

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_attribution_digest_matches_protocol;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_attribution_digest_matches_protocol
    CHECK (
        (protocol_version = 'LOT42-V2' AND attributed_facts_digest IS NOT NULL)
        OR
        (protocol_version = 'LOT42-V1' AND attributed_facts_digest IS NULL)
    );

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_protocol_version_valid;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_protocol_version_valid
    CHECK (protocol_version IN ('LOT42-V1', 'LOT42-V2'));

ALTER TABLE ingestion_control.resource_candidates
    DROP CONSTRAINT IF EXISTS resource_candidates_canonical_url_by_pipeline;

ALTER TABLE ingestion_control.resource_candidates
    ALTER COLUMN canonical_url SET NOT NULL;

ALTER TABLE ingestion_control.resource_candidates
    ADD CONSTRAINT resource_candidates_canonical_url_not_blank
    CHECK (btrim(canonical_url) <> '');

ALTER TABLE ingestion_control.resource_candidates
    DROP CONSTRAINT IF EXISTS resource_candidates_pipeline_kind_valid;

ALTER TABLE ingestion_control.resource_candidates
    DROP COLUMN IF EXISTS pipeline_kind;

ALTER TABLE ingestion_control.resources
    DROP CONSTRAINT IF EXISTS resources_pipeline_kind_valid;

ALTER TABLE ingestion_control.resources
    DROP COLUMN IF EXISTS pipeline_kind;

COMMIT;
