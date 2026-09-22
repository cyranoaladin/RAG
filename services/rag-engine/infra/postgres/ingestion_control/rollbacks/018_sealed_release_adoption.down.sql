-- Rollback 018 : retrait de la table d'adoption.
--
-- Même discipline que 016 et 017 : le verrou précède le contrôle de vacuité,
-- l'attente est bornée, et le contrôle de transaction appartient à
-- l'APPELANT (`rollback_ingestion_control_schema.sh`, en
-- `--single-transaction`). Détruire des adoptions priverait les attestations
-- batch d'un successeur de la preuve de ce qu'elles couvrent.

SET LOCAL lock_timeout = '5s';
LOCK TABLE ingestion_control.sealed_release_adoptions IN ACCESS EXCLUSIVE MODE;

DO $$
DECLARE
    restantes BIGINT;
BEGIN
    SELECT count(*) INTO restantes
      FROM ingestion_control.sealed_release_adoptions;
    IF restantes > 0 THEN
        RAISE EXCEPTION
            'rollback 018 refused: % adoption(s) would be destroyed, and the '
            'batch attestations of their successor would lose the proof of '
            'what they cover', restantes;
    END IF;
END
$$;

DROP TRIGGER IF EXISTS sealed_release_adoptions_no_update
    ON ingestion_control.sealed_release_adoptions;
DROP FUNCTION IF EXISTS ingestion_control._sealed_release_adoptions_append_only();
DROP TABLE IF EXISTS ingestion_control.sealed_release_adoptions;
