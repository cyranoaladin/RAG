-- ---------------------------------------------------------------------
-- 014 — Stockage du protocole LOT42-RELEASE-BATCH-V1 (ADR-0056)
--
-- **Le problème.** `LOT42-V1` lie une revue humaine à UNE ressource
-- découverte à son URL : `canonical_url` y est l'identité du document, et
-- l'exiger est correct. ADR-0056 a ajouté un second protocole pour les
-- releases scellées, où cette URL canonique documentaire **n'existe pas** :
-- 315 artefacts se partagent 19 pages de provenance, et promouvoir une page
-- en identité de document affirmerait ce que personne n'a établi.
--
-- Le schéma, lui, l'exigeait encore partout. Conséquence mesurée : la
-- machine d'états est strictement séquentielle — `DISCOVERED -> NEEDS_REVIEW`
-- est refusé, il faut passer par `CANDIDATE` —, et `CANDIDATE` suppose une
-- ligne `resource_candidates`, dont `canonical_url` était `NOT NULL` avec un
-- `CHECK (btrim(...) <> '')`. Une release scellée ne pouvait donc PAS
-- atteindre `NEEDS_REVIEW` sans fabriquer une URL.
--
-- **Ce que cette migration fait, et ne fait pas.** Elle n'assouplit rien
-- globalement. Elle reprend l'idiome déjà posé par la migration 013 — une
-- contrainte CONDITIONNELLE par protocole — et l'étend à `canonical_url` :
--
--   * pour `resource_pipeline` / `LOT42-V1` / `LOT42-V2` : `canonical_url`
--     reste OBLIGATOIRE et non vide. Le comportement est identique, à la
--     ligne près ;
--   * pour `sealed_release_pipeline` / `LOT42-RELEASE-BATCH-V1` :
--     `canonical_url` doit être `NULL`. Pas « peut être » : **doit**. Une
--     valeur fabriquée y est donc refusée par la base, et pas seulement
--     déconseillée par une convention.
--
-- C'est la différence entre rendre une colonne nullable et déclarer qu'une
-- identité documentaire n'existe pas pour cette origine.
--
-- `artifacts` n'est pas touchée : elle ne porte aucun `canonical_url`. Ses
-- champs `original_url` / `final_url` sont de la PROVENANCE — d'où l'objet
-- vient —, ce qu'une `source_url` de release renseigne légitimement. Les
-- confondre avec une identité canonique serait précisément l'erreur que
-- cette migration ferme.
-- ---------------------------------------------------------------------


-- ---------------------------------------------------------------------
-- 1. L'origine de la ressource devient une donnée déclarée, pas une
--    convention implicite. Le défaut préserve tout l'existant.
-- ---------------------------------------------------------------------

ALTER TABLE ingestion_control.resources
    ADD COLUMN IF NOT EXISTS pipeline_kind TEXT NOT NULL
        DEFAULT 'resource_pipeline';

ALTER TABLE ingestion_control.resources
    DROP CONSTRAINT IF EXISTS resources_pipeline_kind_valid;

ALTER TABLE ingestion_control.resources
    ADD CONSTRAINT resources_pipeline_kind_valid
    CHECK (pipeline_kind IN ('resource_pipeline', 'sealed_release_pipeline'));

ALTER TABLE ingestion_control.resource_candidates
    ADD COLUMN IF NOT EXISTS pipeline_kind TEXT NOT NULL
        DEFAULT 'resource_pipeline';

ALTER TABLE ingestion_control.resource_candidates
    DROP CONSTRAINT IF EXISTS resource_candidates_pipeline_kind_valid;

ALTER TABLE ingestion_control.resource_candidates
    ADD CONSTRAINT resource_candidates_pipeline_kind_valid
    CHECK (pipeline_kind IN ('resource_pipeline', 'sealed_release_pipeline'));

-- ---------------------------------------------------------------------
-- 2. `resource_candidates.canonical_url` : conditionnelle, jamais permissive.
--    La colonne cesse d'être NOT NULL au niveau colonne, mais la contrainte
--    la rend OBLIGATOIRE pour `resource_pipeline` — l'ancien comportement
--    est donc intégralement conservé pour lui.
-- ---------------------------------------------------------------------

ALTER TABLE ingestion_control.resource_candidates
    ALTER COLUMN canonical_url DROP NOT NULL;

ALTER TABLE ingestion_control.resource_candidates
    DROP CONSTRAINT IF EXISTS resource_candidates_canonical_url_not_blank;

ALTER TABLE ingestion_control.resource_candidates
    DROP CONSTRAINT IF EXISTS resource_candidates_canonical_url_by_pipeline;

ALTER TABLE ingestion_control.resource_candidates
    ADD CONSTRAINT resource_candidates_canonical_url_by_pipeline
    CHECK (
        (
            pipeline_kind = 'resource_pipeline'
            AND canonical_url IS NOT NULL
            AND btrim(canonical_url) <> ''
        )
        OR
        -- Une release scellée n'a pas d'URL canonique documentaire : le
        -- schéma l'INTERDIT ici, au lieu de laisser une valeur plausible
        -- s'y installer.
        (pipeline_kind = 'sealed_release_pipeline' AND canonical_url IS NULL)
    );

-- ---------------------------------------------------------------------
-- 3. `publication_attestations` : même traitement, même idiome que 013.
-- ---------------------------------------------------------------------

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_protocol_version_valid;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_protocol_version_valid
    CHECK (protocol_version IN ('LOT42-V1', 'LOT42-V2', 'LOT42-RELEASE-BATCH-V1'));

-- Le digest d'attribution (013) reste réservé à V2 ; une attestation de
-- release scellée n'en porte pas, et ne doit pas pouvoir en porter un.
ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_attribution_digest_matches_protocol;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_attribution_digest_matches_protocol
    CHECK (
        (protocol_version = 'LOT42-V2' AND attributed_facts_digest IS NOT NULL)
        OR
        (
            protocol_version IN ('LOT42-V1', 'LOT42-RELEASE-BATCH-V1')
            AND attributed_facts_digest IS NULL
        )
    );

ALTER TABLE ingestion_control.publication_attestations
    ALTER COLUMN canonical_url DROP NOT NULL;

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_canonical_url_not_blank;

ALTER TABLE ingestion_control.publication_attestations
    DROP CONSTRAINT IF EXISTS publication_attestations_canonical_url_by_protocol;

ALTER TABLE ingestion_control.publication_attestations
    ADD CONSTRAINT publication_attestations_canonical_url_by_protocol
    CHECK (
        (
            protocol_version IN ('LOT42-V1', 'LOT42-V2')
            AND canonical_url IS NOT NULL
            AND btrim(canonical_url) <> ''
        )
        OR
        (protocol_version = 'LOT42-RELEASE-BATCH-V1' AND canonical_url IS NULL)
    );

-- ---------------------------------------------------------------------
-- 4. `publication_commit_pins` : ouverture au troisième protocole, sans
--    copie de digest — la clé étrangère vers l'attestation suffit, comme
--    la migration 013 l'a déjà établi.
-- ---------------------------------------------------------------------

ALTER TABLE ingestion_control.publication_commit_pins
    DROP CONSTRAINT IF EXISTS publication_commit_pins_publication_protocol_valid;

ALTER TABLE ingestion_control.publication_commit_pins
    ADD CONSTRAINT publication_commit_pins_publication_protocol_valid
    CHECK (
        publication_protocol_version
            IN ('LOT42-V1', 'LOT42-V2', 'LOT42-RELEASE-BATCH-V1')
    );
