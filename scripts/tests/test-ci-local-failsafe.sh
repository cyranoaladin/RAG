#!/usr/bin/env bash
# test-ci-local-failsafe.sh — Verify that ci-local.sh propagates failures.
# Injects a failing target and checks that it shows FAIL in the summary.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
COMMON_LIB="$REPO_ROOT/scripts/lib/ci-common.sh"

TESTS_PASS=0
TESTS_FAIL=0

if ! source "$COMMON_LIB"; then
    echo "  FAIL  unable to source scripts/lib/ci-common.sh"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

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
echo "=== Test: require_python_311 rejects Python 3.10 ==="

TMPDIR_CI=$(mktemp -d)
trap 'rm -rf "$TMPDIR_CI"' EXIT

cat > "$TMPDIR_CI/python3.10" <<'SCRIPT'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then
    echo "Python 3.10.14"
    exit 0
fi
exit 1
SCRIPT
chmod +x "$TMPDIR_CI/python3.10"

set +e
require_python_311 "$TMPDIR_CI/python3.10"
PYTHON_310_EXIT=$?
set -e

if [ "$PYTHON_310_EXIT" -ne 0 ]; then
    echo "  PASS  Python 3.10 is rejected"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  Python 3.10 should be rejected"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=== Test: require_python_311 accepts Python 3.11 ==="

cat > "$TMPDIR_CI/python3.11" <<'SCRIPT'
#!/usr/bin/env bash
if [ "${1:-}" = "--version" ]; then
    echo "Python 3.11.9"
    exit 0
fi
exit 0
SCRIPT
chmod +x "$TMPDIR_CI/python3.11"

set +e
require_python_311 "$TMPDIR_CI/python3.11"
PYTHON_311_EXIT=$?
set -e

if [ "$PYTHON_311_EXIT" -eq 0 ]; then
    echo "  PASS  Python 3.11 is accepted"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  Python 3.11 should be accepted (exit $PYTHON_311_EXIT)"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=== Test: run_checked propagates command exit code ==="

returns_seven() { return 7; }

set +e
run_checked returns_seven
RUN_CHECKED_EXIT=$?
set -e

if [ "$RUN_CHECKED_EXIT" -eq 7 ]; then
    echo "  PASS  run_checked propagated exit code 7"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  run_checked returned $RUN_CHECKED_EXIT instead of 7"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=== Test: no pre-existing failure tolerance remains ==="

if ! grep -q 'pre-existing failure(s) — acceptable' "$REPO_ROOT/scripts/ci-local.sh"; then
    echo "  PASS  ci-local.sh contains no accepted-failure exception"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  ci-local.sh still accepts pre-existing failures"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=============================="
echo "  CI FAILSAFE TESTS"
echo "=============================="
echo "  $TESTS_PASS passed, $TESTS_FAIL failed"

if [ "$TESTS_FAIL" -gt 0 ]; then exit 1; fi
exit 0
