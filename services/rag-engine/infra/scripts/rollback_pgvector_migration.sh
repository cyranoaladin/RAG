#!/usr/bin/env bash
# Roll back exactly migration 002 while preserving its predecessor and backup.
# Usage: BACKUP_ROOT=... ./rollback_pgvector_migration.sh 002_hybrid_retrieval
set -euo pipefail

if [[ "${1:-}" != "002_hybrid_retrieval" || "$#" -ne 1 ]]; then
    echo "ROLLBACK_ARGUMENT_INVALID: expected 002_hybrid_retrieval" >&2
    exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATIONS_DIR="$INFRA_DIR/postgres/migrations"
MIGRATION_HEAD_FILE="$MIGRATIONS_DIR/HEAD"
ROLLBACK_FILE="$INFRA_DIR/postgres/rollbacks/002_hybrid_retrieval.down.sql"

# shellcheck source=lib/pgvector_migration_state.sh
source "$SCRIPT_DIR/lib/pgvector_migration_state.sh"

# Load the deployment environment without displaying it.
load_deployment_environment "$INFRA_DIR/.env"

PGVECTOR_CONTAINER="${PGVECTOR_CONTAINER:-rag_pgvector}"
PGVECTOR_DB="${PGVECTOR_DB:-ragdb}"
PGVECTOR_USER="${PGVECTOR_USER:-raguser}"
: "${BACKUP_ROOT:?BACKUP_ROOT must be set to a persistent backup directory}"

discover_manifest "$MIGRATIONS_DIR" "$MIGRATION_HEAD_FILE"

if [[ ${#MIGRATION_VERSIONS[@]} -lt 2 \
   || "${MIGRATION_NAMES[1]}" != "002_hybrid_retrieval.sql" ]]; then
    echo "ROLLBACK_HEAD_INVALID: migration 002_hybrid_retrieval is unavailable" >&2
    exit 1
fi
if [[ ! -f "$ROLLBACK_FILE" || -L "$ROLLBACK_FILE" ]]; then
    echo "ROLLBACK_FILE_INVALID" >&2
    exit 1
fi
MIGRATION_SNAPSHOT_DIR=""
MIGRATION_SNAPSHOT_FILES=()
trap cleanup_manifest_snapshot EXIT
trap 'exit 130' HUP INT TERM
create_manifest_snapshot "$MIGRATIONS_DIR" "$MIGRATION_HEAD_FILE" "$ROLLBACK_FILE"
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

backup_database() {
    local stamp backup_dir backup_file remote_dump

    stamp="$(date -u +%Y%m%dT%H%M%SZ)-$$"
    backup_dir="$BACKUP_ROOT/pgvector-rollback-$stamp"
    backup_file="$backup_dir/ragdb-before-rollback-002.dump"
    remote_dump="/tmp/nexus-rag-schema-rollback-$stamp.dump"
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

read_database_state
if [[ "$REGISTRY_PRESENT" != "1" || "$RAG_CHUNKS_PRESENT" != "1" \
   || "$EFFECTIVE_HEAD" -ne 2 ]]; then
    echo "ROLLBACK_HEAD_INVALID: effective head must be 002_hybrid_retrieval" >&2
    exit 1
fi

{
    validate_001_sql
    validate_002_sql
    validate_registry_sql 2
} | docker exec -i "$PGVECTOR_CONTAINER" \
    psql -X -q -v ON_ERROR_STOP=1 \
    -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" >/dev/null

backup_database

{
    advisory_lock_sql
    command cat "$MIGRATION_ROLLBACK_FILE"
    printf '\n'
    cat <<'SQL'
DELETE FROM rag_schema_migrations
WHERE version = 2;
SQL
    validate_001_sql
    validate_002_absent_sql
    validate_registry_sql 1
} | docker exec -i "$PGVECTOR_CONTAINER" \
    psql -X -q --single-transaction -v ON_ERROR_STOP=1 \
    -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" >/dev/null

echo "ROLLBACK_COMPLETE=002_hybrid_retrieval"
echo "SCHEMA_VERIFICATION=OK"
