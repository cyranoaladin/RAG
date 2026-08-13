-- Migration 010 : clôture transactionnelle du commit de publication.
--
-- Le publisher produit utilise une connexion distincte de la base de
-- contrôle. Une dernière relecture LOT42, seule, laisse donc une fenêtre :
-- une révocation peut committer après cette relecture mais avant le commit
-- produit. Les triggers ci-dessous prennent le même verrou advisory par
-- ressource/autorisation que le publisher. Celui-ci conserve ces verrous
-- dans une transaction control qui englobe le commit produit :
--
--     gouvernance valide + verrous control
--       -> transaction produit -> COMMIT produit
--       -> libération des verrous control
--       -> révocation concurrente autorisée à committer
--
-- Les fonctions sont SECURITY INVOKER : aucun privilège n'est élevé et
-- aucun nouveau writer n'est exposé. Un hash advisory collisionnel ne peut
-- que sur-sérialiser deux ressources ; il ne peut jamais supprimer un
-- verrou requis, car un même identifiant produit toujours la même clé.

CREATE OR REPLACE FUNCTION ingestion_control._governed_publication_resource_fence()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $fence$
DECLARE
    fenced_id UUID;
BEGIN
    FOR fenced_id IN
        SELECT DISTINCT candidate_id
        FROM unnest(
            ARRAY[
                CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN OLD.resource_id END,
                CASE WHEN TG_OP IN ('UPDATE', 'INSERT') THEN NEW.resource_id END
            ]::UUID[]
        ) AS ids(candidate_id)
        WHERE candidate_id IS NOT NULL
        ORDER BY candidate_id
    LOOP
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(
                'nexus:governed-publication:resource:' || fenced_id::TEXT,
                0
            )
        );
    END LOOP;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$fence$;

CREATE OR REPLACE FUNCTION ingestion_control._governed_publication_authorization_fence()
RETURNS trigger
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = pg_catalog
AS $fence$
DECLARE
    fenced_id TEXT;
BEGIN
    FOR fenced_id IN
        SELECT DISTINCT candidate_id COLLATE "C"
        FROM unnest(
            ARRAY[
                CASE WHEN TG_OP IN ('UPDATE', 'DELETE') THEN OLD.authorization_id END,
                CASE WHEN TG_OP IN ('UPDATE', 'INSERT') THEN NEW.authorization_id END
            ]::TEXT[]
        ) AS ids(candidate_id)
        WHERE candidate_id IS NOT NULL
        ORDER BY candidate_id COLLATE "C"
    LOOP
        PERFORM pg_catalog.pg_advisory_xact_lock(
            pg_catalog.hashtextextended(
                'nexus:governed-publication:authorization:' || fenced_id,
                0
            )
        );
    END LOOP;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END
$fence$;

DROP TRIGGER IF EXISTS trg_governed_publication_fence_resources
    ON ingestion_control.resources;
CREATE TRIGGER trg_governed_publication_fence_resources
BEFORE INSERT OR UPDATE OR DELETE ON ingestion_control.resources
FOR EACH ROW EXECUTE FUNCTION
    ingestion_control._governed_publication_resource_fence();

DROP TRIGGER IF EXISTS trg_governed_publication_fence_resource_candidates
    ON ingestion_control.resource_candidates;
CREATE TRIGGER trg_governed_publication_fence_resource_candidates
BEFORE INSERT OR UPDATE OR DELETE ON ingestion_control.resource_candidates
FOR EACH ROW EXECUTE FUNCTION
    ingestion_control._governed_publication_resource_fence();

DROP TRIGGER IF EXISTS trg_governed_publication_fence_artifacts
    ON ingestion_control.artifacts;
CREATE TRIGGER trg_governed_publication_fence_artifacts
BEFORE INSERT OR UPDATE OR DELETE ON ingestion_control.artifacts
FOR EACH ROW EXECUTE FUNCTION
    ingestion_control._governed_publication_resource_fence();

DROP TRIGGER IF EXISTS trg_governed_publication_fence_workflow_events
    ON ingestion_control.workflow_events;
CREATE TRIGGER trg_governed_publication_fence_workflow_events
BEFORE INSERT OR UPDATE OR DELETE ON ingestion_control.workflow_events
FOR EACH ROW EXECUTE FUNCTION
    ingestion_control._governed_publication_resource_fence();

DROP TRIGGER IF EXISTS trg_governed_publication_fence_publication_attestations
    ON ingestion_control.publication_attestations;
CREATE TRIGGER trg_governed_publication_fence_publication_attestations
BEFORE INSERT OR UPDATE OR DELETE ON ingestion_control.publication_attestations
FOR EACH ROW EXECUTE FUNCTION
    ingestion_control._governed_publication_resource_fence();

DROP TRIGGER IF EXISTS trg_governed_publication_fence_scope_authorizations
    ON ingestion_control.scope_authorizations;
CREATE TRIGGER trg_governed_publication_fence_scope_authorizations
BEFORE INSERT OR UPDATE OR DELETE ON ingestion_control.scope_authorizations
FOR EACH ROW EXECUTE FUNCTION
    ingestion_control._governed_publication_authorization_fence();
