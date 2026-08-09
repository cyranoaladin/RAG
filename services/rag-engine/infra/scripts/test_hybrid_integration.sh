#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INFRA_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
SERVICE_ROOT="$(cd "$INFRA_DIR/.." && pwd)"
PYTEST_BIN="${NEXUS_RAG_ENGINE_PYTEST:-$SERVICE_ROOT/.venv/bin/pytest}"
IMAGE="pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc"

suffix="$$-${RANDOM}-${RANDOM}"
PGVECTOR_CONTAINER="lot40-pg-${suffix}"
PGVECTOR_VOLUME="lot40-pg-volume-${suffix}"
LOT40_OWNER_KEY="com.nexus.lot40.owner"
LOT40_OWNER_TOKEN="$(od -An -N16 -tx1 /dev/urandom | tr -d '[:space:]')"
if [[ ! "$LOT40_OWNER_TOKEN" =~ ^[0-9a-f]{32}$ ]]; then
    echo "LOT40_OWNER_TOKEN_INVALID" >&2
    exit 2
fi
LOT40_OWNER_LABEL="$LOT40_OWNER_KEY=$LOT40_OWNER_TOKEN"
PGVECTOR_BOOTSTRAP_DB="lot40db"
PGVECTOR_FRESH_DB="lot40fresh"
PGVECTOR_DB="$PGVECTOR_BOOTSTRAP_DB"
PGVECTOR_USER="lot40user"
PGVECTOR_APP_USER="lot40_app"
PGVECTOR_REVIEW_USER="lot41_review"
PGVECTOR_PUBLISHER_USER="lot42_publisher"
PGVECTOR_APP_PASSWORD="lot40-app-$LOT40_OWNER_TOKEN"
PGVECTOR_REVIEW_PASSWORD="lot41-review-$LOT40_OWNER_TOKEN"
PGVECTOR_PUBLISHER_PASSWORD="lot42-publisher-$LOT40_OWNER_TOKEN"
RUN_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/lot40-hybrid.XXXXXX")"
BACKUP_ROOT="$RUN_ROOT/backups"
container_cleanup_armed=0
volume_cleanup_armed=0
PGVECTOR_CONTAINER_ID=""
PGVECTOR_VOLUME_CREATED_AT=""

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

inspect_container_identity() {
    docker container inspect \
        --format '{{.Id}}|{{.Name}}|{{ index .Config.Labels "com.nexus.lot40.owner" }}' \
        "$1"
}

inspect_volume_identity() {
    docker volume inspect \
        --format '{{ index .Labels "com.nexus.lot40.owner" }}|{{.CreatedAt}}' \
        "$PGVECTOR_VOLUME"
}

parse_container_identity() {
    local identity="$1"
    local extra=""
    IFS='|' read -r parsed_container_id parsed_container_name \
        parsed_container_owner extra <<< "$identity"
    [[ -z "$extra" \
       && "$parsed_container_id" =~ ^[0-9a-f]{64}$ \
       && "$parsed_container_name" == "/$PGVECTOR_CONTAINER" \
       && "$parsed_container_owner" == "$LOT40_OWNER_TOKEN" ]]
}

parse_volume_identity() {
    local identity="$1"
    local extra=""
    IFS='|' read -r parsed_volume_owner parsed_volume_created_at extra <<< "$identity"
    [[ -z "$extra" \
       && "$parsed_volume_owner" == "$LOT40_OWNER_TOKEN" \
       && "$parsed_volume_created_at" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}([.][0-9]+)?(Z|[+-][0-9]{2}:[0-9]{2})$ ]]
}

capture_container_identity() {
    local returned_id="$1"
    local identity
    if [[ ! "$returned_id" =~ ^[0-9a-f]{64}$ ]] \
       || ! identity="$(inspect_container_identity "$returned_id" 2>&1)" \
       || ! parse_container_identity "$identity" \
       || [[ "$parsed_container_id" != "$returned_id" ]]; then
        echo "LOT40_CONTAINER_IDENTITY_MISMATCH" >&2
        return 1
    fi
    PGVECTOR_CONTAINER_ID="$returned_id"
}

capture_volume_identity() {
    local identity
    if ! identity="$(inspect_volume_identity 2>&1)" \
       || ! parse_volume_identity "$identity"; then
        echo "LOT40_VOLUME_IDENTITY_MISMATCH" >&2
        return 1
    fi
    PGVECTOR_VOLUME_CREATED_AT="$parsed_volume_created_at"
}

remove_container_exact() {
    local identity expected_identity inspect_output remove_output
    local inspect_status remove_status name_identity

    if [[ -z "$PGVECTOR_CONTAINER_ID" ]]; then
        if identity="$(inspect_container_identity "$PGVECTOR_CONTAINER" 2>&1)"; then
            if ! parse_container_identity "$identity"; then
                echo "LOT40_CLEANUP_CONTAINER_OWNERSHIP_MISMATCH" >&2
                return 1
            fi
            PGVECTOR_CONTAINER_ID="$parsed_container_id"
        elif is_exact_not_found container "$PGVECTOR_CONTAINER" "$identity"; then
            return 0
        else
            echo "LOT40_CLEANUP_CONTAINER_INSPECT_FAILED" >&2
            return 1
        fi
    fi
    expected_identity="$PGVECTOR_CONTAINER_ID|/$PGVECTOR_CONTAINER|$LOT40_OWNER_TOKEN"

    if ! identity="$(inspect_container_identity "$PGVECTOR_CONTAINER_ID" 2>&1)"; then
        if is_exact_not_found container "$PGVECTOR_CONTAINER_ID" "$identity"; then
            if name_identity="$(inspect_container_identity "$PGVECTOR_CONTAINER" 2>&1)"; then
                echo "LOT40_CLEANUP_CONTAINER_IDENTITY_CHANGED" >&2
                return 1
            fi
            if is_exact_not_found container "$PGVECTOR_CONTAINER" "$name_identity"; then
                return 0
            fi
        fi
        echo "LOT40_CLEANUP_CONTAINER_INSPECT_FAILED" >&2
        return 1
    fi
    if ! parse_container_identity "$identity" \
       || [[ "$identity" != "$expected_identity" ]]; then
        echo "LOT40_CLEANUP_CONTAINER_IDENTITY_CHANGED" >&2
        return 1
    fi

    if ! identity="$(inspect_container_identity "$PGVECTOR_CONTAINER_ID" 2>&1)" \
       || ! parse_container_identity "$identity" \
       || [[ "$identity" != "$expected_identity" ]]; then
        echo "LOT40_CLEANUP_CONTAINER_IDENTITY_CHANGED" >&2
        return 1
    fi

    remove_output="$(docker rm -f "$PGVECTOR_CONTAINER_ID" 2>&1)"
    remove_status=$?
    inspect_output="$(docker container inspect "$PGVECTOR_CONTAINER_ID" 2>&1)"
    inspect_status=$?
    if (( inspect_status == 0 )); then
        echo "LOT40_CLEANUP_CONTAINER_LEAK" >&2
        return 1
    fi
    if ! is_exact_not_found container "$PGVECTOR_CONTAINER_ID" "$inspect_output"; then
        echo "LOT40_CLEANUP_CONTAINER_INSPECT_FAILED" >&2
        return 1
    fi
    if (( remove_status != 0 )) \
       && ! is_exact_not_found container "$PGVECTOR_CONTAINER_ID" "$remove_output"; then
        echo "LOT40_CLEANUP_CONTAINER_REMOVE_FAILED" >&2
        return 1
    fi
    return 0
}

remove_volume_exact() {
    local identity expected_identity remove_output inspect_output
    local remove_status inspect_status

    if identity="$(inspect_volume_identity 2>&1)"; then
        if ! parse_volume_identity "$identity"; then
            echo "LOT40_CLEANUP_VOLUME_OWNERSHIP_MISMATCH" >&2
            return 1
        fi
    elif is_exact_not_found volume "$PGVECTOR_VOLUME" "$identity"; then
        return 0
    else
        echo "LOT40_CLEANUP_VOLUME_INSPECT_FAILED" >&2
        return 1
    fi

    if [[ -z "$PGVECTOR_VOLUME_CREATED_AT" ]]; then
        PGVECTOR_VOLUME_CREATED_AT="$parsed_volume_created_at"
    elif [[ "$parsed_volume_created_at" != "$PGVECTOR_VOLUME_CREATED_AT" ]]; then
        echo "LOT40_CLEANUP_VOLUME_IDENTITY_CHANGED" >&2
        return 1
    fi
    expected_identity="$LOT40_OWNER_TOKEN|$PGVECTOR_VOLUME_CREATED_AT"

    if ! identity="$(inspect_volume_identity 2>&1)" \
       || ! parse_volume_identity "$identity" \
       || [[ "$identity" != "$expected_identity" ]]; then
        echo "LOT40_CLEANUP_VOLUME_IDENTITY_CHANGED" >&2
        return 1
    fi

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

assert_resource_absent() {
    local kind="$1"
    local name="$2"
    local inspect_output

    case "$kind" in
        container)
            if inspect_output="$(docker container inspect "$name" 2>&1)"; then
                echo "LOT40_CONTAINER_NAME_COLLISION" >&2
                return 1
            fi
            ;;
        volume)
            if inspect_output="$(docker volume inspect "$name" 2>&1)"; then
                echo "LOT40_VOLUME_NAME_COLLISION" >&2
                return 1
            fi
            ;;
        *)
            echo "LOT40_RESOURCE_KIND_INVALID" >&2
            return 1
            ;;
    esac

    if ! is_exact_not_found "$kind" "$name" "$inspect_output"; then
        echo "LOT40_${kind^^}_ABSENCE_INSPECT_FAILED" >&2
        return 1
    fi
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
assert_resource_absent container "$PGVECTOR_CONTAINER"
assert_resource_absent volume "$PGVECTOR_VOLUME"
volume_cleanup_armed=1
if docker volume create --label "$LOT40_OWNER_LABEL" "$PGVECTOR_VOLUME" \
    >/dev/null 2>"$RUN_ROOT/volume-create.err"; then
    capture_volume_identity
else
    volume_create_status=$?
    echo "LOT40_VOLUME_CREATE_FAILED" >&2
    exit "$volume_create_status"
fi
container_cleanup_armed=1
if container_run_id="$(docker run -d \
        --name "$PGVECTOR_CONTAINER" \
        --label "$LOT40_OWNER_LABEL" \
        -e "POSTGRES_DB=$PGVECTOR_DB" \
        -e "POSTGRES_USER=$PGVECTOR_USER" \
        -e POSTGRES_HOST_AUTH_METHOD=trust \
        -v "$PGVECTOR_VOLUME:/var/lib/postgresql/data" \
        -v "$INFRA_DIR/postgres/init.sql:/docker-entrypoint-initdb.d/00_init.sql:ro" \
        -p 127.0.0.1::5432 \
        "$IMAGE" 2>"$RUN_ROOT/container-run.err")"; then
    capture_container_identity "$container_run_id"
else
    container_run_status=$?
    echo "LOT40_CONTAINER_RUN_FAILED" >&2
    exit "$container_run_status"
fi

ready=0
for ((attempt = 1; attempt <= ready_attempts; attempt++)); do
    if docker exec "$PGVECTOR_CONTAINER_ID" \
        pg_isready --host 127.0.0.1 --port 5432 \
        --username "$PGVECTOR_USER" --dbname "$PGVECTOR_DB" >/dev/null 2>&1; then
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

port_mapping="$(docker port "$PGVECTOR_CONTAINER_ID" 5432/tcp)"
if [[ ! "$port_mapping" =~ ^127[.]0[.]0[.]1:([0-9]+)$ ]]; then
    echo "LOT40_PORT_MAPPING_INVALID" >&2
    exit 1
fi
PGVECTOR_PORT="${BASH_REMATCH[1]}"
export LOT40_PG_ADMIN_DSN="postgresql://$PGVECTOR_USER@127.0.0.1:$PGVECTOR_PORT/$PGVECTOR_DB"
export LOT40_PG_DSN="postgresql://$PGVECTOR_APP_USER@127.0.0.1:$PGVECTOR_PORT/$PGVECTOR_DB"
export LOT41_PG_REVIEW_DSN="postgresql://$PGVECTOR_REVIEW_USER@127.0.0.1:$PGVECTOR_PORT/$PGVECTOR_DB"
export LOT42_PG_PUBLISHER_DSN="postgresql://$PGVECTOR_PUBLISHER_USER@127.0.0.1:$PGVECTOR_PORT/$PGVECTOR_DB"

echo "LOT40_DATABASE_READY=PASS"

container_psql() {
    docker exec -i "$PGVECTOR_CONTAINER_ID" \
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
    PGVECTOR_CONTAINER="$PGVECTOR_CONTAINER_ID" \
    PGVECTOR_DB="$PGVECTOR_DB" \
    PGVECTOR_USER="$PGVECTOR_USER" \
    BACKUP_ROOT="$BACKUP_ROOT" \
        bash "$1/scripts/apply_pgvector_migrations.sh"
}

run_down_002() {
    PGVECTOR_CONTAINER="$PGVECTOR_CONTAINER_ID" \
    PGVECTOR_DB="$PGVECTOR_DB" \
    PGVECTOR_USER="$PGVECTOR_USER" \
    BACKUP_ROOT="$BACKUP_ROOT" \
        bash "$1/scripts/rollback_pgvector_migration.sh" 002_hybrid_retrieval
}

run_down_003() {
    PGVECTOR_CONTAINER="$PGVECTOR_CONTAINER_ID" \
    PGVECTOR_DB="$PGVECTOR_DB" \
    PGVECTOR_USER="$PGVECTOR_USER" \
    BACKUP_ROOT="$BACKUP_ROOT" \
        bash "$1/scripts/rollback_pgvector_profile_filtering.sh" 003_profile_filtering
}

run_down_004() {
    PGVECTOR_CONTAINER="$PGVECTOR_CONTAINER_ID" \
    PGVECTOR_DB="$PGVECTOR_DB" \
    PGVECTOR_USER="$PGVECTOR_USER" \
    BACKUP_ROOT="$BACKUP_ROOT" \
        bash "$1/scripts/rollback_pgvector_artifact_placements.sh" 004_artifact_placements
}

assert_fresh_head_004() {
    container_psql <<'SQL'
SELECT version
FROM rag_schema_migrations
WHERE version = 4 AND file_name = '004_artifact_placements.sql';
SQL
}

assert_unregistered_bootstrap_002() {
    container_psql <<'SQL'
DO $$
BEGIN
    IF to_regclass('public.rag_schema_migrations') IS NOT NULL
       OR to_regclass('public.rag_chunks') IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'rag_chunks'
             AND column_name = 'text_tsv' AND is_generated = 'ALWAYS'
       )
       OR to_regclass('public.idx_rag_chunks_text_tsv') IS NULL THEN
        RAISE EXCEPTION 'LOT40_EXPECTED_UNREGISTERED_BOOTSTRAP_002';
    END IF;
END
$$;
SQL
}

sha_001="$(sha256sum "$INFRA_DIR/postgres/migrations/001_rag_chunks_v2_schema.sql" | awk '{print $1}')"
sha_002="$(sha256sum "$INFRA_DIR/postgres/migrations/002_hybrid_retrieval.sql" | awk '{print $1}')"
sha_003="$(sha256sum "$INFRA_DIR/postgres/migrations/003_profile_filtering.sql" | awk '{print $1}')"
sha_004="$(sha256sum "$INFRA_DIR/postgres/migrations/004_artifact_placements.sql" | awk '{print $1}')"

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
       OR EXISTS (SELECT 1 FROM rag_schema_migrations WHERE version = 3)
       OR EXISTS (SELECT 1 FROM rag_schema_migrations WHERE version = 4)
       OR EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'rag_chunks'
             AND column_name = 'text_tsv'
       )
       OR EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'rag_chunks'
             AND column_name IN (
                 'tenant', 'candidat', 'visibility', 'school_year',
                 'programme_version'
             )
       )
       OR to_regclass('public.idx_rag_chunks_text_tsv') IS NOT NULL
       OR to_regclass('public.idx_rag_chunks_profile_reviewed') IS NOT NULL THEN
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
       OR EXISTS (SELECT 1 FROM rag_schema_migrations WHERE version = 3)
       OR EXISTS (SELECT 1 FROM rag_schema_migrations WHERE version = 4)
       OR NOT EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'rag_chunks'
             AND column_name = 'text_tsv' AND is_generated = 'ALWAYS'
       )
       OR EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'rag_chunks'
             AND column_name IN (
                 'tenant', 'candidat', 'visibility', 'school_year',
                 'programme_version'
             )
       )
       OR to_regclass('public.idx_rag_chunks_text_tsv') IS NULL
       OR to_regclass('public.idx_rag_chunks_profile_reviewed') IS NOT NULL THEN
        RAISE EXCEPTION 'LOT40_EXPECTED_HEAD_002';
    END IF;
END
\$\$;
SQL
}

assert_state_003() {
    container_psql <<SQL
DO \$\$
BEGIN
    IF (SELECT count(*) FROM rag_schema_migrations) <> 3
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
       OR NOT EXISTS (
           SELECT 1 FROM rag_schema_migrations
           WHERE version = 3
             AND file_name = '003_profile_filtering.sql'
             AND sha256 = '$sha_003'
       )
       OR (SELECT max(version) FROM rag_schema_migrations) <> 3
       OR EXISTS (SELECT 1 FROM rag_schema_migrations WHERE version = 4)
       OR (
           SELECT count(*) FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'rag_chunks'
             AND column_name IN (
                 'tenant', 'candidat', 'visibility', 'school_year',
                 'programme_version'
             )
             AND data_type = 'text'
             AND is_nullable = 'YES'
             AND column_default IS NULL
       ) <> 5
       OR to_regclass('public.idx_rag_chunks_text_tsv') IS NULL
       OR to_regclass('public.idx_rag_chunks_profile_reviewed') IS NULL THEN
        RAISE EXCEPTION 'LOT41_EXPECTED_HEAD_003';
    END IF;
END
\$\$;
SQL
}

assert_state_004() {
    container_psql <<SQL
DO \$\$
BEGIN
    IF (SELECT count(*) FROM rag_schema_migrations) <> 4
       OR NOT EXISTS (
           SELECT 1 FROM rag_schema_migrations
           WHERE version = 4
             AND file_name = '004_artifact_placements.sql'
             AND sha256 = '$sha_004'
       )
       OR (SELECT max(version) FROM rag_schema_migrations) <> 4
       OR to_regclass('public.rag_artifacts') IS NULL
       OR to_regclass('public.rag_artifact_placements') IS NULL
       OR NOT EXISTS (
           SELECT 1 FROM information_schema.columns
           WHERE table_schema = 'public' AND table_name = 'rag_chunks'
             AND column_name = 'artifact_id'
             AND data_type = 'text' AND is_nullable = 'YES'
             AND column_default IS NULL
       )
       OR to_regclass('public.idx_rag_chunks_artifact_chunk_index_unique') IS NULL
       OR to_regclass('public.idx_rag_artifact_placements_scope_active') IS NULL THEN
        RAISE EXCEPTION 'H2C_EXPECTED_HEAD_004';
    END IF;
END
\$\$;
SQL
}

provision_app_role() {
    docker exec -i \
        -e "PGVECTOR_RETRIEVAL_USER=$PGVECTOR_APP_USER" \
        -e "PGVECTOR_RETRIEVAL_PASSWORD=$PGVECTOR_APP_PASSWORD" \
        -e "PGVECTOR_REVIEW_USER=$PGVECTOR_REVIEW_USER" \
        -e "PGVECTOR_REVIEW_PASSWORD=$PGVECTOR_REVIEW_PASSWORD" \
        -e "PGVECTOR_PUBLISHER_USER=$PGVECTOR_PUBLISHER_USER" \
        -e "PGVECTOR_PUBLISHER_PASSWORD=$PGVECTOR_PUBLISHER_PASSWORD" \
        "$PGVECTOR_CONTAINER_ID" bash -s \
        < "$INFRA_DIR/postgres/provision_runtime_roles.sh"
}

assert_unregistered_bootstrap_002
echo "BOOTSTRAP_002_UNREGISTERED=PASS"

atomic_adoption_root="$RUN_ROOT/atomic-adoption"
mkdir -p "$atomic_adoption_root"
cp -a -- "$INFRA_DIR" "$atomic_adoption_root/infra"
sed -i \
    "/# NEXUS_ADOPTION_FAILURE_INJECTION_POINT/a\\        printf '%s\\\\n' 'SELECT 1 / 0;'" \
    "$atomic_adoption_root/infra/scripts/apply_pgvector_migrations.sh"
expect_failure ATOMIC_ADOPTION_002_EXPECTED_FAILURE \
    run_apply "$atomic_adoption_root/infra"
assert_unregistered_bootstrap_002
echo "ATOMIC_ADOPTION_002_ROLLBACK=PASS"

bootstrap_adoption_output="$(run_apply "$INFRA_DIR")"
printf '%s\n' "$bootstrap_adoption_output"
grep -qx 'MIGRATIONS_ADOPTED=2' <<< "$bootstrap_adoption_output"
grep -qx 'MIGRATIONS_APPLIED=2' <<< "$bootstrap_adoption_output"
assert_state_004
echo "BOOTSTRAP_ADOPTION_002=PASS"

run_down_004 "$INFRA_DIR"
assert_state_003
run_down_003 "$INFRA_DIR"
assert_state_002
run_down_002 "$INFRA_DIR"
assert_state_001
run_apply "$INFRA_DIR"
assert_state_004
echo "BOOTSTRAP_CYCLE_004_003_002_001_004=PASS"

docker exec "$PGVECTOR_CONTAINER_ID" \
    createdb -U "$PGVECTOR_USER" -T template0 "$PGVECTOR_FRESH_DB"
PGVECTOR_DB="$PGVECTOR_FRESH_DB"

expect_failure FRESH_HEAD_004_NEGATIVE assert_fresh_head_004

run_apply "$INFRA_DIR"
assert_state_004
run_down_004 "$INFRA_DIR"
assert_state_003
run_down_003 "$INFRA_DIR"
assert_state_002
run_down_002 "$INFRA_DIR"
assert_state_001
run_apply "$INFRA_DIR"
assert_state_004
echo "MIGRATION_CYCLE_001_002_003_004_003_002_001_004=PASS"

run_down_004 "$INFRA_DIR"
assert_state_003
atomic_up_root="$RUN_ROOT/atomic-up"
mkdir -p "$atomic_up_root"
cp -a -- "$INFRA_DIR" "$atomic_up_root/infra"
printf '\nSELECT 1 / 0;\n' \
    >> "$atomic_up_root/infra/postgres/migrations/004_artifact_placements.sql"
expect_failure ATOMIC_UP_EXPECTED_FAILURE run_apply "$atomic_up_root/infra"
assert_state_003
echo "ATOMIC_UP_ROLLBACK=PASS"

run_apply "$INFRA_DIR"
assert_state_004
atomic_down_root="$RUN_ROOT/atomic-down"
mkdir -p "$atomic_down_root"
cp -a -- "$INFRA_DIR" "$atomic_down_root/infra"
printf '\nSELECT 1 / 0;\n' \
    >> "$atomic_down_root/infra/postgres/rollbacks/004_artifact_placements.down.sql"
expect_failure ATOMIC_DOWN_EXPECTED_FAILURE run_down_004 "$atomic_down_root/infra"
assert_state_004
echo "ATOMIC_DOWN_ROLLBACK=PASS"

container_psql <<'SQL'
INSERT INTO rag_artifacts (
    artifact_id, content_sha256, source_label, source_uri, rights,
    source_kind, type_doc, ingestion_artifact_id
) VALUES (
    repeat('a', 64), repeat('a', 64), 'H2-C rollback guard',
    'urn:nexus:h2c:rollback-guard', 'usage_interne', 'test', 'cours',
    '00000000-0000-0000-0000-000000000004'
);
SQL
expect_failure ROLLBACK_004_GOVERNED_DATA_REFUSED run_down_004 "$INFRA_DIR"
assert_state_004
container_psql <<'SQL'
DELETE FROM rag_artifacts WHERE artifact_id = repeat('a', 64);
SQL
echo "ROLLBACK_004_DATA_GUARD=PASS"

run_down_004 "$INFRA_DIR"
assert_state_003
container_psql <<'SQL'
INSERT INTO rag_chunks (
    chunk_id, doc_id, chunk_sha256, collection, niveau, matiere,
    source_label, source_uri, rights, type_doc, tenant
) VALUES (
    'lot41-rollback-guard', 'lot41-rollback-guard',
    'lot41-rollback-guard-sha', 'lot41-guard', 'terminale', 'maths',
    'LOT41 rollback guard', 'urn:nexus:lot41:rollback-guard', 'internal',
    'test', 'libre_terminale'
);
SQL
expect_failure ROLLBACK_003_ENRICHED_DATA_REFUSED run_down_003 "$INFRA_DIR"
assert_state_003
container_psql <<'SQL'
DELETE FROM rag_chunks WHERE chunk_id = 'lot41-rollback-guard';
SQL
echo "ROLLBACK_003_DATA_GUARD=PASS"
run_apply "$INFRA_DIR"
assert_state_004
echo "MIGRATION_FINAL_HEAD_004=PASS"

PGVECTOR_DB="$PGVECTOR_BOOTSTRAP_DB"
provision_app_role
echo "APP_ROLE_LEAST_PRIVILEGE=PASS"

if [[ ! -x "$PYTEST_BIN" ]]; then
    echo "LOT40_PYTEST_BIN_INVALID" >&2
    exit 1
fi
integration_tests=(
    "$SERVICE_ROOT/tests/integration/test_lot40_hybrid_pgvector.py"
)
lot40_integration_executed=1
if [[ -n "${NEXUS_H2C_REHEARSAL_ONLY:-}" ]]; then
    if [[ -z "${NEXUS_H2C_REAL_REHEARSAL:-}" ]]; then
        echo "H2C_REHEARSAL_ONLY_REQUIRES_REAL_INPUTS" >&2
        exit 1
    fi
    integration_tests=()
    lot40_integration_executed=0
fi
if [[ -n "${NEXUS_H2C_REAL_REHEARSAL:-}" ]]; then
    integration_tests+=(
        "$SERVICE_ROOT/tests/integration/test_h2c_governed_rehearsal.py"
    )
fi
LOT40_PG_DSN="$LOT40_PG_DSN" \
LOT40_PG_ADMIN_DSN="$LOT40_PG_ADMIN_DSN" \
LOT41_PG_REVIEW_DSN="$LOT41_PG_REVIEW_DSN" \
LOT42_PG_PUBLISHER_DSN="$LOT42_PG_PUBLISHER_DSN" \
DRIVE_SYNC_DB_PATH="$RUN_ROOT/drive_sync_state.db" \
PYTHONPATH="$SERVICE_ROOT/src" "$PYTEST_BIN" "${integration_tests[@]}" -q -s

assert_state_004
if (( lot40_integration_executed == 1 )); then
    echo "LOT40_HYBRID_INTEGRATION=PASS"
else
    echo "H2E_V2_GOVERNED_REHEARSAL=PASS"
fi
