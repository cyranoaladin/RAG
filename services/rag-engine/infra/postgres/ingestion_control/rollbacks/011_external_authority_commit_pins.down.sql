-- Rollback 011 : un pin a déjà autorisé un commit produit potentiel.
-- Le supprimer détruirait la preuve de linéarisation ; le rollback refuse
-- donc toute table non vide et ne modifie aucun octet dans ce cas.

LOCK TABLE ingestion_control.publication_commit_pins IN ACCESS EXCLUSIVE MODE;

DO $rollback$
BEGIN
    IF EXISTS (
        SELECT 1 FROM ingestion_control.publication_commit_pins LIMIT 1
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_011_PUBLICATION_COMMIT_PINS_PRESENT';
    END IF;
END
$rollback$;

DROP TABLE ingestion_control.publication_commit_pins;
