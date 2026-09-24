-- Migration 019 : autorité de PUBLICATION des placements adoptés (ADR-0060).
--
-- Un placement adopté par un successeur (migration 018) conserve, dans le
-- payload acquis, l'autorisation qui a fondé son ACQUISITION. Elle dit ce qui
-- a été permis hier ; elle n'est pas réécrite. La publication par le
-- successeur exige une autorisation liée au contenu (LOT41A-V2) : cette table
-- la nomme, placement par placement, en ajout seul, à côté de l'autorité
-- d'acquisition qu'elle ne remplace pas.
--
-- Le contrôle de transaction appartient au runner (--single-transaction).

CREATE TABLE IF NOT EXISTS ingestion_control.sealed_release_publication_authorizations (
    binding_id        UUID PRIMARY KEY,
    binding_version   TEXT NOT NULL,

    release_id      TEXT NOT NULL,
    resource_id     UUID NOT NULL,
    artifact_id     UUID NOT NULL,
    content_sha256  TEXT NOT NULL,
    collection      TEXT NOT NULL,

    -- L'autorité qui a fondé l'acquisition, recopiée du payload acquis pour
    -- que la liaison se lise seule ; jamais modifiée dans le payload.
    acquisition_scope_authorization_id   TEXT NOT NULL,
    -- L'autorité de publication, liée au contenu, enregistrée et revue.
    scope_authorization_id   TEXT NOT NULL
        REFERENCES ingestion_control.scope_authorizations(authorization_id),
    scope_authorization_digest   TEXT NOT NULL,

    bound_by        TEXT NOT NULL,
    bound_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    binding_digest  TEXT NOT NULL,

    CONSTRAINT sealed_release_publication_authorizations_adopted
        FOREIGN KEY (release_id, resource_id, artifact_id)
        REFERENCES ingestion_control.sealed_release_adoptions (release_id, resource_id, artifact_id),
    CONSTRAINT sealed_release_publication_authorizations_distinct_authority
        CHECK (scope_authorization_id <> acquisition_scope_authorization_id),
    CONSTRAINT sealed_release_publication_authorizations_digests_valid
        CHECK (
            content_sha256 ~ '^[0-9a-f]{64}$'
            AND scope_authorization_digest ~ '^[0-9a-f]{64}$'
            AND binding_digest ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT sealed_release_publication_authorizations_not_blank
        CHECK (
            btrim(binding_version) <> ''
            AND btrim(release_id) <> ''
            AND btrim(collection) <> ''
            AND btrim(bound_by) <> ''
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS sealed_release_publication_authorizations_identity_uniq
    ON ingestion_control.sealed_release_publication_authorizations (release_id, resource_id, artifact_id);

CREATE INDEX IF NOT EXISTS sealed_release_publication_authorizations_release_idx
    ON ingestion_control.sealed_release_publication_authorizations (release_id);

CREATE OR REPLACE FUNCTION ingestion_control._sealed_release_publication_authorizations_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'sealed_release_publication_authorizations is append-only: % is refused. '
        'A different publication authority is a NEW successor, never a rewrite.',
        TG_OP;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sealed_release_publication_authorizations_no_update
    ON ingestion_control.sealed_release_publication_authorizations;
CREATE TRIGGER sealed_release_publication_authorizations_no_update
    BEFORE UPDATE OR DELETE ON ingestion_control.sealed_release_publication_authorizations
    FOR EACH ROW EXECUTE FUNCTION
        ingestion_control._sealed_release_publication_authorizations_append_only();
