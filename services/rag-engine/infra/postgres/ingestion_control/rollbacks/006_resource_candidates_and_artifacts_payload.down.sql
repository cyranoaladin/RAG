-- Rollback de la migration 006 : retire les colonnes payload. Sûr sans
-- condition de données : une colonne avec DEFAULT ne peut jamais bloquer
-- son propre retrait, et aucune contrainte externe ne référence payload.

ALTER TABLE ingestion_control.artifacts
    DROP COLUMN IF EXISTS payload;

ALTER TABLE ingestion_control.resource_candidates
    DROP COLUMN IF EXISTS payload;
