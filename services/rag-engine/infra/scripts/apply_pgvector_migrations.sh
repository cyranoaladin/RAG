#!/usr/bin/env bash
# Apply the contiguous pgvector migration manifest with an atomic registry.
# Usage: cd services/rag-engine/infra && BACKUP_ROOT=... ./scripts/apply_pgvector_migrations.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATIONS_DIR="$INFRA_DIR/postgres/migrations"
MIGRATION_HEAD_FILE="$MIGRATIONS_DIR/HEAD"

# Load the deployment environment without displaying it.
if [[ -f "$INFRA_DIR/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source "$INFRA_DIR/.env"
    set +a
fi

PGVECTOR_CONTAINER="${PGVECTOR_CONTAINER:-rag_pgvector}"
PGVECTOR_DB="${PGVECTOR_DB:-ragdb}"
PGVECTOR_USER="${PGVECTOR_USER:-raguser}"
: "${BACKUP_ROOT:?BACKUP_ROOT must be set to a persistent backup directory}"

# shellcheck source=lib/pgvector_migration_state.sh
source "$SCRIPT_DIR/lib/pgvector_migration_state.sh"

discover_manifest "$MIGRATIONS_DIR" "$MIGRATION_HEAD_FILE"

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

    [[ "$REGISTRY_PRESENT" =~ ^[01]$ && "$RAG_CHUNKS_PRESENT" =~ ^[01]$ ]] \
        || { echo "MIGRATION_STATE_OUTPUT_INVALID" >&2; return 1; }
    validate_registry_state "$REGISTRY_PRESENT"
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
            validate_registry_sql "$EFFECTIVE_HEAD"
        } | docker exec -i "$PGVECTOR_CONTAINER" \
            psql -X -q -v ON_ERROR_STOP=1 \
            -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" >/dev/null
    elif [[ "$RAG_CHUNKS_PRESENT" == "1" ]]; then
        {
            validate_001_sql
            validate_002_absent_sql
        } | docker exec -i "$PGVECTOR_CONTAINER" \
            psql -X -q -v ON_ERROR_STOP=1 \
            -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" >/dev/null
    fi
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

    docker exec "$PGVECTOR_CONTAINER" \
        pg_dump -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" -Fc -f "$remote_dump"
    if ! docker cp "$PGVECTOR_CONTAINER:$remote_dump" "$backup_file"; then
        docker exec "$PGVECTOR_CONTAINER" rm -f "$remote_dump" >/dev/null 2>&1 || true
        return 1
    fi
    chmod 600 "$backup_file"
    docker exec "$PGVECTOR_CONTAINER" rm -f "$remote_dump" >/dev/null 2>&1 || true
    echo "BACKUP_COMPLETE=$backup_file"
}

run_up_transition() {
    local version="$1"
    local mode="$2"
    local index=$((version - 1))
    local migration_file="${MIGRATION_FILES[$index]}"
    local migration_name="${MIGRATION_NAMES[$index]}"
    local migration_sha="${MIGRATION_SHA256[$index]}"

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
        validate_registry_sql "$version"
    } | docker exec -i "$PGVECTOR_CONTAINER" \
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
if (( EFFECTIVE_HEAD == declared_head )); then
    echo "MIGRATIONS_APPLIED=0"
    echo "SCHEMA_VERIFICATION=OK"
    echo "UPGRADE_COMPLETE"
    exit 0
fi

backup_database

applied_count=0
if [[ "$REGISTRY_PRESENT" == "0" && "$RAG_CHUNKS_PRESENT" == "1" ]]; then
    run_up_transition 1 recognize
    EFFECTIVE_HEAD=1
    applied_count=$((applied_count + 1))
fi

for ((version = EFFECTIVE_HEAD + 1; version <= declared_head; version++)); do
    run_up_transition "$version" apply
    applied_count=$((applied_count + 1))
done

echo "MIGRATIONS_APPLIED=$applied_count"
echo "SCHEMA_VERIFICATION=OK"
echo "UPGRADE_COMPLETE"
