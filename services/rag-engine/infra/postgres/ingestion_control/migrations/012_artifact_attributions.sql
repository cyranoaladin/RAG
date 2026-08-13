-- Migration 012 : ingestion_control.artifact_attributions — LOT H2-F, défaut 6.
--
-- **Le problème résolu ici.** ``collect_publication_facts`` doit lire les
-- quatre faits d'attribution (``source_label``, ``official``,
-- ``source_kind``, ``type_doc``) *avant* la publication produit, sous le
-- rôle ``ingestion_control_attestor``. Les lire dans ``public.rag_artifacts``
-- était impossible deux fois : cette table n'existe pas encore lors d'une
-- première publication (elle est écrite par le publisher, donc après
-- l'attestation), et le rôle attestor n'a — volontairement — aucun
-- privilège sur le schéma ``public``. Les quatre faits vivent donc ici,
-- dans le plan de contrôle, écrits par le rôle applicatif à la fin du
-- pipeline gouverné, relus par l'attestor, puis recopiés (jamais
-- redécidés) par le publisher.
--
-- **Clé canonique.** ``ingestion_artifact_id`` — l'UUID de
-- ``ingestion_control.artifacts``. Jamais le ``artifact_id`` produit, qui
-- est le SHA-256 du contenu : confondre les deux était le second défaut de
-- la version précédente de ce fichier. La contrainte de clé étrangère rend
-- l'erreur irreprésentable, pas seulement improbable.
--
-- **Immuabilité après attestation.** Une attribution écrite puis attestée
-- puis modifiée publierait des valeurs que personne n'a revues. Trois
-- mécanismes se cumulent :
--   1. ``attribution_digest`` est une colonne GÉNÉRÉE — aucun rôle ne peut
--      l'écrire, donc aucun ne peut faire mentir le digest sur les quatre
--      faits qu'il résume ;
--   2. le trigger ``trg_artifact_attributions_sealed`` refuse tout UPDATE
--      qui change ce digest, et tout DELETE, dès qu'une attestation active
--      nomme cet artefact ;
--   3. l'attestation mémorise le digest (``publication_attestations
--      .attributed_facts_digest``) et ``verify_publication_attestation``
--      le recompare aux faits relus avant chaque publication.
-- Une réécriture strictement identique reste donc idempotente ; une
-- réécriture divergente après attestation est refusée par la base.
--
-- Idempotent : ``IF NOT EXISTS`` partout, sûr à rejouer.

-- Le digest canonique encode chaque champ précédé de sa longueur en
-- caractères : aucun séparateur ne peut être fabriqué depuis une valeur
-- (``a|b`` et ``a`` + ``b`` ne collisionnent jamais). ``convert_to`` est
-- STABLE parce qu'il dépend de l'encodage serveur ; la fonction ci-dessous
-- ne peut donc être déclarée IMMUTABLE qu'à la condition, vérifiée ici
-- même et refusée bruyamment sinon, que cet encodage soit UTF-8.
DO $$
BEGIN
    IF current_setting('server_encoding') <> 'UTF8' THEN
        RAISE EXCEPTION
            'INGESTION_CONTROL_ENCODING_UNSUPPORTED: server_encoding=% but the '
            'canonical attribution digest is defined over UTF-8 bytes',
            current_setting('server_encoding');
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION ingestion_control.artifact_attribution_digest(
    p_ingestion_artifact_id UUID,
    p_source_label          TEXT,
    p_official              BOOLEAN,
    p_source_kind           TEXT,
    p_type_doc              TEXT
) RETURNS TEXT
LANGUAGE sql
IMMUTABLE
STRICT
PARALLEL SAFE
AS $$
    SELECT encode(sha256(convert_to(
        'NEXUS-ATTRIBUTION-V1'
        || '|' || length(p_ingestion_artifact_id::text)::text
               || ':' || p_ingestion_artifact_id::text
        || '|' || length(p_source_label)::text || ':' || p_source_label
        || '|' || length(CASE WHEN p_official THEN 'true' ELSE 'false' END)::text
               || ':' || CASE WHEN p_official THEN 'true' ELSE 'false' END
        || '|' || length(p_source_kind)::text || ':' || p_source_kind
        || '|' || length(p_type_doc)::text || ':' || p_type_doc,
        'UTF8')), 'hex')
$$;

CREATE TABLE IF NOT EXISTS ingestion_control.artifact_attributions (
    -- Clé canonique : l'artefact d'ingestion, jamais le SHA-256 produit.
    ingestion_artifact_id UUID PRIMARY KEY
        REFERENCES ingestion_control.artifacts (artifact_id),
    resource_id           UUID NOT NULL
        REFERENCES ingestion_control.resources (resource_id),

    source_label          TEXT NOT NULL,
    official              BOOLEAN NOT NULL,
    source_kind           TEXT NOT NULL,
    type_doc              TEXT NOT NULL,

    -- Provenance de l'écriture — quel run, quel acteur, quand.
    recorded_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    recorded_by_run_id    UUID NOT NULL
        REFERENCES ingestion_control.ingestion_runs (run_id),
    recorded_by_actor     TEXT NOT NULL,

    -- Colonne générée : irrécrivable par tout rôle, y compris le rôle
    -- applicatif qui écrit les quatre faits.
    attribution_digest    TEXT GENERATED ALWAYS AS (
        ingestion_control.artifact_attribution_digest(
            ingestion_artifact_id, source_label, official, source_kind, type_doc
        )
    ) STORED,

    CONSTRAINT artifact_attributions_source_label_not_blank
        CHECK (btrim(source_label) <> '' AND length(source_label) <= 512),
    CONSTRAINT artifact_attributions_source_kind_not_blank
        CHECK (btrim(source_kind) <> '' AND length(source_kind) <= 256),
    CONSTRAINT artifact_attributions_type_doc_not_blank
        CHECK (btrim(type_doc) <> '' AND length(type_doc) <= 128),
    CONSTRAINT artifact_attributions_actor_not_blank
        CHECK (btrim(recorded_by_actor) <> ''),
    CONSTRAINT artifact_attributions_digest_valid
        CHECK (attribution_digest ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_artifact_attributions_run_id
    ON ingestion_control.artifact_attributions (recorded_by_run_id);
CREATE INDEX IF NOT EXISTS idx_artifact_attributions_resource_id
    ON ingestion_control.artifact_attributions (resource_id);

-- Le publisher relit les faits attestés ; l'attestation doit donc pouvoir
-- nommer le digest exact des quatre faits qu'elle scelle. Colonne ajoutée
-- nullable pour rester applicable à un schéma déjà peuplé — une
-- attestation sans digest est refusée à la relecture (fail-closed côté
-- vérificateur), jamais publiée « par défaut ».
ALTER TABLE ingestion_control.publication_attestations
    ADD COLUMN IF NOT EXISTS attributed_facts_digest TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'publication_attestations_attributed_facts_digest_valid'
    ) THEN
        ALTER TABLE ingestion_control.publication_attestations
            ADD CONSTRAINT publication_attestations_attributed_facts_digest_valid
            CHECK (
                attributed_facts_digest IS NULL
                OR attributed_facts_digest ~ '^[0-9a-f]{64}$'
            );
    END IF;
END
$$;

-- Scellement après attestation. Déclenché APRÈS l'écriture : la valeur
-- générée ``attribution_digest`` n'est calculée qu'à ce moment (elle est
-- NULL dans un trigger BEFORE — comportement documenté de PostgreSQL),
-- donc un trigger BEFORE ne pourrait pas comparer les digests. Une
-- exception levée ici annule la transaction exactement de la même façon.
CREATE OR REPLACE FUNCTION ingestion_control._artifact_attributions_sealed()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    v_artifact UUID;
BEGIN
    v_artifact := OLD.ingestion_artifact_id;
    IF TG_OP = 'DELETE' THEN
        IF EXISTS (
            SELECT 1 FROM ingestion_control.publication_attestations
            WHERE artifact_id = v_artifact AND invalidated_at IS NULL
        ) THEN
            RAISE EXCEPTION
                'ATTRIBUTION_SEALED_BY_ATTESTATION: attribution of ingestion '
                'artifact % is attested and can never be deleted', v_artifact;
        END IF;
        RETURN OLD;
    END IF;

    IF NEW.ingestion_artifact_id <> OLD.ingestion_artifact_id THEN
        RAISE EXCEPTION
            'ATTRIBUTION_KEY_IMMUTABLE: ingestion_artifact_id cannot be '
            'reassigned (% -> %)', OLD.ingestion_artifact_id,
            NEW.ingestion_artifact_id;
    END IF;

    -- Une réécriture strictement identique est idempotente : seul un
    -- changement réel des quatre faits est confronté au scellement.
    IF NEW.attribution_digest IS DISTINCT FROM OLD.attribution_digest
       AND EXISTS (
           SELECT 1 FROM ingestion_control.publication_attestations
           WHERE artifact_id = v_artifact AND invalidated_at IS NULL
       ) THEN
        RAISE EXCEPTION
            'ATTRIBUTION_SEALED_BY_ATTESTATION: attribution of ingestion '
            'artifact % is attested (digest %) and can never be changed to %',
            v_artifact, OLD.attribution_digest, NEW.attribution_digest;
    END IF;
    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_artifact_attributions_sealed
    ON ingestion_control.artifact_attributions;
CREATE TRIGGER trg_artifact_attributions_sealed
    AFTER UPDATE OR DELETE ON ingestion_control.artifact_attributions
    FOR EACH ROW
    EXECUTE FUNCTION ingestion_control._artifact_attributions_sealed();

-- Privilèges. Le fichier canonique des GRANT reste
-- infra/scripts/provision_ingestion_control_roles.sh (même discipline que
-- toutes les autres tables de ce schéma) ; ceux-ci le doublent pour qu'une
-- migration appliquée sur une base déjà provisionnée soit immédiatement
-- utilisable, et pour qu'aucune fenêtre n'existe où la table serait
-- lisible par PUBLIC.
REVOKE ALL PRIVILEGES ON ingestion_control.artifact_attributions FROM PUBLIC;
REVOKE ALL PRIVILEGES
    ON FUNCTION ingestion_control.artifact_attribution_digest(
        UUID, TEXT, BOOLEAN, TEXT, TEXT) FROM PUBLIC;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ingestion_control_attestor') THEN
        -- Lecture seule : l'attestor relit les faits, ne les produit jamais.
        GRANT SELECT ON ingestion_control.artifact_attributions
            TO ingestion_control_attestor;
        GRANT EXECUTE ON FUNCTION ingestion_control.artifact_attribution_digest(
            UUID, TEXT, BOOLEAN, TEXT, TEXT) TO ingestion_control_attestor;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON ingestion_control.artifact_attributions
            FROM ingestion_control_attestor;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ingestion_control_app') THEN
        -- Écriture minimale : INSERT et UPDATE (correction avant
        -- attestation, idempotence après). Jamais DELETE : une attribution
        -- écrite ne disparaît pas.
        GRANT SELECT, INSERT, UPDATE ON ingestion_control.artifact_attributions
            TO ingestion_control_app;
        GRANT EXECUTE ON FUNCTION ingestion_control.artifact_attribution_digest(
            UUID, TEXT, BOOLEAN, TEXT, TEXT) TO ingestion_control_app;
        REVOKE DELETE, TRUNCATE ON ingestion_control.artifact_attributions
            FROM ingestion_control_app;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ingestion_control_authority') THEN
        REVOKE ALL PRIVILEGES ON ingestion_control.artifact_attributions
            FROM ingestion_control_authority;
    END IF;
END
$$;
