#!/usr/bin/env bash
# Apply pgvector migrations — idempotent, versioned upgrade path.
# Usage: cd services/rag-engine/infra && ./scripts/apply_pgvector_migrations.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$INFRA_DIR"

# Load .env without displaying it
if [[ -f .env ]]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

PGVECTOR_CONTAINER="${PGVECTOR_CONTAINER:-rag_pgvector}"
PGVECTOR_DB="${PGVECTOR_DB:-ragdb}"
PGVECTOR_USER="${PGVECTOR_USER:-raguser}"
MIGRATIONS_DIR="postgres/migrations"
BACKUP_ROOT="${BACKUP_ROOT:-/backup/rag}"

# ── Pre-flight checks ────────────────────────────────────────────────

if ! docker inspect --format='{{.State.Running}}' "$PGVECTOR_CONTAINER" 2>/dev/null | grep -q true; then
    echo "FATAL: container $PGVECTOR_CONTAINER is not running" >&2
    exit 1
fi

MIGRATION_FILES=()
while IFS= read -r f; do
    MIGRATION_FILES+=("$f")
done < <(find "$MIGRATIONS_DIR" -maxdepth 1 -name '*.sql' -type f | sort)

if [[ ${#MIGRATION_FILES[@]} -eq 0 ]]; then
    echo "FATAL: no migration files found in $MIGRATIONS_DIR" >&2
    exit 1
fi

# ── Backup ────────────────────────────────────────────────────────────

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP_DIR="${BACKUP_ROOT}/pgvector-migration-${STAMP}"
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR"

docker exec "$PGVECTOR_CONTAINER" \
    pg_dump -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" -Fc \
    -f /tmp/ragdb-before-migrations.dump
docker cp "$PGVECTOR_CONTAINER":/tmp/ragdb-before-migrations.dump \
    "$BACKUP_DIR/ragdb-before-migrations.dump"
docker exec "$PGVECTOR_CONTAINER" rm -f /tmp/ragdb-before-migrations.dump

echo "BACKUP=$BACKUP_DIR/ragdb-before-migrations.dump"

# ── Apply migrations ─────────────────────────────────────────────────

for migration in "${MIGRATION_FILES[@]}"; do
    echo "APPLYING $(basename "$migration")"
    docker exec -i "$PGVECTOR_CONTAINER" \
        psql -v ON_ERROR_STOP=1 -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" \
        < "$migration"
done

echo "MIGRATIONS_APPLIED=${#MIGRATION_FILES[@]}"

# ── Schema verification ──────────────────────────────────────────────

V2_REQUIRED_COLUMNS="chunk_id doc_id collection review_status source_label source_uri rights type_doc"

ACTUAL_COLUMNS=$(docker exec "$PGVECTOR_CONTAINER" \
    psql -tAc "SELECT column_name FROM information_schema.columns
               WHERE table_schema='public' AND table_name='rag_chunks'
               ORDER BY ordinal_position;" \
    -U "$PGVECTOR_USER" -d "$PGVECTOR_DB")

for col in $V2_REQUIRED_COLUMNS; do
    if ! echo "$ACTUAL_COLUMNS" | grep -qx "$col"; then
        echo "FATAL: column $col missing from rag_chunks" >&2
        exit 1
    fi
done

VECTOR_TYPE=$(docker exec "$PGVECTOR_CONTAINER" \
    psql -tAc "SELECT format_type(a.atttypid, a.atttypmod)
               FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
               WHERE c.relname='rag_chunks' AND a.attname='vector';" \
    -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" | tr -d '[:space:]')

if [[ "$VECTOR_TYPE" != "vector(1024)" ]]; then
    echo "FATAL: vector type is '$VECTOR_TYPE', expected 'vector(1024)'" >&2
    exit 1
fi

echo "SCHEMA_VERIFICATION=OK"
echo "UPGRADE_COMPLETE"
