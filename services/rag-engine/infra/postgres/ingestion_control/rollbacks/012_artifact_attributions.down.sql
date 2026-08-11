-- Rollback 012 : une attribution a pu être scellée par une attestation.
-- La supprimer détruirait les quatre faits que cette attestation nomme ;
-- le rollback refuse donc toute table non vide et ne modifie aucun octet
-- dans ce cas — même discipline que le rollback 011.
--
-- ``attributed_facts_digest`` est retiré en dernier : tant que la colonne
-- existe, une attestation continue de citer un digest dont la ligne
-- source vient d'être vérifiée absente.

LOCK TABLE ingestion_control.artifact_attributions IN ACCESS EXCLUSIVE MODE;

DO $rollback$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ingestion_control.artifact_attributions LIMIT 1
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_012_ARTIFACT_ATTRIBUTIONS_PRESENT';
    END IF;
    IF EXISTS (
        SELECT 1 FROM ingestion_control.publication_attestations
        WHERE attributed_facts_digest IS NOT NULL LIMIT 1
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_012_ATTESTED_ATTRIBUTION_DIGEST_PRESENT';
    END IF;
END
$rollback$;

DROP TRIGGER IF EXISTS trg_artifact_attributions_sealed
    ON ingestion_control.artifact_attributions;
DROP TABLE ingestion_control.artifact_attributions;
DROP FUNCTION IF EXISTS ingestion_control._artifact_attributions_sealed();
DROP FUNCTION IF EXISTS ingestion_control.artifact_attribution_digest(
    UUID, TEXT, BOOLEAN, TEXT, TEXT);

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_attributed_facts_digest_valid;
ALTER TABLE ingestion_control.publication_attestations
    DROP COLUMN IF EXISTS attributed_facts_digest;
