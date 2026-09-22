-- Migration 017 : projection append-only d'une release scellée (lot CU).
--
-- `publication_attestations` exige des faits unitaires — `quality_passed`,
-- `quality_report_digest`, `rights_status`, `gate_*`, `evidence_event_ids` —
-- que l'ingestion de release scellée n'écrit pas : ses payloads n'en portent
-- aucun, mesuré sur les 479 lignes acquises. Les fabriquer serait inventer
-- des verdicts.
--
-- La projection porte ces faits AVEC LEUR ORIGINE, et sans réécrire le passé :
--
--   FAIT_HISTORIQUE   déjà établi à l'ingestion ; on référence la preuve
--   DERIVATION        déduit MAINTENANT d'une source scellée, qui est nommée
--   EVALUATION        contrôle réellement exécuté maintenant, daté
--   NON_ETABLI        ni établi ni dérivable — bloquant, jamais comblé
--
-- Elle est APPEND-ONLY : aucune ligne n'est modifiée ni supprimée. Un rejeu
-- identique est reconnu par son empreinte ; une même identité portant
-- d'autres données est un conflit, jamais un écrasement.
--
-- Une projection consultable n'autorise rien. C'est `unresolved_conditions`
-- qui décide, et le schéma rend un objet autorisant IMPOSSIBLE à produire
-- tant qu'une condition reste inconnue.

BEGIN;

CREATE TABLE IF NOT EXISTS ingestion_control.sealed_release_projections (
    projection_id            UUID PRIMARY KEY,
    projection_version       TEXT NOT NULL,

    -- L'ensemble scellé auquel cette projection se rattache.
    release_id                       TEXT NOT NULL,
    release_manifest_sha256           TEXT NOT NULL,
    artifacts_release_sha256           TEXT NOT NULL,
    candidate_inventory_sha256          TEXT NOT NULL,
    artifact_transfer_manifest_sha256    TEXT NOT NULL,

    -- Les identités ACQUISES, réutilisées telles quelles.
    resource_id   UUID NOT NULL REFERENCES ingestion_control.resources(resource_id),
    artifact_id    UUID NOT NULL REFERENCES ingestion_control.artifacts(artifact_id),
    content_sha256  TEXT NOT NULL,
    collection       TEXT NOT NULL,
    scope_authorization_id TEXT NOT NULL,

    -- Droits : résolus par le registre gouverné, jamais déduits d'un domaine.
    rights_status           TEXT NOT NULL,
    rights_decision_id       TEXT NOT NULL,
    rights_registry_sha256    TEXT NOT NULL,
    rights_origin              TEXT NOT NULL,

    -- Qualité TECHNIQUE du batch, avec le prédicat qui la définit.
    quality_passed            BOOLEAN NOT NULL,
    quality_report_digest      TEXT NOT NULL,
    quality_predicate_version   TEXT NOT NULL,
    quality_origin               TEXT NOT NULL,

    -- Actualité et PII : deux dimensions DISTINCTES, jamais déduites l'une
    -- de l'autre ni du succès de la qualité.
    currentness          TEXT NOT NULL,
    currentness_origin    TEXT NOT NULL,
    pii_status             TEXT NOT NULL,
    pii_evidence_sha256     TEXT NOT NULL,
    pii_origin               TEXT NOT NULL,

    -- La porte de publication : une évaluation NEUVE, datée, avec son
    -- évaluateur. Jamais antidatée, jamais présentée comme une transition
    -- historique retrouvée.
    gate_passed        BOOLEAN NOT NULL,
    gate_name           TEXT NOT NULL,
    gate_evaluator       TEXT NOT NULL,
    gate_evaluated_at     TIMESTAMPTZ NOT NULL,

    -- Ce qui n'est PAS établi. Vide = rien ne bloque.
    unresolved_conditions TEXT[] NOT NULL DEFAULT '{}',

    projected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    projection_digest  TEXT NOT NULL,

    CONSTRAINT sealed_release_projections_version_not_blank
        CHECK (btrim(projection_version) <> ''),
    CONSTRAINT sealed_release_projections_release_id_not_blank
        CHECK (btrim(release_id) <> ''),
    CONSTRAINT sealed_release_projections_manifest_valid
        CHECK (release_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT sealed_release_projections_registry_valid
        CHECK (artifacts_release_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT sealed_release_projections_inventory_valid
        CHECK (candidate_inventory_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT sealed_release_projections_transfer_valid
        CHECK (artifact_transfer_manifest_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT sealed_release_projections_content_valid
        CHECK (content_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT sealed_release_projections_digest_valid
        CHECK (projection_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT sealed_release_projections_rights_registry_valid
        CHECK (rights_registry_sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT sealed_release_projections_quality_digest_valid
        CHECK (quality_report_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT sealed_release_projections_pii_evidence_valid
        CHECK (pii_evidence_sha256 ~ '^[0-9a-f]{64}$'),

    -- Les quatre origines, et elles seules. Un fait sans origine nommée
    -- serait un fait sans provenance.
    CONSTRAINT sealed_release_projections_origins_named
        CHECK (
            rights_origin      IN ('FAIT_HISTORIQUE','DERIVATION','EVALUATION','NON_ETABLI')
            AND quality_origin IN ('FAIT_HISTORIQUE','DERIVATION','EVALUATION','NON_ETABLI')
            AND currentness_origin IN ('FAIT_HISTORIQUE','DERIVATION','EVALUATION','NON_ETABLI')
            AND pii_origin     IN ('FAIT_HISTORIQUE','DERIVATION','EVALUATION','NON_ETABLI')
        ),

    -- L'invariant central : une dimension NON_ETABLIE doit apparaître dans
    -- `unresolved_conditions`. Sans cela, une projection pourrait se dire
    -- sans blocage tout en portant un fait inconnu.
    CONSTRAINT sealed_release_projections_unknowns_are_listed
        CHECK (
            (rights_origin      <> 'NON_ETABLI' OR 'rights'      = ANY(unresolved_conditions))
            AND (quality_origin <> 'NON_ETABLI' OR 'quality'     = ANY(unresolved_conditions))
            AND (currentness_origin <> 'NON_ETABLI' OR 'currentness' = ANY(unresolved_conditions))
            AND (pii_origin     <> 'NON_ETABLI' OR 'pii'         = ANY(unresolved_conditions))
        ),

    -- Une porte ne peut pas être franchie quand une condition est inconnue.
    -- C'est ce qui rend l'objet AUTORISANT impossible à produire.
    CONSTRAINT sealed_release_projections_gate_requires_no_unknown
        CHECK (gate_passed IS FALSE OR cardinality(unresolved_conditions) = 0)
);

-- Une même identité ne peut pas porter deux contenus différents : le rejeu
-- strictement identique est reconnu, le conflit est refusé.
CREATE UNIQUE INDEX IF NOT EXISTS sealed_release_projections_identity_uniq
    ON ingestion_control.sealed_release_projections
       (release_id, resource_id, artifact_id, projection_version);

CREATE INDEX IF NOT EXISTS sealed_release_projections_release_idx
    ON ingestion_control.sealed_release_projections (release_id);

-- APPEND-ONLY : la règle est portée par le schéma, pas par une convention.
CREATE OR REPLACE FUNCTION ingestion_control._sealed_release_projections_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'sealed_release_projections is append-only: % is refused. A correction '
        'is a NEW projection version, never a rewrite of the recorded past.',
        TG_OP;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS sealed_release_projections_no_update
    ON ingestion_control.sealed_release_projections;
CREATE TRIGGER sealed_release_projections_no_update
    BEFORE UPDATE OR DELETE ON ingestion_control.sealed_release_projections
    FOR EACH ROW EXECUTE FUNCTION
        ingestion_control._sealed_release_projections_append_only();

COMMIT;
