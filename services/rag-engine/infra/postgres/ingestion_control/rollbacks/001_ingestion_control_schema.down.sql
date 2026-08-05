-- Rollback de la migration 001 : retire resources puis ingestion_runs
-- (ordre inverse de leur création, resources référençant ingestion_runs).
-- Ne retire jamais le schéma ingestion_control lui-même — cohérent avec
-- 002/003 (aucun rollback existant ne retire le schéma), et cette table
-- est la fondation dont toutes les migrations ultérieures dépendent : ce
-- rollback ne doit être rejoué qu'après 002 à 006, dans l'ordre inverse.
--
-- Garde de sécurité, même motif que 002/003 : refuse si des données sont
-- présentes plutôt que de les détruire silencieusement.

DO $nexus$
BEGIN
    IF EXISTS (SELECT 1 FROM ingestion_control.resources)
       OR EXISTS (SELECT 1 FROM ingestion_control.ingestion_runs) THEN
        RAISE EXCEPTION 'ROLLBACK_001_DATA_PRESENT';
    END IF;
END
$nexus$;

DROP TABLE ingestion_control.resources;
DROP TABLE ingestion_control.ingestion_runs;
