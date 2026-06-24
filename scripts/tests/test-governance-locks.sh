#!/usr/bin/env bash
# test-governance-locks.sh — Test suite for the governance locks guard script.
# Uses temporary fixtures passed via GOVERNANCE_CONTRACT_FILE / GOVERNANCE_BASELINE_FILE.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD_SCRIPT="$SCRIPT_DIR/../check-governance-locks.sh"

PASS=0
FAIL=0
TOTAL=0

assert_exit() {
    local name="$1"
    local expected="$2"
    local actual="$3"
    TOTAL=$((TOTAL + 1))
    if [ "$actual" -eq "$expected" ]; then
        echo "  PASS  $name (exit $actual)"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name (expected exit $expected, got $actual)"
        FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local name="$1"
    local output="$2"
    local pattern="$3"
    TOTAL=$((TOTAL + 1))
    if echo "$output" | grep -q "$pattern"; then
        echo "  PASS  $name (output contains '$pattern')"
        PASS=$((PASS + 1))
    else
        echo "  FAIL  $name (output missing '$pattern')"
        FAIL=$((FAIL + 1))
    fi
}

# Run the guard script capturing both output and exit code
run_guard() {
    local contract="$1"
    local baseline="$2"
    local output
    local exit_code
    set +e
    output=$(GOVERNANCE_CONTRACT_FILE="$contract" GOVERNANCE_BASELINE_FILE="$baseline" bash "$GUARD_SCRIPT" 2>&1)
    exit_code=$?
    set -e
    LAST_OUTPUT="$output"
    LAST_EXIT="$exit_code"
}

TMPDIR_TEST=$(mktemp -d)
trap 'rm -rf "$TMPDIR_TEST"' EXIT

# --- Fixtures ---
BASELINE="$TMPDIR_TEST/baseline"
cat > "$BASELINE" <<'EOF'
chunking_allowed: false
embeddings_allowed: false
parsing_allowed: false
EOF

# ============================================================
echo ""
echo "=== Test 1: Nominal (contract == baseline) ==="
CONTRACT="$TMPDIR_TEST/contract_nominal.yml"
cat > "$CONTRACT" <<'EOF'
chunking_allowed: false
embeddings_allowed: false
parsing_allowed: false
EOF
run_guard "$CONTRACT" "$BASELINE"
echo "$LAST_OUTPUT"
assert_exit "nominal_exit" 0 "$LAST_EXIT"
assert_contains "nominal_msg" "$LAST_OUTPUT" "all governance locks intact"

# ============================================================
echo ""
echo "=== Test 2: Lock removed ==="
CONTRACT="$TMPDIR_TEST/contract_removed.yml"
cat > "$CONTRACT" <<'EOF'
embeddings_allowed: false
parsing_allowed: false
EOF
run_guard "$CONTRACT" "$BASELINE"
echo "$LAST_OUTPUT"
assert_exit "removed_exit" 1 "$LAST_EXIT"
assert_contains "removed_msg" "$LAST_OUTPUT" "chunking_allowed: false"

# ============================================================
echo ""
echo "=== Test 3: Swap (same count, different key) ==="
CONTRACT="$TMPDIR_TEST/contract_swap.yml"
cat > "$CONTRACT" <<'EOF'
embeddings_allowed: false
parsing_allowed: false
network_allowed: false
EOF
run_guard "$CONTRACT" "$BASELINE"
echo "$LAST_OUTPUT"
assert_exit "swap_exit" 1 "$LAST_EXIT"
assert_contains "swap_missing" "$LAST_OUTPUT" "chunking_allowed: false"

# ============================================================
echo ""
echo "=== Test 4: Zero locks (empty grep) ==="
CONTRACT="$TMPDIR_TEST/contract_empty.yml"
cat > "$CONTRACT" <<'EOF'
chunking_allowed: true
embeddings_allowed: true
parsing_allowed: true
EOF
run_guard "$CONTRACT" "$BASELINE"
echo "$LAST_OUTPUT"
assert_exit "zero_exit" 1 "$LAST_EXIT"
assert_contains "zero_msg" "$LAST_OUTPUT" "missing or weakened"

# ============================================================
echo ""
echo "=== Test 5: ADR exception (manual verification) ==="
echo "  SKIP  ADR exception requires git state; verified manually in lot-0.2 report."
echo "         (swap+ADR on added line -> exit 0)"

# ============================================================
echo ""
echo "=============================="
echo "  GOVERNANCE GUARD TESTS"
echo "=============================="
echo "  $PASS passed, $FAIL failed, $TOTAL total (1 skipped: ADR exception)"
echo ""

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
