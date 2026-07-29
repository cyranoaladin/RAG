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

extract_shell_function() {
    local function_name="$1"
    local source_file="$2"

    awk -v signature="${function_name}() {" '
        $0 == signature {
            in_function = 1
        }
        in_function {
            print
        }
        in_function && $0 == "}" {
            exit
        }
    ' "$source_file"
}

extract_yaml_job() {
    local job_name="$1"
    local workflow_file="$2"

    awk -v signature="  ${job_name}:" '
        $0 == signature {
            in_job = 1
        }
        in_job && $0 != signature && $0 ~ /^  [a-zA-Z0-9_-]+:$/ {
            exit
        }
        in_job {
            print
        }
    ' "$workflow_file"
}

assert_cockpit_commands() {
    local block_label="$1"
    local block="$2"
    local missing=()
    local command

    for command in \
        "npm ci" \
        "npm run lint" \
        "npm test -- --run" \
        "npm run build" \
        "npm audit --omit=dev" \
        "bash scripts/tests/test-cockpit-clean-build.sh"; do
        if ! grep -Fq -- "$command" <<<"$block"; then
            missing+=("$command")
        fi
    done

    if ! grep -Eq \
        '^[[:space:]]*((-[[:space:]]+)?run:[[:space:]]*)?npm audit[[:space:]]*$' \
        <<<"$block"; then
        missing+=("npm audit (complet)")
    fi

    if [ -n "$block" ] && [ "${#missing[@]}" -eq 0 ]; then
        echo "  PASS  $block_label contient tous les contrôles cockpit requis"
        TESTS_PASS=$((TESTS_PASS + 1))
    else
        echo "  FAIL  $block_label est absent ou incomplet"
        for command in "${missing[@]}"; do
            echo "        commande manquante: $command"
        done
        TESTS_FAIL=$((TESTS_FAIL + 1))
    fi
}

echo ""
echo "=== Test: run_cockpit contient uniquement ses contrôles requis ==="

RUN_COCKPIT_BLOCK="$(
    extract_shell_function "run_cockpit" "$REPO_ROOT/scripts/ci-local.sh"
)"
assert_cockpit_commands "run_cockpit()" "$RUN_COCKPIT_BLOCK"

if grep -Fq 'require_node_2222 "$NODE_BIN"' <<<"$RUN_COCKPIT_BLOCK" \
    && grep -Fq 'run_target "services/cockpit" run_cockpit' \
        "$REPO_ROOT/scripts/ci-local.sh"; then
    echo "  PASS  le target cockpit applique le garde-fou Node"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  le target cockpit ou son garde-fou Node est absent"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=== Test: le job YAML cockpit contient uniquement ses contrôles requis ==="

COCKPIT_JOB_BLOCK="$(
    extract_yaml_job "cockpit" "$REPO_ROOT/.github/workflows/ci.yml"
)"
assert_cockpit_commands "jobs.cockpit" "$COCKPIT_JOB_BLOCK"

if grep -Fq "actions/setup-node@v4" <<<"$COCKPIT_JOB_BLOCK" \
    && grep -Fq "node-version-file: .nvmrc" <<<"$COCKPIT_JOB_BLOCK" \
    && grep -Fq "cache: npm" <<<"$COCKPIT_JOB_BLOCK" \
    && grep -Fq "cache-dependency-path: services/cockpit/package-lock.json" \
        <<<"$COCKPIT_JOB_BLOCK"; then
    echo "  PASS  le job cockpit utilise .nvmrc et le cache du lockfile"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  la configuration Node/cache du job cockpit est absente"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

if [ "$(cat "$REPO_ROOT/.nvmrc" 2>/dev/null)" = "22.22.0" ]; then
    echo "  PASS  .nvmrc fixe Node 22.22.0"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  .nvmrc doit contenir exactement 22.22.0"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

create_fake_node() {
    local path="$1"
    local version="$2"
    cat > "$path" <<SCRIPT
#!/usr/bin/env bash
if [ "\$#" -ne 1 ] || [ "\$1" != "--version" ]; then
    exit 90
fi
printf '%s\n' "$version"
printf '%s\n' "--version" > "\$FAKE_NODE_CALL_LOG"
SCRIPT
    chmod +x "$path"
}

echo ""
echo "=== Test: require_node_2222 rejette Node 22.21 ==="

create_fake_node "$TMPDIR_CI/node-22.21" "v22.21.0"
FAKE_NODE_CALL_LOG="$TMPDIR_CI/node-22.21.call"
export FAKE_NODE_CALL_LOG
set +e
require_node_2222 "$TMPDIR_CI/node-22.21"
NODE_2221_EXIT=$?
set -e

if [ "$NODE_2221_EXIT" -ne 0 ] \
    && [ "$(cat "$FAKE_NODE_CALL_LOG" 2>/dev/null)" = "--version" ]; then
    echo "  PASS  Node 22.21 est rejeté après lecture de sa version"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  Node 22.21 doit être interrogé puis rejeté"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=== Test: require_node_2222 accepte Node 22.22 ==="

create_fake_node "$TMPDIR_CI/node-22.22" "v22.22.0"
FAKE_NODE_CALL_LOG="$TMPDIR_CI/node-22.22.call"
export FAKE_NODE_CALL_LOG
set +e
require_node_2222 "$TMPDIR_CI/node-22.22"
NODE_2222_EXIT=$?
set -e

if [ "$NODE_2222_EXIT" -eq 0 ] \
    && [ "$(cat "$FAKE_NODE_CALL_LOG" 2>/dev/null)" = "--version" ]; then
    echo "  PASS  Node 22.22 est accepté après lecture de sa version"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  Node 22.22 doit être interrogé puis accepté"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=== Test: ci-local.sh s'arrête avant npm avec Node incompatible ==="

NODE_FAILURE_ROOT="$TMPDIR_CI/node-failure"
mkdir -p "$NODE_FAILURE_ROOT/scripts/lib" "$NODE_FAILURE_ROOT/bin"
cp "$REPO_ROOT/scripts/ci-local.sh" "$NODE_FAILURE_ROOT/scripts/ci-local.sh"
cp "$COMMON_LIB" "$NODE_FAILURE_ROOT/scripts/lib/ci-common.sh"
create_fake_node "$NODE_FAILURE_ROOT/bin/node" "v22.21.0"
cat > "$NODE_FAILURE_ROOT/bin/python3.11" <<'SCRIPT'
#!/usr/bin/env bash
if [ "$1" = "--version" ]; then
    echo "Python 3.11.0"
    exit 0
fi
if [ "$#" -eq 2 ] && [ "$1" = "-c" ]; then
    exit 0
fi
exit 90
SCRIPT
cat > "$NODE_FAILURE_ROOT/bin/npm" <<'SCRIPT'
#!/usr/bin/env bash
printf '%s\n' "npm-called" > "$FAKE_NPM_CALL_LOG"
exit 99
SCRIPT
chmod +x "$NODE_FAILURE_ROOT/bin/python3.11" "$NODE_FAILURE_ROOT/bin/npm"

FAKE_NODE_CALL_LOG="$NODE_FAILURE_ROOT/node.call"
FAKE_NPM_CALL_LOG="$NODE_FAILURE_ROOT/npm.call"
export FAKE_NODE_CALL_LOG FAKE_NPM_CALL_LOG
set +e
NODE_FAILURE_OUTPUT="$(
    PATH="$NODE_FAILURE_ROOT/bin:$PATH" \
        bash "$NODE_FAILURE_ROOT/scripts/ci-local.sh" 2>&1
)"
NODE_FAILURE_EXIT=$?
set -e

if [ "$NODE_FAILURE_EXIT" -ne 0 ] \
    && grep -Fq "ERROR: Node 22.22+ is required" <<<"$NODE_FAILURE_OUTPUT" \
    && [ ! -e "$FAKE_NPM_CALL_LOG" ]; then
    echo "  PASS  la CI locale rejette Node 22.21 avant tout appel npm"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  la CI locale n'a pas échoué avant npm avec Node 22.21"
    echo "$NODE_FAILURE_OUTPUT"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=============================="
echo "  CI FAILSAFE TESTS"
echo "=============================="
echo "  $TESTS_PASS passed, $TESTS_FAIL failed"

if [ "$TESTS_FAIL" -gt 0 ]; then exit 1; fi
exit 0
