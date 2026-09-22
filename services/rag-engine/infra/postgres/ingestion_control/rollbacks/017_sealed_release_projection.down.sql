-- Rollback 017 : retrait de la table de projection.
--
-- Même discipline que la 016 : le contrôle de vacuité et la destruction sont
-- inséparables, le verrou précède le contrôle, et l'attente est bornée.
-- Détruire des projections priverait les attestations batch de la source de
-- leurs faits.

BEGIN;

SET LOCAL lock_timeout = '5s';
LOCK TABLE ingestion_control.sealed_release_projections IN ACCESS EXCLUSIVE MODE;

DO $$
DECLARE
    restantes BIGINT;
BEGIN
    SELECT count(*) INTO restantes
      FROM ingestion_control.sealed_release_projections;
    IF restantes > 0 THEN
        RAISE EXCEPTION
            'rollback 017 refused: % projection(s) would be destroyed, and the '
            'batch attestations that derive their facts from them would lose '
            'their source', restantes;
    END IF;
END
$$;

DROP TRIGGER IF EXISTS sealed_release_projections_no_update
    ON ingestion_control.sealed_release_projections;
DROP FUNCTION IF EXISTS ingestion_control._sealed_release_projections_append_only();
DROP TABLE IF EXISTS ingestion_control.sealed_release_projections;

COMMIT;
