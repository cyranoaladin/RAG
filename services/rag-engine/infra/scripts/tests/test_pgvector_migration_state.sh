#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LIBRARY="$SCRIPT_DIR/../lib/pgvector_migration_state.sh"

if [[ ! -f "$LIBRARY" ]]; then
    echo "FAIL: migration state library is missing" >&2
    exit 1
fi

# shellcheck source=../lib/pgvector_migration_state.sh
source "$LIBRARY"

TEST_ROOT="$(mktemp -d)"
trap 'rm -rf "$TEST_ROOT"' EXIT

fail() {
    echo "FAIL: $*" >&2
    exit 1
}

new_manifest() {
    local name="$1"
    local dir="$TEST_ROOT/$name"
    mkdir -p "$dir"
    printf '%s\n' "$dir"
}

assert_rejected() {
    local expected="$1"
    local dir="$2"
    local head_file="$3"
    local output

    if output="$(discover_manifest "$dir" "$head_file" 2>&1)"; then
        fail "manifest unexpectedly accepted: $expected"
    fi
    [[ "$output" == *"$expected"* ]] || fail "missing diagnostic $expected: $output"
}

nominal="$(new_manifest nominal)"
printf 'SELECT 1;\n' > "$nominal/001_rag_chunks_v2_schema.sql"
printf 'SELECT 2;\n' > "$nominal/002_hybrid_retrieval.sql"
printf '002_hybrid_retrieval\n' > "$nominal/HEAD"
discover_manifest "$nominal" "$nominal/HEAD"
[[ "${MIGRATION_VERSIONS[*]}" == "1 2" ]] || fail "unexpected versions"
[[ "${MIGRATION_NAMES[*]}" == "001_rag_chunks_v2_schema.sql 002_hybrid_retrieval.sql" ]] \
    || fail "unexpected names"
[[ "${MIGRATION_FILES[0]}" == "$nominal/001_rag_chunks_v2_schema.sql" ]] \
    || fail "unexpected first path"
[[ "${#MIGRATION_SHA256[@]}" -eq 2 ]] || fail "unexpected hash count"
for digest in "${MIGRATION_SHA256[@]}"; do
    [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "invalid sha256: $digest"
done

gap="$(new_manifest gap)"
printf 'SELECT 1;\n' > "$gap/001_first.sql"
printf 'SELECT 3;\n' > "$gap/003_third.sql"
printf '003_third\n' > "$gap/HEAD"
assert_rejected "MIGRATION_GAP" "$gap" "$gap/HEAD"

duplicate="$(new_manifest duplicate)"
printf 'SELECT 1;\n' > "$duplicate/001_first.sql"
printf 'SELECT 1;\n' > "$duplicate/001_second.sql"
printf '001_second\n' > "$duplicate/HEAD"
assert_rejected "MIGRATION_DUPLICATE" "$duplicate" "$duplicate/HEAD"

invalid="$(new_manifest invalid)"
printf 'SELECT 1;\n' > "$invalid/001_VALID.sql"
printf '001_VALID\n' > "$invalid/HEAD"
assert_rejected "MIGRATION_NAME_INVALID" "$invalid" "$invalid/HEAD"

missing_head="$(new_manifest missing-head)"
printf 'SELECT 1;\n' > "$missing_head/001_first.sql"
assert_rejected "MIGRATION_HEAD_MISSING" "$missing_head" "$missing_head/HEAD"

wrong_head="$(new_manifest wrong-head)"
printf 'SELECT 1;\n' > "$wrong_head/001_first.sql"
printf 'something_else\n' > "$wrong_head/HEAD"
assert_rejected "MIGRATION_HEAD_INVALID" "$wrong_head" "$wrong_head/HEAD"

non_regular="$(new_manifest non-regular)"
printf 'SELECT 1;\n' > "$non_regular/001_first.sql"
ln -s "$non_regular/001_first.sql" "$non_regular/002_second.sql"
printf '002_second\n' > "$non_regular/HEAD"
assert_rejected "MIGRATION_FILE_NOT_REGULAR" "$non_regular" "$non_regular/HEAD"

echo "PASS: migration manifest state"
