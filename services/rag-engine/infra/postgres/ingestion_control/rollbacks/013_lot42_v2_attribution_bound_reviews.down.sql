-- Rollback 013 : retour au schéma « LOT42-V1 seulement ».
--
-- Fail-closed. Revenir en arrière signifie réimposer un CHECK qui refuse
-- ``LOT42-V2``. Si des lignes V2 existent déjà, il n'y a que trois issues
-- possibles, et deux sont interdites :
--   * supprimer ces lignes — destruction de preuve d'attestation ;
--   * les réétiqueter en V1 — mensonge : elles ont été revues comme V2, et
--     leur digest d'attribution deviendrait invalide au regard du CHECK
--     V1 ;
--   * refuser le rollback — seule issue honnête, retenue ici.
--
-- Le refus est levé *avant* toute modification de contrainte, et la table
-- est verrouillée pendant la vérification : aucune ligne V2 ne peut
-- apparaître entre le contrôle et la bascule des contraintes. Le rollback
-- ne modifie donc jamais un seul octet quand il refuse.
--
-- Sur une base sans donnée V2, le rollback est intégral et sans perte : il
-- restaure exactement les contraintes de 008 et 011.

LOCK TABLE ingestion_control.publication_attestations IN ACCESS EXCLUSIVE MODE;
LOCK TABLE ingestion_control.publication_commit_pins IN ACCESS EXCLUSIVE MODE;

DO $rollback$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ingestion_control.publication_attestations
        WHERE protocol_version = 'LOT42-V2' LIMIT 1
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_013_LOT42_V2_ATTESTATIONS_PRESENT';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ingestion_control.publication_commit_pins
        WHERE publication_protocol_version = 'LOT42-V2' LIMIT 1
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_013_LOT42_V2_COMMIT_PINS_PRESENT';
    END IF;
END
$rollback$;

-- Aucune ligne V2 : les contraintes 008/011 d'origine sont restaurables
-- telles quelles.
ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_attribution_digest_matches_protocol;

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_protocol_version_valid;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_protocol_version_valid
    CHECK (protocol_version = 'LOT42-V1');

ALTER TABLE ingestion_control.publication_commit_pins
    DROP CONSTRAINT IF EXISTS publication_commit_pins_publication_protocol_valid;

ALTER TABLE ingestion_control.publication_commit_pins
    ADD CONSTRAINT publication_commit_pins_publication_protocol_valid
    CHECK (publication_protocol_version = 'LOT42-V1');
