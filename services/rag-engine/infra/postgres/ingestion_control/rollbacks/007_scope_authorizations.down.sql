-- Rollback de la migration 007 : retire ingestion_control.scope_authorizations.
-- Sûr uniquement si aucune ligne n'existe (aucune autorisation, réelle ou
-- de test, n'a jamais été enregistrée) — même discipline que 001-006.

LOCK TABLE ingestion_control.scope_authorizations IN ACCESS EXCLUSIVE MODE;

DO $nexus$
BEGIN
    IF EXISTS (SELECT 1 FROM ingestion_control.scope_authorizations) THEN
        RAISE EXCEPTION 'ROLLBACK_007_DATA_PRESENT';
    END IF;
END
$nexus$;

DROP TABLE ingestion_control.scope_authorizations;
DROP FUNCTION IF EXISTS ingestion_control._scope_authorizations_no_wildcard_domain(TEXT[]);
DROP FUNCTION IF EXISTS ingestion_control._scope_authorizations_rights_canonical(TEXT[]);
DROP FUNCTION IF EXISTS ingestion_control._scope_authorizations_domains_canonical(TEXT[]);
