-- Rollback de la migration 001 : retire resources puis ingestion_runs
-- (ordre inverse de leur création, resources référençant ingestion_runs).
-- Ne retire jamais le schéma ingestion_control lui-même — cohérent avec
-- 002/003 (aucun rollback existant ne retire le schéma), et cette table
-- est la fondation dont toutes les migrations ultérieures dépendent : ce
-- rollback ne doit être rejoué qu'après 002 à 006, dans l'ordre inverse.
--
-- Garde de sécurité, même motif que 002/003 : refuse si des données sont
-- présentes plutôt que de les détruire silencieusement.
--
-- Remédiation revue PR#90 (Cubic P1) : LOCK TABLE ... ACCESS EXCLUSIVE
-- avant la vérification, dans la même transaction que le DROP qui suit —
-- sans ce verrou, une transaction concurrente pouvait valider un INSERT
-- entre la vérification (aucune donnée présente) et le DROP, perdant
-- silencieusement une écriture pourtant validée par PostgreSQL. Le verrou
-- bloque tout INSERT/UPDATE/DELETE/SELECT concurrent sur ces deux tables
-- jusqu'à la fin de cette transaction (commit du DROP ou rollback sur
-- RAISE EXCEPTION) — jamais un simple contrôle de vacuité sans garantie.

LOCK TABLE ingestion_control.resources, ingestion_control.ingestion_runs
    IN ACCESS EXCLUSIVE MODE;

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
