-- Rollback 015 — fail-closed : refuse tant qu'une preuve scellée existe.
--
-- Retirer `review_evidence` d'une base qui en contient détruirait la seule
-- trace d'une revue humaine qui ne se reconstitue pas. Le rollback n'est
-- donc possible que sur une base qui n'en porte aucune.
--
-- Le verrou est pris AVANT le comptage : sans lui, une transaction
-- concurrente pourrait insérer une autorisation scellée entre le décompte
-- et le DROP, et la preuve disparaîtrait sans que rien ne l'ait détecté.

LOCK TABLE ingestion_control.scope_authorizations IN ACCESS EXCLUSIVE MODE;

DO $nexus$
DECLARE
    scellees BIGINT;
    revoquees BIGINT;
BEGIN
    SELECT count(*) INTO scellees
    FROM ingestion_control.scope_authorizations
    WHERE review_evidence IS NOT NULL;

    IF scellees > 0 THEN
        RAISE EXCEPTION 'rollback 015 refusé : % autorisation(s) portent une '
            'preuve de revue scellée — la retirer detruirait une preuve '
            'humaine qui ne se reconstitue pas', scellees;
    END IF;

    IF to_regclass('ingestion_control.revoked_review_evidence') IS NOT NULL THEN
        EXECUTE 'LOCK TABLE ingestion_control.revoked_review_evidence '
                'IN ACCESS EXCLUSIVE MODE';
        SELECT count(*) INTO revoquees FROM ingestion_control.revoked_review_evidence;
        IF revoquees > 0 THEN
            RAISE EXCEPTION 'rollback 015 refusé : % révocation(s) de preuve '
                'enregistrée(s) — les perdre ressusciterait des autorisations '
                'explicitement éteintes', revoquees;
        END IF;
    END IF;
END
$nexus$;

DROP TABLE IF EXISTS ingestion_control.revoked_review_evidence;

DROP INDEX IF EXISTS
    ingestion_control.idx_ingestion_control_scope_auth_review_evidence_digest;

ALTER TABLE ingestion_control.scope_authorizations
    DROP CONSTRAINT IF EXISTS scope_authorizations_review_evidence_protocol;

ALTER TABLE ingestion_control.scope_authorizations
    DROP CONSTRAINT IF EXISTS scope_authorizations_review_evidence_paired;

ALTER TABLE ingestion_control.scope_authorizations
    DROP COLUMN IF EXISTS review_evidence_digest;

ALTER TABLE ingestion_control.scope_authorizations
    DROP COLUMN IF EXISTS review_evidence;
