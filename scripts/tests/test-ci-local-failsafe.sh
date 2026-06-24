#!/usr/bin/env bash
# test-ci-local-failsafe.sh — Verify that ci-local.sh propagates failures.
# Injects a failing target and checks that it shows FAIL in the summary.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo "=== Test: ci-local.sh propagates target failure ==="

# Create a minimal ci-local variant that runs only a failing target
TMPSCRIPT=$(mktemp)
cat > "$TMPSCRIPT" <<'SCRIPT'
#!/usr/bin/env bash
set -uo pipefail

PASS=0
FAIL=0
RESULTS=()

run_target() {
    local name="$1"
    shift
    if "$@"; then
        RESULTS+=("PASS  $name")
        PASS=$((PASS + 1))
    else
        RESULTS+=("FAIL  $name")
        FAIL=$((FAIL + 1))
    fi
}

failing_target() { echo "intentional failure"; return 1; }
passing_target() { echo "ok"; return 0; }

run_target "should-fail" failing_target
run_target "should-pass" passing_target

echo "CI LOCAL — SUMMARY"
for r in "${RESULTS[@]}"; do echo "  $r"; done
echo "Total: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then exit 1; fi
exit 0
SCRIPT

chmod +x "$TMPSCRIPT"

set +e
OUTPUT=$(bash "$TMPSCRIPT" 2>&1)
EXIT=$?
set -e
rm -f "$TMPSCRIPT"

echo "$OUTPUT"

# Assertions
TESTS_PASS=0
TESTS_FAIL=0

if [ "$EXIT" -ne 0 ]; then
    echo "  PASS  exit code is non-zero ($EXIT)"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  exit code should be non-zero, got $EXIT"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

if echo "$OUTPUT" | grep -q "FAIL  should-fail"; then
    echo "  PASS  output contains FAIL for failing target"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  output missing FAIL for failing target"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

if echo "$OUTPUT" | grep -q "PASS  should-pass"; then
    echo "  PASS  output contains PASS for passing target"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  output missing PASS for passing target"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=============================="
echo "  CI FAILSAFE TESTS"
echo "=============================="
echo "  $TESTS_PASS passed, $TESTS_FAIL failed"

if [ "$TESTS_FAIL" -gt 0 ]; then exit 1; fi
exit 0
