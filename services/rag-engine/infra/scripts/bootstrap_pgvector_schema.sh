#!/usr/bin/env bash
# Bootstrap/catch-up automatique du schéma pgvector (LOT43).
#
# Contrairement à apply_pgvector_migrations.sh (outil opérateur avec backup
# pg_dump + docker cp, pensé pour une upgrade "day 2" d'une base de
# production contenant des données réelles), ce script est pensé pour être
# invoqué automatiquement à chaque démarrage (docker compose up), y compris
# sur un volume PostgreSQL vierge :
#   - aucune dépendance à `docker exec`/`docker cp` : connexion directe via
#     psql et les variables d'environnement libpq standard (PGHOST, PGPORT,
#     PGUSER, PGPASSWORD, PGDATABASE) ;
#   - aucune sauvegarde pg_dump : les migrations appliquées sont additives et
#     non destructrices par construction (cf. commentaires des fichiers
#     001/002/003 et la règle NOT VALID/VALIDATE CONSTRAINT de 003), et un
#     volume vierge n'a de toute façon rien à sauvegarder.
#   - réutilise intégralement la bibliothèque de découverte de manifeste et
#     de validation SQL déjà utilisée par l'outil opérateur
#     (lib/pgvector_migration_state.sh), pour ne jamais diverger sur ce qui
#     compte comme "schéma valide".
#
# Pour une upgrade de production avec des données réelles et une garantie de
# rollback, utiliser apply_pgvector_migrations.sh, pas ce script.
#
# Usage : PGHOST=pgvector PGPORT=5432 PGUSER=raguser PGPASSWORD=... \
#         PGDATABASE=ragdb ./scripts/bootstrap_pgvector_schema.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATIONS_DIR="$INFRA_DIR/postgres/migrations"
MIGRATION_HEAD_FILE="$MIGRATIONS_DIR/HEAD"

: "${PGHOST:?PGHOST must be set (host of the pgvector service)}"
: "${PGDATABASE:?PGDATABASE must be set}"
: "${PGUSER:?PGUSER must be set}"

# shellcheck source=lib/pgvector_migration_state.sh
source "$SCRIPT_DIR/lib/pgvector_migration_state.sh"

discover_manifest "$MIGRATIONS_DIR" "$MIGRATION_HEAD_FILE"

CONNECT_RETRIES="${BOOTSTRAP_CONNECT_RETRIES:-30}"
CONNECT_DELAY_SECONDS="${BOOTSTRAP_CONNECT_DELAY_SECONDS:-1}"

wait_for_connection() {
    local attempt
    for ((attempt = 1; attempt <= CONNECT_RETRIES; attempt++)); do
        if psql -X -q -A -t -v ON_ERROR_STOP=1 -c 'SELECT 1;' >/dev/null 2>&1; then
            return 0
        fi
        sleep "$CONNECT_DELAY_SECONDS"
    done
    echo "FATAL: cannot reach PostgreSQL at $PGHOST:${PGPORT:-5432} after $CONNECT_RETRIES attempts" >&2
    return 1
}

read_database_state() {
    local state_output line kind first second third extra

    APPLIED_VERSIONS=()
    APPLIED_NAMES=()
    APPLIED_SHA256=()
    REGISTRY_PRESENT=""
    RAG_CHUNKS_PRESENT=""
    UNREGISTERED_SCHEMA_HEAD=0
    state_output="$({ read_migration_state_sql; } | psql -X -q -A -t -v ON_ERROR_STOP=1)"

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        IFS='|' read -r kind first second third extra <<< "$line"
        case "$kind" in
            REGISTRY_PRESENT)
                [[ -z "${second:-}${third:-}${extra:-}" ]] \
                    || { echo "MIGRATION_STATE_OUTPUT_INVALID" >&2; return 1; }
                REGISTRY_PRESENT="$first"
                ;;
            RAG_CHUNKS_PRESENT)
                [[ -z "${second:-}${third:-}${extra:-}" ]] \
                    || { echo "MIGRATION_STATE_OUTPUT_INVALID" >&2; return 1; }
                RAG_CHUNKS_PRESENT="$first"
                ;;
            MIGRATION)
                [[ -n "$first" && -n "$second" && -n "$third" && -z "${extra:-}" ]] \
                    || { echo "MIGRATION_STATE_OUTPUT_INVALID" >&2; return 1; }
                APPLIED_VERSIONS+=("$first")
                APPLIED_NAMES+=("$second")
                APPLIED_SHA256+=("$third")
                ;;
            *)
                echo "MIGRATION_STATE_OUTPUT_INVALID" >&2
                return 1
                ;;
        esac
    done <<< "$state_output"

    [[ "$REGISTRY_PRESENT" =~ ^[01]$ \
       && "$RAG_CHUNKS_PRESENT" =~ ^[01]$ ]] \
        || { echo "MIGRATION_STATE_OUTPUT_INVALID" >&2; return 1; }
    validate_registry_state "$REGISTRY_PRESENT"

    if [[ "$REGISTRY_PRESENT" == "0" && "$RAG_CHUNKS_PRESENT" == "1" ]]; then
        read_unregistered_schema_head
    fi
}

read_unregistered_schema_head() {
    local state_output line kind first second extra

    HYBRID_COLUMN_PRESENT=""
    HYBRID_INDEX_PRESENT=""
    state_output="$({ read_unregistered_hybrid_state_sql; } | psql -X -q -A -t -v ON_ERROR_STOP=1)"

    while IFS= read -r line; do
        [[ -z "$line" ]] && continue
        IFS='|' read -r kind first second extra <<< "$line"
        [[ -z "${second:-}${extra:-}" ]] \
            || { echo "MIGRATION_STATE_OUTPUT_INVALID" >&2; return 1; }
        case "$kind" in
            HYBRID_COLUMN_PRESENT)
                HYBRID_COLUMN_PRESENT="$first"
                ;;
            HYBRID_INDEX_PRESENT)
                HYBRID_INDEX_PRESENT="$first"
                ;;
            *)
                echo "MIGRATION_STATE_OUTPUT_INVALID" >&2
                return 1
                ;;
        esac
    done <<< "$state_output"

    [[ "$HYBRID_COLUMN_PRESENT" =~ ^[01]$ \
       && "$HYBRID_INDEX_PRESENT" =~ ^[01]$ ]] \
        || { echo "MIGRATION_STATE_OUTPUT_INVALID" >&2; return 1; }

    if [[ "$HYBRID_COLUMN_PRESENT" == "0" \
       && "$HYBRID_INDEX_PRESENT" == "0" ]]; then
        UNREGISTERED_SCHEMA_HEAD=1
    elif [[ "$HYBRID_COLUMN_PRESENT" == "1" \
         && "$HYBRID_INDEX_PRESENT" == "1" ]]; then
        UNREGISTERED_SCHEMA_HEAD=2
    else
        echo "UNREGISTERED_SCHEMA_HYBRID_OBJECTS_MISMATCH" >&2
        return 1
    fi
}

run_readonly_preflight_validation() {
    if [[ "$REGISTRY_PRESENT" == "1" ]]; then
        {
            validate_001_sql
            if (( EFFECTIVE_HEAD >= 2 )); then
                validate_002_sql
            else
                validate_002_absent_sql
            fi
            if (( EFFECTIVE_HEAD >= 3 )); then
                validate_003_sql
            else
                validate_003_absent_sql
            fi
            validate_registry_sql "$EFFECTIVE_HEAD"
        } | psql -X -q -v ON_ERROR_STOP=1 >/dev/null
    elif [[ "$RAG_CHUNKS_PRESENT" == "1" ]]; then
        {
            validate_001_sql
            if (( UNREGISTERED_SCHEMA_HEAD == 2 )); then
                validate_002_sql
            else
                validate_002_absent_sql
            fi
            validate_003_absent_sql
        } | psql -X -q -v ON_ERROR_STOP=1 >/dev/null
    fi
}

run_adoption_transition() {
    local adopted_head="$1"
    local version variable_prefix
    local -a psql_variables=()

    if (( adopted_head < 1 || adopted_head > ${#MIGRATION_VERSIONS[@]} )); then
        echo "UNREGISTERED_SCHEMA_HEAD_INVALID" >&2
        return 1
    fi

    for ((version = 1; version <= adopted_head; version++)); do
        variable_prefix="migration_$(printf '%03d' "$version")"
        psql_variables+=(
            -v "${variable_prefix}_file=${MIGRATION_NAMES[$((version - 1))]}"
            -v "${variable_prefix}_sha=${MIGRATION_SHA256[$((version - 1))]}"
        )
    done

    {
        advisory_lock_sql
        printf '%s\n' "-- NEXUS_ADOPT_SCHEMA_HEAD_$(printf '%03d' "$adopted_head")"
        registry_schema_sql
        validate_001_sql
        if (( adopted_head >= 2 )); then
            validate_002_sql
        else
            validate_002_absent_sql
        fi
        validate_003_absent_sql
        for ((version = 1; version <= adopted_head; version++)); do
            variable_prefix="migration_$(printf '%03d' "$version")"
            printf '%s\n' \
                "INSERT INTO rag_schema_migrations (version, file_name, sha256)" \
                "VALUES ($version, :'${variable_prefix}_file', :'${variable_prefix}_sha');"
        done
        validate_001_sql
        if (( adopted_head >= 2 )); then
            validate_002_sql
        else
            validate_002_absent_sql
        fi
        validate_003_absent_sql
        validate_registry_sql "$adopted_head"
    } | psql -X -q --single-transaction \
        -v ON_ERROR_STOP=1 \
        "${psql_variables[@]}" >/dev/null
}

run_up_transition() {
    local version="$1"
    local index=$((version - 1))
    local migration_file="${MIGRATION_FILES[$index]}"
    local migration_name="${MIGRATION_NAMES[$index]}"
    local migration_sha="${MIGRATION_SHA256[$index]}"

    {
        advisory_lock_sql
        if (( version == 1 )); then
            registry_schema_sql
        fi
        command cat "$migration_file"
        printf '\n'
        cat <<'SQL'
INSERT INTO rag_schema_migrations (version, file_name, sha256)
VALUES (:'migration_version'::integer, :'migration_file', :'migration_sha');
SQL
        validate_001_sql
        if (( version >= 2 )); then
            validate_002_sql
        else
            validate_002_absent_sql
        fi
        if (( version >= 3 )); then
            validate_003_sql
        else
            validate_003_absent_sql
        fi
        validate_registry_sql "$version"
    } | psql -X -q --single-transaction \
        -v ON_ERROR_STOP=1 \
        -v "migration_version=$version" \
        -v "migration_file=$migration_name" \
        -v "migration_sha=$migration_sha" >/dev/null
}

wait_for_connection
read_database_state
run_readonly_preflight_validation

declared_head="${#MIGRATION_VERSIONS[@]}"
if [[ "$REGISTRY_PRESENT" == "1" ]] && (( EFFECTIVE_HEAD == declared_head )); then
    echo "MIGRATIONS_APPLIED=0"
    echo "MIGRATIONS_ADOPTED=0"
    echo "SCHEMA_VERIFICATION=OK"
    echo "BOOTSTRAP_COMPLETE"
    echo "SCHEMA_HEAD=$declared_head"
    exit 0
fi

applied_count=0
adopted_count=0
if (( UNREGISTERED_SCHEMA_HEAD > 0 )); then
    run_adoption_transition "$UNREGISTERED_SCHEMA_HEAD"
    EFFECTIVE_HEAD="$UNREGISTERED_SCHEMA_HEAD"
    adopted_count="$UNREGISTERED_SCHEMA_HEAD"
fi

for ((version = EFFECTIVE_HEAD + 1; version <= declared_head; version++)); do
    run_up_transition "$version"
    applied_count=$((applied_count + 1))
done

# Revalidate from scratch: never trust our own bookkeeping as proof.
read_database_state
if [[ "$REGISTRY_PRESENT" != "1" ]] || (( EFFECTIVE_HEAD != declared_head )); then
    echo "FATAL: schema head after bootstrap ($EFFECTIVE_HEAD) does not match declared head ($declared_head)" >&2
    exit 1
fi

echo "MIGRATIONS_APPLIED=$applied_count"
echo "MIGRATIONS_ADOPTED=$adopted_count"
echo "SCHEMA_VERIFICATION=OK"
echo "BOOTSTRAP_COMPLETE"
echo "SCHEMA_HEAD=$declared_head"
