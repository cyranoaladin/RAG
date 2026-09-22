-- Migration 018 : adoption, par une release successeur, des placements acquis
-- sous son prédécesseur (lot CV, ADR-0059 § 5).
--
-- Les lignes acquises sont liées à leur release par le `release_id` de leur
-- payload, et toute la chaîne les sélectionne ainsi. Une release successeur —
-- mêmes octets, autorités corrigées, identité neuve (ADR-0050) — ne pouvait
-- donc les couvrir qu'en réécrivant ces payloads, ou en réingérant les mêmes
-- contenus. Les deux sont refusés : le premier réécrit des faits historiques,
-- le second est une réingestion de convenance.
--
-- Une ligne d'adoption dit qu'un placement acquis est couvert par le
-- successeur, et nomme les preuves du successeur qui le fondent. Elle ne
-- modifie pas la ligne acquise. Elle est APPEND-ONLY : une correction est une
-- adoption par un NOUVEAU successeur, jamais une réécriture.
--
-- Le contrôle de transaction appartient au runner (lot CU) : ce fichier ne
-- porte ni BEGIN ni COMMIT.

CREATE TABLE IF NOT EXISTS ingestion_control.sealed_release_adoptions (
    adoption_id        UUID PRIMARY KEY,
    adoption_version   TEXT NOT NULL,

    -- Le successeur, et les preuves qui fondent l'adoption.
    release_id                          TEXT NOT NULL,
    release_manifest_sha256              TEXT NOT NULL,
    artifacts_release_sha256              TEXT NOT NULL,
    candidate_inventory_sha256             TEXT NOT NULL,
    artifact_transfer_manifest_sha256       TEXT NOT NULL,
    currentness_evidence_sha256              TEXT NOT NULL,
    pii_evidence_sha256                       TEXT NOT NULL,

    -- Le prédécesseur dont le placement a été acquis.
    predecessor_release_id                TEXT NOT NULL,
    predecessor_release_manifest_sha256    TEXT NOT NULL,

    -- Les identités ACQUISES, réutilisées telles quelles.
    resource_id   UUID NOT NULL REFERENCES ingestion_control.resources(resource_id),
    artifact_id   UUID NOT NULL REFERENCES ingestion_control.artifacts(artifact_id),
    content_sha256  TEXT NOT NULL,
    collection       TEXT NOT NULL,
    placement_id      TEXT NOT NULL,

    -- L'actualité du placement sous le successeur, dans le vocabulaire du
    -- produit. Un instantané officiel n'est jamais `current` (ADR-0059).
    currentness   TEXT NOT NULL,

    adopted_by        TEXT NOT NULL,
    adopted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    adoption_digest   TEXT NOT NULL,

    CONSTRAINT sealed_release_adoptions_version_not_blank
        CHECK (btrim(adoption_version) <> ''),
    CONSTRAINT sealed_release_adoptions_release_id_not_blank
        CHECK (btrim(release_id) <> ''),
    CONSTRAINT sealed_release_adoptions_is_a_successor
        CHECK (release_id <> predecessor_release_id),
    CONSTRAINT sealed_release_adoptions_manifest_differs
        CHECK (release_manifest_sha256 <> predecessor_release_manifest_sha256),
    CONSTRAINT sealed_release_adoptions_digests_valid
        CHECK (
            release_manifest_sha256 ~ '^[0-9a-f]{64}$'
            AND artifacts_release_sha256 ~ '^[0-9a-f]{64}$'
            AND candidate_inventory_sha256 ~ '^[0-9a-f]{64}$'
            AND artifact_transfer_manifest_sha256 ~ '^[0-9a-f]{64}$'
            AND currentness_evidence_sha256 ~ '^[0-9a-f]{64}$'
            AND pii_evidence_sha256 ~ '^[0-9a-f]{64}$'
            AND predecessor_release_manifest_sha256 ~ '^[0-9a-f]{64}$'
            AND content_sha256 ~ '^[0-9a-f]{64}$'
            AND adoption_digest ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT sealed_release_adoptions_currentness_publishable
        CHECK (currentness IN ('current', 'official_snapshot')),
    CONSTRAINT sealed_release_adoptions_actor_not_blank
        CHECK (btrim(adopted_by) <> '')
);

-- Un placement acquis n'est adopté qu'une fois par un même successeur ; un
-- rejeu identique est reconnu par son empreinte, un conflit est refusé.
CREATE UNIQUE INDEX IF NOT EXISTS sealed_release_adoptions_identity_uniq
    ON ingestion_control.sealed_release_adoptions (release_id, resource_id, artifact_id);

CREATE INDEX IF NOT EXISTS sealed_release_adoptions_release_idx
    ON ingestion_control.sealed_release_adoptions (release_id);

CREATE OR REPLACE FUNCTION ingestion_control._sealed_release_adoptions_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'sealed_release_adoptions is append-only: % is refused. A correction '
        'is an adoption by a NEW successor, never a rewrite of the recorded past.',
        TG_OP;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sealed_release_adoptions_no_update
    ON ingestion_control.sealed_release_adoptions;
CREATE TRIGGER sealed_release_adoptions_no_update
    BEFORE UPDATE OR DELETE ON ingestion_control.sealed_release_adoptions
    FOR EACH ROW EXECUTE FUNCTION
        ingestion_control._sealed_release_adoptions_append_only();
