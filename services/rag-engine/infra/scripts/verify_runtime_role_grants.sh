#!/usr/bin/env bash
# Vérifier les ACL runtime après une restauration (P0-L2, invariant de reprise).
#
# `pg_dump -Fc` d'une base ne transporte pas les rôles : ils sont globaux au
# cluster. Restaurer sur un cluster neuf produit donc une base complète mais
# **sans aucun privilège runtime** — et `pg_restore` signale ces GRANT en
# erreurs ignorées, pas en échec. Le runbook impose déjà l'ordre correct
# (`--no-privileges` puis `provision_runtime_roles.sh`) ; il manquait la
# troisième jambe, celle qui prouve que les droits sont réellement revenus.
#
# Ce vérificateur rend l'ordre incorrect **détectable** au lieu de silencieux :
#   provision cluster-global roles -> restore database -> verify grants
#
# Usage :
#   PGVECTOR_CONTAINER=... PGVECTOR_DB=... PGVECTOR_USER=... \
#     ./scripts/verify_runtime_role_grants.sh
#
# Sortie : `RUNTIME_ROLE_GRANTS=PASS` (0), ou `=FAIL` avec un motif explicite
# et un code non nul.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# shellcheck source=lib/pgvector_migration_state.sh
source "$SCRIPT_DIR/lib/pgvector_migration_state.sh"

load_deployment_environment "$INFRA_DIR/.env"

PGVECTOR_CONTAINER="${PGVECTOR_CONTAINER:-rag_pgvector}"
PGVECTOR_DB="${PGVECTOR_DB:-ragdb}"
PGVECTOR_USER="${PGVECTOR_USER:-raguser}"
RETRIEVAL_USER="${PGVECTOR_RETRIEVAL_USER:-rag_reader}"
REVIEW_USER="${PGVECTOR_REVIEW_USER:-rag_reviewer}"
PUBLISHER_USER="${PGVECTOR_PUBLISHER_USER:-rag_publisher}"

fail() {
    printf 'RUNTIME_ROLE_GRANTS=FAIL\nREASON=%s\n' "$1" >&2
    exit 1
}

if ! docker inspect --format='{{.State.Running}}' "$PGVECTOR_CONTAINER" \
    2>/dev/null | grep -qx true; then
    fail "pgvector_container_not_running"
fi

verification_sql() {
    cat <<SQL
-- NEXUS_VERIFY_RUNTIME_ROLE_GRANTS
DO \$nexus\$
DECLARE
    observed integer;
    updatable text;
BEGIN
    -- 1. Les trois rôles existent. Leur absence est la signature exacte d'une
    --    restauration effectuée avant leur provisionnement.
    SELECT count(*) INTO observed FROM pg_roles
    WHERE rolname IN ('${RETRIEVAL_USER}', '${REVIEW_USER}', '${PUBLISHER_USER}');
    IF observed <> 3 THEN
        RAISE EXCEPTION 'roles_absent_restore_ran_before_provisioning';
    END IF;

    -- 2. Aucun rôle runtime n'est administrateur.
    SELECT count(*) INTO observed FROM pg_roles
    WHERE rolname IN ('${RETRIEVAL_USER}', '${REVIEW_USER}', '${PUBLISHER_USER}')
      AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolbypassrls OR rolreplication);
    IF observed <> 0 THEN
        RAISE EXCEPTION 'runtime_role_holds_administrative_attribute';
    END IF;

    -- 3. Lecture : SELECT seul, et jamais la moindre écriture.
    SELECT count(*) INTO observed
    FROM information_schema.role_table_grants
    WHERE grantee = '${RETRIEVAL_USER}' AND table_name = 'rag_chunks'
      AND privilege_type = 'SELECT';
    IF observed <> 1 THEN
        RAISE EXCEPTION 'retrieval_role_lost_its_select_grant';
    END IF;

    SELECT count(*) INTO observed
    FROM information_schema.role_table_grants
    WHERE grantee = '${RETRIEVAL_USER}' AND privilege_type <> 'SELECT';
    IF observed <> 0 THEN
        RAISE EXCEPTION 'retrieval_role_gained_a_write_grant';
    END IF;

    -- 4. Revue : SELECT sur rag_chunks, et UPDATE sur la seule colonne de statut.
    SELECT count(*) INTO observed
    FROM information_schema.role_table_grants
    WHERE grantee = '${REVIEW_USER}' AND table_name = 'rag_chunks'
      AND privilege_type = 'SELECT';
    IF observed <> 1 THEN
        RAISE EXCEPTION 'review_role_lost_its_select_grant';
    END IF;

    SELECT coalesce(string_agg(column_name, ',' ORDER BY column_name), '<none>')
      INTO updatable
    FROM information_schema.column_privileges
    WHERE grantee = '${REVIEW_USER}' AND table_name = 'rag_chunks'
      AND privilege_type = 'UPDATE';
    IF updatable <> 'review_status' THEN
        RAISE EXCEPTION 'review_role_update_scope_is_% instead of review_status', updatable;
    END IF;

    SELECT count(*) INTO observed
    FROM information_schema.role_table_grants
    WHERE grantee = '${REVIEW_USER}'
      AND privilege_type NOT IN ('SELECT', 'UPDATE');
    IF observed <> 0 THEN
        RAISE EXCEPTION 'review_role_gained_an_unexpected_grant';
    END IF;

    -- 5. Publication : SELECT et INSERT sur les trois tables produit, rien d'autre.
    SELECT count(*) INTO observed
    FROM information_schema.role_table_grants
    WHERE grantee = '${PUBLISHER_USER}'
      AND table_name IN ('rag_chunks', 'rag_artifacts', 'rag_artifact_placements')
      AND privilege_type IN ('SELECT', 'INSERT');
    IF observed <> 6 THEN
        RAISE EXCEPTION 'publisher_role_grants_are_incomplete';
    END IF;

    SELECT count(*) INTO observed
    FROM information_schema.role_table_grants
    WHERE grantee = '${PUBLISHER_USER}'
      AND privilege_type NOT IN ('SELECT', 'INSERT');
    IF observed <> 0 THEN
        RAISE EXCEPTION 'publisher_role_gained_a_destructive_grant';
    END IF;

    -- 6. Aucun rôle runtime ne touche les relations auxiliaires.
    SELECT count(*) INTO observed
    FROM information_schema.role_table_grants
    WHERE grantee IN ('${RETRIEVAL_USER}', '${REVIEW_USER}', '${PUBLISHER_USER}')
      AND table_name IN ('rag_api_keys', 'rag_eval_runs');
    IF observed <> 0 THEN
        RAISE EXCEPTION 'runtime_role_reaches_an_auxiliary_relation';
    END IF;
END
\$nexus\$;
SQL
}

if ! output="$({ verification_sql; } | docker exec -i "$PGVECTOR_CONTAINER" \
    psql -X -q -v ON_ERROR_STOP=1 \
    -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" 2>&1)"; then
    reason="$(printf '%s' "$output" | sed -n 's/^ERROR:[[:space:]]*//p' | head -1)"
    fail "${reason:-verification_query_failed}"
fi

printf 'RUNTIME_ROLE_GRANTS=PASS\n'
printf 'VERIFIED_ROLES=%s,%s,%s\n' \
    "$RETRIEVAL_USER" "$REVIEW_USER" "$PUBLISHER_USER"
