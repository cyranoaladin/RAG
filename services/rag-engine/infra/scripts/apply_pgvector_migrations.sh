#!/usr/bin/env bash
# Apply the contiguous pgvector migration manifest with an atomic registry.
# Usage: cd services/rag-engine/infra && BACKUP_ROOT=... ./scripts/apply_pgvector_migrations.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATIONS_DIR="$INFRA_DIR/postgres/migrations"
MIGRATION_HEAD_FILE="$MIGRATIONS_DIR/HEAD"
RUNTIME_ROLE_PROVISIONING="$INFRA_DIR/postgres/provision_runtime_roles.sh"

# shellcheck source=lib/pgvector_migration_state.sh
source "$SCRIPT_DIR/lib/pgvector_migration_state.sh"

# Load the deployment environment without displaying it.
load_deployment_environment "$INFRA_DIR/.env"

PGVECTOR_CONTAINER="${PGVECTOR_CONTAINER:-rag_pgvector}"
PGVECTOR_DB="${PGVECTOR_DB:-ragdb}"
PGVECTOR_USER="${PGVECTOR_USER:-raguser}"
: "${BACKUP_ROOT:?BACKUP_ROOT must be set to a persistent backup directory}"

# shellcheck source=../postgres/provision_runtime_roles.sh
source "$RUNTIME_ROLE_PROVISIONING"

discover_manifest "$MIGRATIONS_DIR" "$MIGRATION_HEAD_FILE"
MIGRATION_SNAPSHOT_DIR=""
MIGRATION_SNAPSHOT_FILES=()
trap cleanup_manifest_snapshot EXIT
trap 'exit 130' HUP INT TERM
create_manifest_snapshot "$MIGRATIONS_DIR" "$MIGRATION_HEAD_FILE"

if ! docker inspect --format='{{.State.Running}}' "$PGVECTOR_CONTAINER" \
    2>/dev/null | grep -qx true; then
    echo "FATAL: pgvector container is not running" >&2
    exit 1
fi

read_database_state() {
    local state_output line kind first second third extra

    APPLIED_VERSIONS=()
    APPLIED_NAMES=()
    APPLIED_SHA256=()
    REGISTRY_PRESENT=""
    RAG_CHUNKS_PRESENT=""
    UNREGISTERED_SCHEMA_HEAD=0
    state_output="$({ read_migration_state_sql; } | docker exec -i \
        "$PGVECTOR_CONTAINER" psql -X -q -A -t -v ON_ERROR_STOP=1 \
        -U "$PGVECTOR_USER" -d "$PGVECTOR_DB")"

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
    state_output="$({ read_unregistered_hybrid_state_sql; } | docker exec -i \
        "$PGVECTOR_CONTAINER" psql -X -q -A -t -v ON_ERROR_STOP=1 \
        -U "$PGVECTOR_USER" -d "$PGVECTOR_DB")"

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
            if (( EFFECTIVE_HEAD >= 4 )); then
                validate_004_sql
            else
                validate_004_absent_sql
            fi
            validate_registry_sql "$EFFECTIVE_HEAD"
        } | docker exec -i "$PGVECTOR_CONTAINER" \
            psql -X -q -v ON_ERROR_STOP=1 \
            -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" >/dev/null
    elif [[ "$RAG_CHUNKS_PRESENT" == "1" ]]; then
        {
            validate_001_sql
            if (( UNREGISTERED_SCHEMA_HEAD == 2 )); then
                validate_002_sql
            else
                validate_002_absent_sql
            fi
            validate_003_absent_sql
            validate_004_absent_sql
        } | docker exec -i "$PGVECTOR_CONTAINER" \
            psql -X -q -v ON_ERROR_STOP=1 \
            -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" >/dev/null
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
        validate_004_absent_sql
        for ((version = 1; version <= adopted_head; version++)); do
            variable_prefix="migration_$(printf '%03d' "$version")"
            printf '%s\n' \
                "INSERT INTO rag_schema_migrations (version, file_name, sha256)" \
                "VALUES ($version, :'${variable_prefix}_file', :'${variable_prefix}_sha');"
        done
        # NEXUS_ADOPTION_FAILURE_INJECTION_POINT
        validate_001_sql
        if (( adopted_head >= 2 )); then
            validate_002_sql
        else
            validate_002_absent_sql
        fi
        validate_003_absent_sql
        validate_004_absent_sql
        validate_registry_sql "$adopted_head"
    } | docker exec -i "$PGVECTOR_CONTAINER" \
        psql -X -q --single-transaction \
        -v ON_ERROR_STOP=1 \
        "${psql_variables[@]}" \
        -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" >/dev/null
}

backup_database() {
    local stamp backup_dir backup_file remote_dump

    stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
    backup_dir="$BACKUP_ROOT/pgvector-migration-$stamp"
    backup_file="$backup_dir/ragdb-before-migrations.dump"
    remote_dump="/tmp/nexus-rag-schema-$stamp.dump"
    umask 077
    mkdir -p "$backup_dir"
    chmod 700 "$backup_dir"

    if ! docker exec "$PGVECTOR_CONTAINER" \
        pg_dump -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" -Fc -f "$remote_dump"; then
        docker exec "$PGVECTOR_CONTAINER" rm -f "$remote_dump" >/dev/null 2>&1 || true
        return 1
    fi
    if ! docker cp "$PGVECTOR_CONTAINER:$remote_dump" "$backup_file"; then
        docker exec "$PGVECTOR_CONTAINER" rm -f "$remote_dump" >/dev/null 2>&1 || true
        return 1
    fi
    chmod 600 "$backup_file"
    docker exec "$PGVECTOR_CONTAINER" rm -f "$remote_dump" >/dev/null
    echo "BACKUP_COMPLETE=$backup_file"
}

run_up_transition() {
    local version="$1"
    local mode="$2"
    local index=$((version - 1))
    local migration_file="${MIGRATION_FILES[$index]}"
    local migration_name="${MIGRATION_NAMES[$index]}"
    local migration_sha="${MIGRATION_SHA256[$index]}"
    local -a docker_environment=()

    if (( version == 4 )); then
        POSTGRES_USER="$PGVECTOR_USER"
        POSTGRES_DB="$PGVECTOR_DB"
        export POSTGRES_USER POSTGRES_DB \
            PGVECTOR_RETRIEVAL_USER PGVECTOR_RETRIEVAL_PASSWORD \
            PGVECTOR_REVIEW_USER PGVECTOR_REVIEW_PASSWORD \
            PGVECTOR_PUBLISHER_USER PGVECTOR_PUBLISHER_PASSWORD
        validate_runtime_role_environment
        docker_environment=(
            -e POSTGRES_DB
            -e PGVECTOR_RETRIEVAL_USER
            -e PGVECTOR_RETRIEVAL_PASSWORD
            -e PGVECTOR_REVIEW_USER
            -e PGVECTOR_REVIEW_PASSWORD
            -e PGVECTOR_PUBLISHER_USER
            -e PGVECTOR_PUBLISHER_PASSWORD
        )
    fi

    {
        advisory_lock_sql
        if (( version == 1 )); then
            registry_schema_sql
        fi
        if [[ "$mode" == "recognize" ]]; then
            validate_001_sql
        else
            command cat "$migration_file"
            printf '\n'
        fi
        if (( version == 4 )); then
            provision_runtime_roles_sql
        fi
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
        if (( version >= 4 )); then
            validate_004_sql
        else
            validate_004_absent_sql
        fi
        validate_registry_sql "$version"
    } | docker exec -i "${docker_environment[@]}" "$PGVECTOR_CONTAINER" \
        psql -X -q --single-transaction \
        -v ON_ERROR_STOP=1 \
        -v "migration_version=$version" \
        -v "migration_file=$migration_name" \
        -v "migration_sha=$migration_sha" \
        -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" >/dev/null
}

# The entire preflight is read-only. The backup is the mutation boundary.
read_database_state
run_readonly_preflight_validation

declared_head="${#MIGRATION_VERSIONS[@]}"
if [[ "$REGISTRY_PRESENT" == "1" ]] && (( EFFECTIVE_HEAD == declared_head )); then
    echo "MIGRATIONS_APPLIED=0"
    echo "MIGRATIONS_ADOPTED=0"
    echo "SCHEMA_VERIFICATION=OK"
    echo "UPGRADE_COMPLETE"
    exit 0
fi

backup_database

applied_count=0
adopted_count=0
if (( UNREGISTERED_SCHEMA_HEAD > 0 )); then
    run_adoption_transition "$UNREGISTERED_SCHEMA_HEAD"
    EFFECTIVE_HEAD="$UNREGISTERED_SCHEMA_HEAD"
    adopted_count="$UNREGISTERED_SCHEMA_HEAD"
fi

for ((version = EFFECTIVE_HEAD + 1; version <= declared_head; version++)); do
    run_up_transition "$version" apply
    applied_count=$((applied_count + 1))
done

echo "MIGRATIONS_APPLIED=$applied_count"
echo "MIGRATIONS_ADOPTED=$adopted_count"
echo "SCHEMA_VERIFICATION=OK"
echo "UPGRADE_COMPLETE"
