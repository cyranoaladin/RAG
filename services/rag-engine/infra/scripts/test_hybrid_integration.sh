#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
IMAGE="pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc"

suffix="$$-${RANDOM}-${RANDOM}"
PGVECTOR_CONTAINER="lot40-pg-${suffix}"
PGVECTOR_VOLUME="lot40-pg-volume-${suffix}"
PGVECTOR_DB="lot40db"
PGVECTOR_USER="lot40user"
PGVECTOR_APP_USER="lot40_app"
RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/lot40-hybrid.XXXXXX")"
BACKUP_ROOT="$RUN_ROOT/backups"
container_cleanup_armed=0
volume_cleanup_armed=0

is_exact_not_found() {
    local kind="$1"
    local name="$2"
    local diagnostic="$3"
    local daemon_message
    case "$kind" in
        container)
            daemon_message="Error response from daemon: No such container: $name"
            ;;
        volume)
            daemon_message="Error response from daemon: get $name: no such volume"
            ;;
        *)
            return 1
            ;;
    esac
    [[ "$diagnostic" == "$daemon_message" || "$diagnostic" == $'[]\n'"$daemon_message" ]]
}

remove_container_exact() {
    local remove_output remove_status inspect_output inspect_status
    remove_output="$(docker rm -f "$PGVECTOR_CONTAINER" 2>&1)"
    remove_status=$?
    inspect_output="$(docker container inspect "$PGVECTOR_CONTAINER" 2>&1)"
    inspect_status=$?
    if (( inspect_status == 0 )); then
        echo "LOT40_CLEANUP_CONTAINER_LEAK" >&2
        return 1
    fi
    if ! is_exact_not_found container "$PGVECTOR_CONTAINER" "$inspect_output"; then
        echo "LOT40_CLEANUP_CONTAINER_INSPECT_FAILED" >&2
        return 1
    fi
    if (( remove_status != 0 )) \
       && ! is_exact_not_found container "$PGVECTOR_CONTAINER" "$remove_output"; then
        echo "LOT40_CLEANUP_CONTAINER_REMOVE_FAILED" >&2
        return 1
    fi
    return 0
}

remove_volume_exact() {
    local remove_output remove_status inspect_output inspect_status
    remove_output="$(docker volume rm "$PGVECTOR_VOLUME" 2>&1)"
    remove_status=$?
    inspect_output="$(docker volume inspect "$PGVECTOR_VOLUME" 2>&1)"
    inspect_status=$?
    if (( inspect_status == 0 )); then
        echo "LOT40_CLEANUP_VOLUME_LEAK" >&2
        return 1
    fi
    if ! is_exact_not_found volume "$PGVECTOR_VOLUME" "$inspect_output"; then
        echo "LOT40_CLEANUP_VOLUME_INSPECT_FAILED" >&2
        return 1
    fi
    if (( remove_status != 0 )) \
       && ! is_exact_not_found volume "$PGVECTOR_VOLUME" "$remove_output"; then
        echo "LOT40_CLEANUP_VOLUME_REMOVE_FAILED" >&2
        return 1
    fi
    return 0
}

cleanup() {
    local original_status=$?
    local cleanup_status=0
    trap - EXIT INT TERM
    set +e

    if [[ ! "$PGVECTOR_CONTAINER" =~ ^lot40-pg-[0-9]+-[0-9]+-[0-9]+$ ]]; then
        echo "LOT40_CLEANUP_CONTAINER_NAME_INVALID" >&2
        cleanup_status=1
    elif (( container_cleanup_armed == 1 )); then
        remove_container_exact || cleanup_status=1
    fi

    if [[ ! "$PGVECTOR_VOLUME" =~ ^lot40-pg-volume-[0-9]+-[0-9]+-[0-9]+$ ]]; then
        echo "LOT40_CLEANUP_VOLUME_NAME_INVALID" >&2
        cleanup_status=1
    elif (( volume_cleanup_armed == 1 )); then
        remove_volume_exact || cleanup_status=1
    fi

    if [[ "$RUN_ROOT" =~ ^${TMPDIR:-/tmp}/lot40-hybrid\.[A-Za-z0-9]+$ ]]; then
        rm -rf -- "$RUN_ROOT" || cleanup_status=1
    else
        echo "LOT40_CLEANUP_TMP_NAME_INVALID" >&2
        cleanup_status=1
    fi

    if (( original_status != 0 )); then
        exit "$original_status"
    fi
    exit "$cleanup_status"
}
trap cleanup EXIT INT TERM

ready_attempts="${LOT40_PG_READY_ATTEMPTS:-30}"
ready_delay="${LOT40_PG_READY_DELAY_S:-1}"
if [[ ! "$ready_attempts" =~ ^[0-9]+$ ]] \
   || (( ready_attempts < 1 || ready_attempts > 120 )); then
    echo "LOT40_READY_ATTEMPTS_INVALID" >&2
    exit 2
fi
if [[ ! "$ready_delay" =~ ^([0-9]+([.][0-9]+)?)$ ]] \
   || ! awk -v value="$ready_delay" 'BEGIN { exit !(value >= 0 && value <= 10) }'; then
    echo "LOT40_READY_DELAY_INVALID" >&2
    exit 2
fi

mkdir -p "$BACKUP_ROOT"
volume_cleanup_armed=1
docker volume create "$PGVECTOR_VOLUME" >/dev/null
container_cleanup_armed=1
docker run -d \
    --name "$PGVECTOR_CONTAINER" \
    -e "POSTGRES_DB=$PGVECTOR_DB" \
    -e "POSTGRES_USER=$PGVECTOR_USER" \
    -e POSTGRES_HOST_AUTH_METHOD=trust \
    -v "$PGVECTOR_VOLUME:/var/lib/postgresql/data" \
    -p 127.0.0.1::5432 \
    "$IMAGE" >/dev/null

ready=0
for ((attempt = 1; attempt <= ready_attempts; attempt++)); do
    if docker exec "$PGVECTOR_CONTAINER" \
        pg_isready -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" >/dev/null 2>&1; then
        ready=1
        break
    fi
    if (( attempt < ready_attempts )); then
        sleep "$ready_delay"
    fi
done
if (( ready == 0 )); then
    echo "LOT40_DB_READINESS_TIMEOUT" >&2
    exit 1
fi

port_mapping="$(docker port "$PGVECTOR_CONTAINER" 5432/tcp)"
if [[ ! "$port_mapping" =~ ^127[.]0[.]0[.]1:([0-9]+)$ ]]; then
    echo "LOT40_PORT_MAPPING_INVALID" >&2
    exit 1
fi
PGVECTOR_PORT="${BASH_REMATCH[1]}"
export LOT40_PG_ADMIN_DSN="postgresql://$PGVECTOR_USER@127.0.0.1:$PGVECTOR_PORT/$PGVECTOR_DB"
export LOT40_PG_DSN="postgresql://$PGVECTOR_APP_USER@127.0.0.1:$PGVECTOR_PORT/$PGVECTOR_DB"

echo "LOT40_DATABASE_READY=PASS"

container_psql() {
    docker exec -i "$PGVECTOR_CONTAINER" \
        psql -X -q -v ON_ERROR_STOP=1 \
        -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" "$@"
}

expect_failure() {
    local label="$1"
    local status
    shift
    set +e
    "$@" >"$RUN_ROOT/${label}.out" 2>&1
    status=$?
    set -e
    if (( status == 0 )); then
        echo "${label}_UNEXPECTED_SUCCESS" >&2
        return 1
    fi
    echo "${label}=PASS"
}

run_apply() {
    PGVECTOR_CONTAINER="$PGVECTOR_CONTAINER" \
    PGVECTOR_DB="$PGVECTOR_DB" \
    PGVECTOR_USER="$PGVECTOR_USER" \
    BACKUP_ROOT="$BACKUP_ROOT" \
        bash "$1/scripts/apply_pgvector_migrations.sh"
}

run_down() {
    PGVECTOR_CONTAINER="$PGVECTOR_CONTAINER" \
    PGVECTOR_DB="$PGVECTOR_DB" \
    PGVECTOR_USER="$PGVECTOR_USER" \
    BACKUP_ROOT="$BACKUP_ROOT" \
        bash "$1/scripts/rollback_pgvector_migration.sh" 002_hybrid_retrieval
}

assert_fresh_head_002() {
    container_psql <<'SQL'
SELECT version
FROM rag_schema_migrations
WHERE version = 2 AND file_name = '002_hybrid_retrieval.sql';
SQL
}

sha_001="$(sha256sum "$INFRA_DIR/postgres/migrations/001_rag_chunks_v2_schema.sql" | awk '{print $1}')"
sha_002="$(sha256sum "$INFRA_DIR/postgres/migrations/002_hybrid_retrieval.sql" | awk '{print $1}')"

assert_state_001() {
    container_psql <<SQL
DO \$\$
BEGIN
    IF (SELECT count(*) FROM rag_schema_migrations) <> 1
       OR NOT EXISTS (
           SELECT 1 FROM rag_schema_migrations
           WHERE version = 1
             AND file_name = '001_rag_chunks_v2_schema.sql'
             AND sha256 = '$sha_001'
       )
       OR EXISTS (SELECT 1 FROM rag_schema_migrations WHERE version = 2)
       OR EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'rag_chunks'
             AND column_name = 'text_tsv'
       )
       OR to_regclass('public.idx_rag_chunks_text_tsv') IS NOT NULL THEN
        RAISE EXCEPTION 'LOT40_EXPECTED_HEAD_001';
    END IF;
END
\$\$;
SQL
}

assert_state_002() {
    container_psql <<SQL
DO \$\$
BEGIN
    IF (SELECT count(*) FROM rag_schema_migrations) <> 2
       OR NOT EXISTS (
           SELECT 1 FROM rag_schema_migrations
           WHERE version = 1
             AND file_name = '001_rag_chunks_v2_schema.sql'
             AND sha256 = '$sha_001'
       )
       OR NOT EXISTS (
           SELECT 1 FROM rag_schema_migrations
           WHERE version = 2
             AND file_name = '002_hybrid_retrieval.sql'
             AND sha256 = '$sha_002'
       )
       OR (SELECT max(version) FROM rag_schema_migrations) <> 2
       OR NOT EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'rag_chunks'
             AND column_name = 'text_tsv' AND is_generated = 'ALWAYS'
       )
       OR to_regclass('public.idx_rag_chunks_text_tsv') IS NULL THEN
        RAISE EXCEPTION 'LOT40_EXPECTED_HEAD_002';
    END IF;
END
\$\$;
SQL
}

provision_app_role() {
    container_psql <<SQL
CREATE ROLE $PGVECTOR_APP_USER
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;
REVOKE ALL PRIVILEGES ON DATABASE $PGVECTOR_DB FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON SCHEMA public FROM $PGVECTOR_APP_USER;
REVOKE ALL PRIVILEGES ON TABLE rag_chunks FROM $PGVECTOR_APP_USER;
GRANT CONNECT ON DATABASE $PGVECTOR_DB TO $PGVECTOR_APP_USER;
GRANT USAGE ON SCHEMA public TO $PGVECTOR_APP_USER;
GRANT USAGE ON TYPE vector TO $PGVECTOR_APP_USER;
GRANT SELECT ON TABLE rag_chunks TO $PGVECTOR_APP_USER;
SQL
}

expect_failure FRESH_HEAD_002_NEGATIVE assert_fresh_head_002

run_apply "$INFRA_DIR"
assert_state_002
run_down "$INFRA_DIR"
assert_state_001
run_apply "$INFRA_DIR"
assert_state_002
echo "MIGRATION_CYCLE_001_002_001_002=PASS"

run_down "$INFRA_DIR"
assert_state_001
atomic_up_root="$RUN_ROOT/atomic-up"
mkdir -p "$atomic_up_root"
cp -a -- "$INFRA_DIR" "$atomic_up_root/infra"
printf '\nSELECT 1 / 0;\n' \
    >> "$atomic_up_root/infra/postgres/migrations/002_hybrid_retrieval.sql"
expect_failure ATOMIC_UP_EXPECTED_FAILURE run_apply "$atomic_up_root/infra"
assert_state_001
echo "ATOMIC_UP_ROLLBACK=PASS"

run_apply "$INFRA_DIR"
assert_state_002
atomic_down_root="$RUN_ROOT/atomic-down"
mkdir -p "$atomic_down_root"
cp -a -- "$INFRA_DIR" "$atomic_down_root/infra"
printf '\nSELECT 1 / 0;\n' \
    >> "$atomic_down_root/infra/postgres/rollbacks/002_hybrid_retrieval.down.sql"
expect_failure ATOMIC_DOWN_EXPECTED_FAILURE run_down "$atomic_down_root/infra"
assert_state_002
echo "ATOMIC_DOWN_ROLLBACK=PASS"
echo "MIGRATION_FINAL_HEAD_002=PASS"
provision_app_role
echo "APP_ROLE_LEAST_PRIVILEGE=PASS"

LOT40_PG_DSN="$LOT40_PG_DSN" \
LOT40_PG_ADMIN_DSN="$LOT40_PG_ADMIN_DSN" \
PYTHONPATH="$SERVICE_ROOT/src" "$SERVICE_ROOT/.venv/bin/pytest" "$SERVICE_ROOT/tests/integration/test_lot40_hybrid_pgvector.py" -q -s

assert_state_002
echo "LOT40_HYBRID_INTEGRATION=PASS"
