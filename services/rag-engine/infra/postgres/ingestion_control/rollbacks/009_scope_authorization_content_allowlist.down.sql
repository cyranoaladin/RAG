-- Rollback de la migration 009 : retour au protocole LOT41A-V1 seul.
--
-- Un rollback en présence d'une décision V2 supprimerait silencieusement
-- sa frontière positive de contenu. Il est donc refusé sous verrou ;
-- l'opérateur doit d'abord révoquer et retirer explicitement ces décisions.

LOCK TABLE ingestion_control.scope_authorizations IN ACCESS EXCLUSIVE MODE;

DO $nexus$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM ingestion_control.scope_authorizations
        WHERE protocol_version = 'LOT41A-V2'
    ) THEN
        RAISE EXCEPTION 'ROLLBACK_009_V2_DATA_PRESENT';
    END IF;
END
$nexus$;

ALTER TABLE ingestion_control.scope_authorizations
    DROP CONSTRAINT scope_authorizations_content_allowlist_by_protocol;
ALTER TABLE ingestion_control.scope_authorizations
    DROP CONSTRAINT scope_authorizations_protocol_version_valid;
ALTER TABLE ingestion_control.scope_authorizations
    ADD CONSTRAINT scope_authorizations_protocol_version_valid
    CHECK (protocol_version = 'LOT41A-V1');
ALTER TABLE ingestion_control.scope_authorizations
    DROP COLUMN allowed_content_sha256;

DROP FUNCTION ingestion_control._scope_authorizations_content_allowlist_canonical(TEXT[]);
