-- Rollback 010 : retire la clôture de publication sans toucher aux données.
--
-- Le verrou advisory exclusif attend la fin de tous les publishers qui
-- détiennent la variante partagée. Les ACCESS EXCLUSIVE empêchent ensuite
-- toute écriture de gouvernance de traverser la suppression des triggers.
-- Le publisher exige en outre les triggers 010 puis le pin 011 : après
-- rollback, une publication neuve refuse avant toute transaction produit.

SELECT pg_catalog.pg_advisory_xact_lock(
    pg_catalog.hashtextextended('nexus:governed-publication:schema', 0)
);

LOCK TABLE
    ingestion_control.resources,
    ingestion_control.resource_candidates,
    ingestion_control.artifacts,
    ingestion_control.workflow_events,
    ingestion_control.publication_attestations,
    ingestion_control.scope_authorizations
IN ACCESS EXCLUSIVE MODE;

DROP TRIGGER trg_governed_publication_fence_scope_authorizations
    ON ingestion_control.scope_authorizations;
DROP TRIGGER trg_governed_publication_fence_publication_attestations
    ON ingestion_control.publication_attestations;
DROP TRIGGER trg_governed_publication_fence_workflow_events
    ON ingestion_control.workflow_events;
DROP TRIGGER trg_governed_publication_fence_artifacts
    ON ingestion_control.artifacts;
DROP TRIGGER trg_governed_publication_fence_resource_candidates
    ON ingestion_control.resource_candidates;
DROP TRIGGER trg_governed_publication_fence_resources
    ON ingestion_control.resources;

DROP FUNCTION ingestion_control._governed_publication_authorization_fence();
DROP FUNCTION ingestion_control._governed_publication_resource_fence();
