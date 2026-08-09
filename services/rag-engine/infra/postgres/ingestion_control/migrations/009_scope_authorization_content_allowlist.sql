-- Migration 009 : frontière de contenu positive pour LOT41A-V2 (ADR-0034).
--
-- Ajout strictement additif : les autorisations LOT41A-V1 existantes
-- conservent leur sémantique et leur colonne allowed_content_sha256 reste
-- NULL. LOT41A-V2 exige au contraire une liste positive, non vide et
-- canonique de SHA-256 du contenu effectivement revu.
--
-- La validation est reproduite à la frontière PostgreSQL : elle ne dépend
-- ni de Pydantic ni du chemin d'écriture opérateur. L'ordre est celui des
-- octets ASCII (collation C), identique à la sérialisation canonique.

CREATE OR REPLACE FUNCTION ingestion_control._scope_authorizations_content_allowlist_canonical(
    values_to_check TEXT[]
)
RETURNS boolean
LANGUAGE sql
IMMUTABLE
AS $func$
    SELECT COALESCE(
        array_ndims(values_to_check) = 1
        AND array_lower(values_to_check, 1) = 1
        AND cardinality(values_to_check) > 0
        AND array_position(values_to_check, NULL) IS NULL
        AND NOT EXISTS (
            SELECT 1
            FROM unnest(values_to_check) AS value(item)
            WHERE value.item !~ '^[0-9a-f]{64}$'
        )
        AND values_to_check = ARRAY(
            SELECT DISTINCT value.item COLLATE "C"
            FROM unnest(values_to_check) AS value(item)
            ORDER BY value.item COLLATE "C"
        ),
        false
    )
$func$;

LOCK TABLE ingestion_control.scope_authorizations IN ACCESS EXCLUSIVE MODE;

ALTER TABLE ingestion_control.scope_authorizations
    ADD COLUMN IF NOT EXISTS allowed_content_sha256 TEXT[];

-- La contrainte V1 historique est remplacée explicitement par le jeu fermé
-- des protocoles implémentés. Aucun préfixe/wildcard ni version inconnue.
ALTER TABLE ingestion_control.scope_authorizations
    DROP CONSTRAINT IF EXISTS scope_authorizations_protocol_version_valid;
ALTER TABLE ingestion_control.scope_authorizations
    ADD CONSTRAINT scope_authorizations_protocol_version_valid
    CHECK (protocol_version IN ('LOT41A-V1', 'LOT41A-V2'));

ALTER TABLE ingestion_control.scope_authorizations
    DROP CONSTRAINT IF EXISTS scope_authorizations_content_allowlist_by_protocol;
ALTER TABLE ingestion_control.scope_authorizations
    ADD CONSTRAINT scope_authorizations_content_allowlist_by_protocol
    CHECK (
        (
            protocol_version = 'LOT41A-V1'
            AND allowed_content_sha256 IS NULL
        )
        OR
        (
            protocol_version = 'LOT41A-V2'
            AND allowed_content_sha256 IS NOT NULL
            AND ingestion_control._scope_authorizations_content_allowlist_canonical(
                allowed_content_sha256
            )
        )
    );
