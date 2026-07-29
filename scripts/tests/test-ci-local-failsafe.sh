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
if [ "$#" -ne 2 ] || [ "$1" != "-c" ]; then
    exit 90
fi
case "$2" in
    *"sys.version_info >= (3, 11)"*)
        printf '%s\n' "python3.10-threshold-checked" > "$FAKE_PYTHON_CALL_LOG"
        ;;
    *)
        exit 91
        ;;
esac
exit 1
SCRIPT
chmod +x "$TMPDIR_CI/python3.10"

FAKE_PYTHON_CALL_LOG="$TMPDIR_CI/python3.10.call"
export FAKE_PYTHON_CALL_LOG
set +e
require_python_311 "$TMPDIR_CI/python3.10"
PYTHON_310_EXIT=$?
set -e

if [ "$PYTHON_310_EXIT" -ne 0 ] \
    && [ "$(cat "$FAKE_PYTHON_CALL_LOG" 2>/dev/null)" = "python3.10-threshold-checked" ]; then
    echo "  PASS  Python 3.10 is rejected after checking the 3.11 threshold"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  Python 3.10 threshold check was not invoked exactly"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=== Test: require_python_311 accepts Python 3.11 ==="

cat > "$TMPDIR_CI/python3.11" <<'SCRIPT'
#!/usr/bin/env bash
if [ "$#" -ne 2 ] || [ "$1" != "-c" ]; then
    exit 90
fi
case "$2" in
    *"sys.version_info >= (3, 11)"*)
        printf '%s\n' "python3.11-threshold-checked" > "$FAKE_PYTHON_CALL_LOG"
        ;;
    *)
        exit 91
        ;;
esac
exit 0
SCRIPT
chmod +x "$TMPDIR_CI/python3.11"

FAKE_PYTHON_CALL_LOG="$TMPDIR_CI/python3.11.call"
export FAKE_PYTHON_CALL_LOG
set +e
require_python_311 "$TMPDIR_CI/python3.11"
PYTHON_311_EXIT=$?
set -e

if [ "$PYTHON_311_EXIT" -eq 0 ] \
    && [ "$(cat "$FAKE_PYTHON_CALL_LOG" 2>/dev/null)" = "python3.11-threshold-checked" ]; then
    echo "  PASS  Python 3.11 is accepted after checking the 3.11 threshold"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  Python 3.11 threshold check was not invoked exactly (exit $PYTHON_311_EXIT)"
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
echo "=== Test: ci-local.sh fails closed when ci-common.sh cannot be sourced ==="

SOURCE_FAILURE_ROOT="$TMPDIR_CI/source-failure"
mkdir -p "$SOURCE_FAILURE_ROOT/scripts/lib"
cp "$REPO_ROOT/scripts/ci-local.sh" "$SOURCE_FAILURE_ROOT/scripts/ci-local.sh"
cat > "$SOURCE_FAILURE_ROOT/scripts/lib/ci-common.sh" <<'SCRIPT'
return 42
SCRIPT

set +e
SOURCE_FAILURE_OUTPUT=$(bash "$SOURCE_FAILURE_ROOT/scripts/ci-local.sh" 2>&1)
SOURCE_FAILURE_EXIT=$?
set -e

if [ "$SOURCE_FAILURE_EXIT" -ne 0 ] \
    && echo "$SOURCE_FAILURE_OUTPUT" \
        | grep -q "ERROR: unable to source scripts/lib/ci-common.sh"; then
    echo "  PASS  ci-local.sh reports the source failure and exits non-zero"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  ci-local.sh did not fail closed explicitly"
    echo "$SOURCE_FAILURE_OUTPUT"
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
