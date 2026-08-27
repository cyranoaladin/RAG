#!/usr/bin/env bash
# Convergence d'une base pgvector existante vers le HEAD canonique 004.
#
# Complément de `register_bootstrap_migrations.sh` : ce dernier ne couvre que le
# bootstrap d'un volume neuf (`docker-entrypoint-initdb.d`, exécuté une seule
# fois par PostgreSQL). Une base déjà peuplée ne repasse jamais par initdb, donc
# rien n'y applique 003/004 ni n'y crée le registre. Ce script est le chemin de
# rattrapage.
#
# Propriétés :
#   - idempotent : chaque étape est gardée par l'état réel du catalogue ;
#   - transactionnel : une seule transaction, aucun CREATE INDEX CONCURRENTLY ;
#   - non destructif : aucune ligne de rag_chunks n'est réécrite, aucun vecteur
#     recalculé, aucun volume touché ;
#   - checksums identiques à `register_bootstrap_migrations.sh`
#     (`sha256sum <fichier> | cut -d' ' -f1`), pour que le registre produit ici
#     et celui produit au bootstrap soient indiscernables.
#
# Usage :
#   scripts/remediate-pgvector-to-head-004.sh [--dry-run]
#
# Variables (toutes surchargeables) :
#   PGVECTOR_CONTAINER  conteneur cible          (défaut : infra-pgvector-1)
#   PGVECTOR_DB         base cible               (défaut : ragdb)
#   PGVECTOR_USER       rôle propriétaire        (défaut : raguser)
#
# --dry-run rejoue la totalité de la séquence puis ROLLBACK : rien n'est écrit,
# mais toute erreur de la séquence est révélée.

set -euo pipefail

dry_run=0
case "${1:-}" in
    --dry-run) dry_run=1 ;;
    "") ;;
    *) printf 'usage: %s [--dry-run]\n' "$0" >&2; exit 2 ;;
esac

# Racines dérivées de l'emplacement du script : aucun chemin machine-local.
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
infra_dir="$(cd -- "$script_dir/.." && pwd)"
migrations_dir="$infra_dir/postgres/migrations"

container="${PGVECTOR_CONTAINER:-infra-pgvector-1}"
database="${PGVECTOR_DB:-ragdb}"
role="${PGVECTOR_USER:-raguser}"

# Chemin des migrations tel que monté DANS le conteneur (cf. docker-compose.v2.yml).
container_migrations=/docker-entrypoint-migrations

migration_001_file=001_rag_chunks_v2_schema.sql
migration_002_file=002_hybrid_retrieval.sql
migration_003_file=003_profile_filtering.sql
migration_004_file=004_artifact_placements.sql

for migration_file in \
    "$migration_001_file" \
    "$migration_002_file" \
    "$migration_003_file" \
    "$migration_004_file"; do
    test -f "$migrations_dir/$migration_file"
done

# Même méthode que register_bootstrap_migrations.sh, à la lettre.
migration_001_sha="$(sha256sum "$migrations_dir/$migration_001_file" | cut -d' ' -f1)"
migration_002_sha="$(sha256sum "$migrations_dir/$migration_002_file" | cut -d' ' -f1)"
migration_003_sha="$(sha256sum "$migrations_dir/$migration_003_file" | cut -d' ' -f1)"
migration_004_sha="$(sha256sum "$migrations_dir/$migration_004_file" | cut -d' ' -f1)"

if (( dry_run )); then
    closing_statement='ROLLBACK;'
    printf '%s\n' "MODE REPETITION : la transaction sera annulee (ROLLBACK)." >&2
else
    closing_statement='COMMIT;'
fi

docker exec -i \
    -e PGOPTIONS='--client-min-messages=warning' \
    "$container" \
    psql \
        --username "$role" \
        --dbname "$database" \
        --no-psqlrc \
        --set ON_ERROR_STOP=1 \
        --set "migrations_dir=$container_migrations" \
        --set "migration_001_file=$migration_001_file" \
        --set "migration_001_sha=$migration_001_sha" \
        --set "migration_002_file=$migration_002_file" \
        --set "migration_002_sha=$migration_002_sha" \
        --set "migration_003_file=$migration_003_file" \
        --set "migration_003_sha=$migration_003_sha" \
        --set "migration_004_file=$migration_004_file" \
        --set "migration_004_sha=$migration_004_sha" \
        --set "closing_statement=$closing_statement" \
<<'PSQL'
BEGIN;

-- Sérialise les convergences concurrentes sur le même verrou que l'outillage
-- de migration (advisory_lock_sql de pgvector_migration_state.sh).
SELECT pg_advisory_xact_lock(hashtext('nexus-rag-schema-migrations'));

-- ─────────────────────────────────────────────────────────────────────────
-- Étape A — Restaurer les DEFAULT de la migration 001.
--
-- Les bases créées par une version antérieure de `init.sql` ont rag_chunks
-- sans ces trois DEFAULT. `validate_001_sql` compare la valeur RENDUE par le
-- catalogue : c'est la seule référence qui fait foi.
-- Idempotent : SET DEFAULT sur une valeur déjà posée est un no-op.
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.rag_chunks
    ALTER COLUMN audience            SET DEFAULT '{tous}',
    ALTER COLUMN statut_enseignement SET DEFAULT 'unknown',
    ALTER COLUMN source_kind         SET DEFAULT 'unknown';

-- ─────────────────────────────────────────────────────────────────────────
-- Étape B — Retirer la colonne générée `tsv` en doublon de `text_tsv`.
--
-- Même expression génératrice exactement
-- (to_tsvector('french', COALESCE(text,''))) : aucune donnée propre n'est
-- perdue, `text_tsv` la porte déjà. Le catalogue de 001 refuse toute colonne
-- hors liste (`unexpected columns`).
-- ─────────────────────────────────────────────────────────────────────────
DROP INDEX IF EXISTS public.idx_rag_chunks_tsv;
ALTER TABLE public.rag_chunks DROP COLUMN IF EXISTS tsv;

-- ─────────────────────────────────────────────────────────────────────────
-- Étape B-bis — Retirer les CHECK ajoutés hors migrations.
--
-- Ces quatre contraintes n'existent dans aucune migration ni dans `init.sql`
-- (0 référence dans le dépôt) : posées à la main à la même époque que la
-- colonne `tsv`. `validate_001_sql` énumère les contraintes autorisées sur
-- rag_chunks et exige zéro contrainte hors liste : les conserver rend le head
-- 004 inatteignable.
--
-- Effet sur les données : nul. Aucune ligne ne les viole au moment de la
-- remédiation. `rag_chunks_vector_dims_1024` est de surcroît redondante — le
-- type `vector(1024)` refuse déjà toute autre dimension.
--
-- Les trois garanties réellement perdues (audience non vide, doc_id <>
-- chunk_id, énumération review_status) sont tracées dans la note de dette
-- comme candidates à un ADR d'évolution du contrat. Suppression nominative et
-- non dynamique : le périmètre reste auditable.
-- ─────────────────────────────────────────────────────────────────────────
ALTER TABLE public.rag_chunks
    DROP CONSTRAINT IF EXISTS rag_chunks_audience_non_empty,
    DROP CONSTRAINT IF EXISTS rag_chunks_doc_id_not_chunk_id,
    DROP CONSTRAINT IF EXISTS rag_chunks_review_status_allowed,
    DROP CONSTRAINT IF EXISTS rag_chunks_vector_dims_1024;

-- ─────────────────────────────────────────────────────────────────────────
-- Étape C — Migration 003, seulement si elle n'a jamais tourné.
-- 003 n'est pas idempotente (ADD COLUMN nu) : la garde est obligatoire.
-- ─────────────────────────────────────────────────────────────────────────
SELECT NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'rag_chunks'
      AND column_name = 'tenant'
) AS besoin_003 \gset
\if :besoin_003
\echo 'application de la migration 003'
\i :migrations_dir/003_profile_filtering.sql
\else
\echo 'migration 003 deja appliquee, ignoree'
\endif

-- ─────────────────────────────────────────────────────────────────────────
-- Étape D — Migration 004, même garde.
-- ─────────────────────────────────────────────────────────────────────────
SELECT (to_regclass('public.rag_artifacts') IS NULL) AS besoin_004 \gset
\if :besoin_004
\echo 'application de la migration 004'
\i :migrations_dir/004_artifact_placements.sql
\else
\echo 'migration 004 deja appliquee, ignoree'
\endif

-- ─────────────────────────────────────────────────────────────────────────
-- Étape E — Registre canonique `rag_schema_migrations`.
--
-- Table distincte de la table héritée `schema_migrations`, qu'aucun validateur
-- du contrat ne lit et que ce script laisse intacte.
-- Définition strictement identique à registry_schema_sql() /
-- register_bootstrap_migrations.sh : validate_registry_sql compare la
-- définition des contraintes au caractère près.
-- ─────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.rag_schema_migrations (
    version integer PRIMARY KEY CHECK (version > 0),
    file_name text NOT NULL UNIQUE CHECK (btrim(file_name) <> ''),
    sha256 text NOT NULL CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO public.rag_schema_migrations (version, file_name, sha256)
VALUES
    (1, :'migration_001_file', :'migration_001_sha'),
    (2, :'migration_002_file', :'migration_002_sha'),
    (3, :'migration_003_file', :'migration_003_sha'),
    (4, :'migration_004_file', :'migration_004_sha')
ON CONFLICT (version) DO NOTHING;

-- ─────────────────────────────────────────────────────────────────────────
-- Étape F — Refuser de valider une convergence incomplète.
-- ─────────────────────────────────────────────────────────────────────────
DO $nexus$
DECLARE
    ecart integer;
BEGIN
    SELECT count(*) INTO ecart
    FROM (VALUES (1), (2), (3), (4)) AS attendu(version)
    LEFT JOIN public.rag_schema_migrations reel USING (version)
    WHERE reel.version IS NULL;
    IF ecart <> 0 THEN
        RAISE EXCEPTION 'REMEDIATION_INCOMPLETE: registre incomplet';
    END IF;

    IF to_regclass('public.rag_artifacts') IS NULL
       OR to_regclass('public.rag_artifact_placements') IS NULL THEN
        RAISE EXCEPTION 'REMEDIATION_INCOMPLETE: tables 004 absentes';
    END IF;

    SELECT count(*) INTO ecart
    FROM pg_attribute
    WHERE attrelid = 'public.rag_chunks'::regclass
      AND attnum > 0
      AND NOT attisdropped
      AND attname = 'tsv';
    IF ecart <> 0 THEN
        RAISE EXCEPTION 'REMEDIATION_INCOMPLETE: colonne tsv toujours presente';
    END IF;

    -- Même liste d'autorisation que validate_001_sql : échouer ici donne un
    -- message utile, plutôt que de laisser le healthcheck échouer plus tard
    -- sans nommer la contrainte fautive.
    SELECT count(*) INTO ecart
    FROM pg_constraint
    WHERE conrelid = 'public.rag_chunks'::regclass
      AND NOT (
          contype = 'p'
          AND conname = 'rag_chunks_pkey'
          AND pg_get_constraintdef(oid, true) = 'PRIMARY KEY (chunk_id)'
      )
      AND conname NOT IN (
          'rag_chunks_tenant_lot41_check',
          'rag_chunks_candidat_lot41_check',
          'rag_chunks_visibility_lot41_check',
          'rag_chunks_school_year_lot41_check',
          'rag_chunks_programme_version_lot41_check',
          'rag_chunks_artifact_id_fkey',
          'rag_chunks_governed_identity_check'
      );
    IF ecart <> 0 THEN
        RAISE EXCEPTION
            'REMEDIATION_INCOMPLETE: % contrainte(s) hors contrat sur rag_chunks', ecart;
    END IF;
END
$nexus$;

:closing_statement
PSQL
