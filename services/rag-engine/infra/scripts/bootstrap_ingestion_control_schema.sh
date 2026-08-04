#!/usr/bin/env bash
# Bootstrap/catch-up automatique du schéma ingestion_control (LOT44b).
#
# Applique, dans l'ordre, les migrations numérotées de
# infra/postgres/ingestion_control/migrations/*.sql sur le schéma logique
# dédié "ingestion_control" — décision D1 : même instance PostgreSQL/pgvector
# que le reste du projet, jamais mélangé au schéma "public"/rag_chunks.
#
# Différence assumée par rapport à bootstrap_pgvector_schema.sh /
# pgvector_migration_state.sh : ce script ne réutilise pas la bibliothèque
# rag_chunks (validate_001_sql, etc. y encodent en dur des colonnes/index
# spécifiques à rag_chunks — non généralisable sans dupliquer 1000+ lignes
# de validation de catalogue pour un schéma différent). Ce script applique
# une version proportionnée du même principe : registre versionné, checksum
# par migration, verrou pour éviter une double application concurrente, et
# revalidation explicite après application — mais sans le fingerprint
# exhaustif de catalogue Postgres (colonnes/contraintes/index un par un)
# que pgvector_migration_state.sh applique pour rag_chunks. Documenté comme
# réserve dans le rapport LOT44b.
#
# Usage : PGHOST=... PGPORT=... PGUSER=... PGPASSWORD=... PGDATABASE=... \
#         ./scripts/bootstrap_ingestion_control_schema.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MIGRATIONS_DIR="$INFRA_DIR/postgres/ingestion_control/migrations"
HEAD_FILE="$MIGRATIONS_DIR/HEAD"

: "${PGHOST:?PGHOST must be set}"
: "${PGDATABASE:?PGDATABASE must be set}"
: "${PGUSER:?PGUSER must be set}"

[[ -f "$HEAD_FILE" ]] || { echo "FATAL: HEAD file missing: $HEAD_FILE" >&2; exit 1; }
declared_head_name="$(<"$HEAD_FILE")"

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

# Discover the manifest: NNN_description.sql, contiguous from 1, no gaps,
# no duplicates — same discipline as pgvector_migration_state.sh, kept
# local here since it is a handful of lines, not worth a shared dependency
# for a single caller.
discover_manifest() {
    local entry basename number stem expected
    local -a candidates=()
    MIGRATION_VERSIONS=()
    MIGRATION_NAMES=()
    MIGRATION_FILES=()
    MIGRATION_SHA256=()

    mapfile -t candidates < <(
        find "$MIGRATIONS_DIR" -maxdepth 1 -type f \
            -name '[0-9][0-9][0-9]_*.sql' -print | LC_ALL=C sort
    )
    [[ ${#candidates[@]} -gt 0 ]] || { echo "FATAL: no migration files found in $MIGRATIONS_DIR" >&2; exit 1; }

    expected=1
    for entry in "${candidates[@]}"; do
        basename="$(basename "$entry")"
        [[ "$basename" =~ ^([0-9]{3})_([a-z0-9_]+)\.sql$ ]] \
            || { echo "FATAL: invalid migration filename: $basename" >&2; exit 1; }
        number=$((10#${BASH_REMATCH[1]}))
        (( number == expected )) \
            || { echo "FATAL: migration gap/duplicate at $(printf '%03d' "$expected"), found $basename" >&2; exit 1; }
        MIGRATION_VERSIONS+=("$number")
        MIGRATION_NAMES+=("$basename")
        MIGRATION_FILES+=("$entry")
        MIGRATION_SHA256+=("$(sha256sum "$entry" | awk '{print $1}')")
        expected=$((expected + 1))
    done

    stem="${MIGRATION_NAMES[${#MIGRATION_NAMES[@]} - 1]%.sql}"
    [[ "$stem" == "$declared_head_name" ]] \
        || { echo "FATAL: HEAD ($declared_head_name) does not match last migration ($stem)" >&2; exit 1; }
}

registry_schema_sql() {
    cat <<'SQL'
CREATE SCHEMA IF NOT EXISTS ingestion_control;
CREATE TABLE IF NOT EXISTS ingestion_control.schema_migrations (
    version     INTEGER PRIMARY KEY,
    file_name   TEXT NOT NULL,
    sha256      TEXT NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
SQL
}

advisory_lock_sql() {
    # Clé arbitraire mais stable, distincte de celle de pgvector_migration_state.sh
    # (namespace différent : ingestion_control, pas rag_chunks).
    echo "SELECT pg_advisory_xact_lock(72144, 1);"
}

read_registry_state() {
    local output
    APPLIED_VERSIONS=()
    APPLIED_SHA256=()
    output="$(psql -X -q -A -t -F'|' -v ON_ERROR_STOP=1 -c "
        SELECT version, sha256 FROM ingestion_control.schema_migrations
        ORDER BY version;
    " 2>/dev/null || true)"
    while IFS='|' read -r version sha; do
        [[ -z "$version" ]] && continue
        APPLIED_VERSIONS+=("$version")
        APPLIED_SHA256+=("$sha")
    done <<< "$output"
}

verify_no_checksum_drift() {
    local index=0
    for version in "${APPLIED_VERSIONS[@]}"; do
        local declared_sha="${MIGRATION_SHA256[$((version - 1))]}"
        local stored_sha="${APPLIED_SHA256[$index]}"
        if [[ "$declared_sha" != "$stored_sha" ]]; then
            echo "FATAL: MIGRATION_CHECKSUM_MISMATCH version=$version stored=$stored_sha declared=$declared_sha" >&2
            exit 1
        fi
        index=$((index + 1))
    done
}

apply_migration() {
    local version="$1"
    local index=$((version - 1))
    local file="${MIGRATION_FILES[$index]}"
    local name="${MIGRATION_NAMES[$index]}"
    local sha="${MIGRATION_SHA256[$index]}"

    {
        advisory_lock_sql
        registry_schema_sql
        cat "$file"
        printf '\n'
        printf '%s\n' \
            "INSERT INTO ingestion_control.schema_migrations (version, file_name, sha256)" \
            "VALUES (:'migration_version'::integer, :'migration_file', :'migration_sha');"
    } | psql -X -q --single-transaction \
        -v ON_ERROR_STOP=1 \
        -v "migration_version=$version" \
        -v "migration_file=$name" \
        -v "migration_sha=$sha" >/dev/null
}

verify_expected_tables_exist() {
    psql -X -q -v ON_ERROR_STOP=1 <<'SQL' >/dev/null
DO $$
BEGIN
    IF to_regclass('ingestion_control.ingestion_runs') IS NULL
       OR to_regclass('ingestion_control.resources') IS NULL
       OR to_regclass('ingestion_control.resource_candidates') IS NULL
       OR to_regclass('ingestion_control.artifacts') IS NULL
       OR to_regclass('ingestion_control.workflow_events') IS NULL THEN
        RAISE EXCEPTION 'INGESTION_CONTROL_SCHEMA_INCOMPLETE';
    END IF;
END
$$;
SQL
}

wait_for_connection
discover_manifest
registry_schema_sql | psql -X -q -v ON_ERROR_STOP=1 >/dev/null
read_registry_state
verify_no_checksum_drift

declared_head="${#MIGRATION_VERSIONS[@]}"
current_head="${#APPLIED_VERSIONS[@]}"

applied_count=0
for ((version = current_head + 1; version <= declared_head; version++)); do
    apply_migration "$version"
    applied_count=$((applied_count + 1))
done

# Revalidation : ne jamais faire confiance à sa propre comptabilité.
read_registry_state
verify_no_checksum_drift
if (( ${#APPLIED_VERSIONS[@]} != declared_head )); then
    echo "FATAL: schema head after bootstrap (${#APPLIED_VERSIONS[@]}) does not match declared head ($declared_head)" >&2
    exit 1
fi
verify_expected_tables_exist

echo "MIGRATIONS_APPLIED=$applied_count"
echo "SCHEMA_VERIFICATION=OK"
echo "BOOTSTRAP_COMPLETE"
echo "SCHEMA_HEAD=$declared_head"
