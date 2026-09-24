-- Rollback 019 : retrait de la table des autorités de publication.
--
-- Même discipline que 018 : le verrou précède le contrôle de vacuité,
-- l'attente est bornée, et le contrôle de transaction appartient à
-- l'APPELANT (`rollback_ingestion_control_schema.sh`, en
-- `--single-transaction`). Détruire des liaisons priverait les attestations
-- du successeur de la preuve de l'autorité sous laquelle elles publient.

SET LOCAL lock_timeout = '5s';
LOCK TABLE ingestion_control.sealed_release_publication_authorizations IN ACCESS EXCLUSIVE MODE;

DO $$
DECLARE
    restantes BIGINT;
BEGIN
    SELECT count(*) INTO restantes
      FROM ingestion_control.sealed_release_publication_authorizations;
    IF restantes > 0 THEN
        RAISE EXCEPTION
            'rollback 019 refused: % publication authority binding(s) would be '
            'destroyed', restantes;
    END IF;
END
$$;

DROP TRIGGER IF EXISTS sealed_release_publication_authorizations_no_update
    ON ingestion_control.sealed_release_publication_authorizations;
DROP FUNCTION IF EXISTS ingestion_control._sealed_release_publication_authorizations_append_only();
DROP TABLE IF EXISTS ingestion_control.sealed_release_publication_authorizations;
