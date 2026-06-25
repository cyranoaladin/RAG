#!/usr/bin/env bash
# test-governance-locks.sh — Test suite for the governance locks guard script.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GUARD_SCRIPT="$SCRIPT_DIR/../check-governance-locks.sh"

PASS=0
FAIL=0
TOTAL=0

assert_exit() {
    local name="$1" expected="$2" actual="$3"
    TOTAL=$((TOTAL + 1))
    if [ "$actual" -eq "$expected" ]; then
        echo "  PASS  $name (exit $actual)"; PASS=$((PASS + 1))
    else
        echo "  FAIL  $name (expected exit $expected, got $actual)"; FAIL=$((FAIL + 1))
    fi
}

assert_contains() {
    local name="$1" output="$2" pattern="$3"
    TOTAL=$((TOTAL + 1))
    if echo "$output" | grep -q "$pattern"; then
        echo "  PASS  $name (contains '$pattern')"; PASS=$((PASS + 1))
    else
        echo "  FAIL  $name (missing '$pattern')"; FAIL=$((FAIL + 1))
    fi
}

run_guard() {
    local exit_code
    set +e
    LAST_OUTPUT=$(GOVERNANCE_CONTRACT_FILE="$1" GOVERNANCE_BASELINE_FILE="$2" bash "$GUARD_SCRIPT" 2>&1)
    exit_code=$?
    set -e
    LAST_EXIT="$exit_code"
}

TMPDIR_TEST=$(mktemp -d)
trap 'rm -rf "$TMPDIR_TEST"' EXIT

# ============================================================
echo ""
echo "=== Test 1: Nominal (config == baseline, all false) ==="
BASELINE="$TMPDIR_TEST/bl1"
CONTRACT="$TMPDIR_TEST/ct1.yml"
cat > "$BASELINE" <<'EOF'
chunking_allowed: false
embeddings_allowed: false
parsing_allowed: false
EOF
cp "$BASELINE" "$CONTRACT"
run_guard "$CONTRACT" "$BASELINE"
echo "$LAST_OUTPUT"
assert_exit "nominal_exit" 0 "$LAST_EXIT"
assert_contains "nominal_msg" "$LAST_OUTPUT" "all governance locks match baseline"

# ============================================================
echo ""
echo "=== Test 2: Lock removed from config ==="
CONTRACT="$TMPDIR_TEST/ct2.yml"
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
CONTRACT="$TMPDIR_TEST/ct3.yml"
cat > "$CONTRACT" <<'EOF'
embeddings_allowed: false
parsing_allowed: false
network_allowed: false
EOF
run_guard "$CONTRACT" "$BASELINE"
echo "$LAST_OUTPUT"
assert_exit "swap_exit" 1 "$LAST_EXIT"
assert_contains "swap_msg" "$LAST_OUTPUT" "chunking_allowed: false"

# ============================================================
echo ""
echo "=== Test 4: All locks flipped to true ==="
CONTRACT="$TMPDIR_TEST/ct4.yml"
cat > "$CONTRACT" <<'EOF'
chunking_allowed: true
embeddings_allowed: true
parsing_allowed: true
EOF
run_guard "$CONTRACT" "$BASELINE"
echo "$LAST_OUTPUT"
assert_exit "allflip_exit" 1 "$LAST_EXIT"
assert_contains "allflip_msg" "$LAST_OUTPUT" "deviate"

# ============================================================
echo ""
echo "=== Test 5: Nominal with authorized true (ADR on baseline line) ==="
BASELINE5="$TMPDIR_TEST/bl5"
CONTRACT5="$TMPDIR_TEST/ct5.yml"
cat > "$BASELINE5" <<'EOF'
chunking_allowed: false
network_allowed: true  # ADR-0004
parsing_allowed: false
EOF
cat > "$CONTRACT5" <<'EOF'
chunking_allowed: false
network_allowed: true  # ADR-0004
parsing_allowed: false
EOF
run_guard "$CONTRACT5" "$BASELINE5"
echo "$LAST_OUTPUT"
assert_exit "auth_true_exit" 0 "$LAST_EXIT"
assert_contains "auth_true_msg" "$LAST_OUTPUT" "all governance locks match baseline"

# ============================================================
echo ""
echo "=== Test 6: FLAW — second lock activated while ADR exists elsewhere ==="
echo "    (ingestion_allowed:true in config, baseline has it false)"
BASELINE6="$TMPDIR_TEST/bl6"
CONTRACT6="$TMPDIR_TEST/ct6.yml"
cat > "$BASELINE6" <<'EOF'
chunking_allowed: false
ingestion_allowed: false
network_allowed: true  # ADR-0004
parsing_allowed: false
EOF
cat > "$CONTRACT6" <<'EOF'
chunking_allowed: false
ingestion_allowed: true
network_allowed: true  # ADR-0004
parsing_allowed: false
EOF
run_guard "$CONTRACT6" "$BASELINE6"
echo "$LAST_OUTPUT"
assert_exit "flaw_exit" 1 "$LAST_EXIT"
assert_contains "flaw_msg" "$LAST_OUTPUT" "ingestion_allowed"

# ============================================================
echo ""
echo "=== Test 7: Baseline has true WITHOUT ADR ==="
BASELINE7="$TMPDIR_TEST/bl7"
CONTRACT7="$TMPDIR_TEST/ct7.yml"
cat > "$BASELINE7" <<'EOF'
chunking_allowed: false
network_allowed: true
parsing_allowed: false
EOF
cat > "$CONTRACT7" <<'EOF'
chunking_allowed: false
network_allowed: true
parsing_allowed: false
EOF
run_guard "$CONTRACT7" "$BASELINE7"
echo "$LAST_OUTPUT"
assert_exit "noADR_exit" 1 "$LAST_EXIT"
assert_contains "noADR_msg" "$LAST_OUTPUT" "without ADR"

# ============================================================
echo ""
echo "=============================="
echo "  GOVERNANCE GUARD TESTS"
echo "=============================="
echo "  $PASS passed, $FAIL failed, $TOTAL total"
echo ""

if [ "$FAIL" -gt 0 ]; then exit 1; fi
exit 0
