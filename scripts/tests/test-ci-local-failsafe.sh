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

block_has_exact_command() {
    local block="$1"
    local expected="$2"

    awk -v expected="$expected" '
        {
            line = $0
            sub(/^[[:space:]]+/, "", line)
            sub(/[[:space:]]+$/, "", line)
            if (line == expected) {
                found = 1
            }
        }
        END {
            exit(found ? 0 : 1)
        }
    ' <<<"$block"
}

validate_shell_cockpit_commands() {
    local block_label="$1"
    local block="$2"
    local missing=()
    local command

    for command in \
        "npm ci" \
        "npm run lint" \
        "npm test -- --run" \
        "npm run build" \
        "npm audit" \
        "npm audit --omit=dev" \
        "bash scripts/tests/test-cockpit-clean-build.sh"; do
        if ! block_has_exact_command "$block" "$command"; then
            missing+=("$command")
        fi
    done

    if [ -n "$block" ] && [ "${#missing[@]}" -eq 0 ]; then
        return 0
    else
        echo "$block_label est absent ou incomplet"
        for command in "${missing[@]}"; do
            echo "commande manquante: $command"
        done
        return 1
    fi
}

assert_shell_cockpit_commands() {
    local block_label="$1"
    local block="$2"
    local validation_output

    if validation_output="$(
        validate_shell_cockpit_commands "$block_label" "$block"
    )"; then
        echo "  PASS  $block_label contient les commandes shell exactes requises"
        TESTS_PASS=$((TESTS_PASS + 1))
    else
        echo "  FAIL  $validation_output"
        TESTS_FAIL=$((TESTS_FAIL + 1))
    fi
}

find_yaml_python() {
    local candidate
    local system_python

    if [ -n "${YAML_PYTHON_BIN:-}" ]; then
        if "$YAML_PYTHON_BIN" -c "import yaml" 2>/dev/null; then
            printf '%s\n' "$YAML_PYTHON_BIN"
            return 0
        fi
        return 1
    fi

    for candidate in \
        "$REPO_ROOT/services/rag-pedago/.venv/bin/python" \
        "$REPO_ROOT/services/rag-engine/.venv/bin/python"; do
        if [ -x "$candidate" ] \
            && "$candidate" -c "import yaml" 2>/dev/null; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    system_python="$(command -v python3 || command -v python || true)"
    if [ -n "$system_python" ] \
        && "$system_python" -c "import yaml" 2>/dev/null; then
        printf '%s\n' "$system_python"
        return 0
    fi
    return 1
}

validate_yaml_cockpit_job() {
    local workflow_file="$1"
    local yaml_python

    if ! yaml_python="$(find_yaml_python)"; then
        echo "interpréteur Python avec PyYAML introuvable"
        return 1
    fi

    "$yaml_python" - "$workflow_file" <<'PY'
import sys
from pathlib import Path
from typing import Any

import yaml

workflow_path = Path(sys.argv[1])
try:
    document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
except (OSError, yaml.YAMLError) as exc:
    print(f"workflow YAML illisible: {exc}")
    raise SystemExit(1) from exc

jobs = document.get("jobs") if isinstance(document, dict) else None
cockpit = jobs.get("cockpit") if isinstance(jobs, dict) else None
steps = cockpit.get("steps") if isinstance(cockpit, dict) else None
if not isinstance(steps, list):
    print("jobs.cockpit.steps est absent ou invalide")
    raise SystemExit(1)

errors: list[str] = []
triggers = document.get("on") if isinstance(document, dict) else None
if triggers is None and isinstance(document, dict):
    # PyYAML suit YAML 1.1 et interprète la clé non citée `on` comme true.
    triggers = document.get(True)
required_branches = {"main", "lot-*", "lot-*/**"}
for event_name in ("push", "pull_request"):
    event = triggers.get(event_name) if isinstance(triggers, dict) else None
    branches = event.get("branches") if isinstance(event, dict) else None
    actual_branches = set(branches) if isinstance(branches, list) else set()
    missing_branches = sorted(required_branches - actual_branches)
    if missing_branches:
        errors.append(
            f"on.{event_name}.branches ne couvre pas: "
            + ", ".join(missing_branches)
        )

required_commands: tuple[tuple[str, str | None], ...] = (
    ("npm ci", "services/cockpit"),
    ("npm run lint", "services/cockpit"),
    ("npm test -- --run", "services/cockpit"),
    ("npm run build", "services/cockpit"),
    ("npm audit", "services/cockpit"),
    ("npm audit --omit=dev", "services/cockpit"),
    ("bash scripts/tests/test-cockpit-clean-build.sh", None),
)

for forbidden_key in ("if", "continue-on-error", "shell"):
    if forbidden_key in cockpit:
        errors.append(f"jobs.cockpit.{forbidden_key} est interdit")

for step_index, step in enumerate(steps):
    if not isinstance(step, dict):
        continue
    for forbidden_key in ("if", "continue-on-error", "shell"):
        if forbidden_key in step:
            errors.append(
                f"jobs.cockpit.steps[{step_index}].{forbidden_key} est interdit"
            )

workflow_defaults = (
    document.get("defaults") if isinstance(document, dict) else None
)
workflow_run_defaults = (
    workflow_defaults.get("run")
    if isinstance(workflow_defaults, dict)
    else None
)
if (
    isinstance(workflow_run_defaults, dict)
    and "shell" in workflow_run_defaults
):
    errors.append("defaults.run.shell est interdit")

cockpit_defaults = cockpit.get("defaults")
cockpit_run_defaults = (
    cockpit_defaults.get("run") if isinstance(cockpit_defaults, dict) else None
)
if isinstance(cockpit_run_defaults, dict) and "shell" in cockpit_run_defaults:
    errors.append("jobs.cockpit.defaults.run.shell est interdit")

for command, working_directory in required_commands:
    matches = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        run_value = step.get("run")
        if not isinstance(run_value, str) or run_value != command:
            continue
        if step.get("working-directory") != working_directory:
            continue
        matches.append(step)
    if len(matches) != 1:
        errors.append(
            f"commande effective exacte requise une fois: {command!r} "
            f"(working-directory={working_directory!r}, trouvé={len(matches)})"
        )

setup_node_steps: list[dict[str, Any]] = [
    step
    for step in steps
    if isinstance(step, dict) and step.get("uses") == "actions/setup-node@v4"
]
if len(setup_node_steps) != 1:
    errors.append(
        "actions/setup-node@v4 doit être présent exactement une fois "
        f"(trouvé={len(setup_node_steps)})"
    )
else:
    setup_node_with = setup_node_steps[0].get("with")
    expected_setup = {
        "node-version-file": ".nvmrc",
        "cache": "npm",
        "cache-dependency-path": "services/cockpit/package-lock.json",
    }
    if not isinstance(setup_node_with, dict):
        errors.append("la configuration with de setup-node est absente")
    else:
        for key, expected in expected_setup.items():
            if setup_node_with.get(key) != expected:
                errors.append(
                    f"setup-node.with.{key} doit valoir exactement {expected!r}"
                )

if errors:
    print("jobs.cockpit est incomplet ou non exécutable")
    for error in errors:
        print(f"- {error}")
    raise SystemExit(1)
PY
}

assert_yaml_cockpit_job() {
    local workflow_file="$1"
    local validation_output

    if validation_output="$(validate_yaml_cockpit_job "$workflow_file")"; then
        echo "  PASS  déclencheurs et jobs.cockpit sont stricts et exécutables"
        TESTS_PASS=$((TESTS_PASS + 1))
    else
        echo "  FAIL  $validation_output"
        TESTS_FAIL=$((TESTS_FAIL + 1))
    fi
}

echo ""
echo "=== Test: run_cockpit contient uniquement ses contrôles requis ==="

RUN_COCKPIT_BLOCK="$(
    extract_shell_function "run_cockpit" "$REPO_ROOT/scripts/ci-local.sh"
)"
assert_shell_cockpit_commands "run_cockpit()" "$RUN_COCKPIT_BLOCK"

if block_has_exact_command "$RUN_COCKPIT_BLOCK" \
        'require_node_2222 "$NODE_BIN"' \
    && grep -Fxq 'run_target "services/cockpit" run_cockpit' \
        "$REPO_ROOT/scripts/ci-local.sh"; then
    echo "  PASS  le target cockpit applique le garde-fou Node"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  le target cockpit ou son garde-fou Node est absent"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=== Mutation: run_cockpit rejette une commande seulement affichée ==="

MUTATED_CI_LOCAL="$TMPDIR_CI/ci-local-echo.sh"
cp "$REPO_ROOT/scripts/ci-local.sh" "$MUTATED_CI_LOCAL"
sed -i '0,/^[[:space:]]*npm ci[[:space:]]*$/s//        echo "npm ci"/' \
    "$MUTATED_CI_LOCAL"
MUTATED_RUN_COCKPIT_BLOCK="$(
    extract_shell_function "run_cockpit" "$MUTATED_CI_LOCAL"
)"

if ! validate_shell_cockpit_commands \
    "run_cockpit() muté" "$MUTATED_RUN_COCKPIT_BLOCK" >/dev/null; then
    echo "  PASS  echo \"npm ci\" ne satisfait pas le validateur shell"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  echo \"npm ci\" satisfait encore le validateur shell"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

echo ""
echo "=== Test: le workflow et le job YAML cockpit restent stricts ==="

assert_yaml_cockpit_job "$REPO_ROOT/.github/workflows/ci.yml"

echo ""
echo "=== Mutation: le job cockpit rejette un label sans commande effective ==="

MUTATED_WORKFLOW="$TMPDIR_CI/ci-name-only.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i '0,/^        run: npm ci$/{s/^        run: npm ci$/\
        name: npm ci\
        run: true/;}' "$MUTATED_WORKFLOW"

if ! validate_yaml_cockpit_job "$MUTATED_WORKFLOW" >/dev/null; then
    echo "  PASS  name: npm ci avec run: true est rejeté"
    TESTS_PASS=$((TESTS_PASS + 1))
else
    echo "  FAIL  name: npm ci avec run: true satisfait encore le validateur YAML"
    TESTS_FAIL=$((TESTS_FAIL + 1))
fi

assert_yaml_mutation_rejected() {
    local mutation_label="$1"
    local mutated_workflow="$2"

    if ! validate_yaml_cockpit_job "$mutated_workflow" >/dev/null; then
        echo "  PASS  $mutation_label"
        TESTS_PASS=$((TESTS_PASS + 1))
    else
        echo "  FAIL  $mutation_label est encore accepté"
        TESTS_FAIL=$((TESTS_FAIL + 1))
    fi
}

echo ""
echo "=== Mutations: les déclencheurs lot restent exhaustifs ==="

MUTATED_WORKFLOW="$TMPDIR_CI/ci-trigger-no-flat.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i 's/, "lot-\*"//g' "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "un déclencheur sans lot-* est rejeté" "$MUTATED_WORKFLOW"

MUTATED_WORKFLOW="$TMPDIR_CI/ci-trigger-no-nested.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i 's/, "lot-\*\/\*\*"//g' "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "un déclencheur sans lot-*/** est rejeté" "$MUTATED_WORKFLOW"

echo ""
echo "=== Mutations: le job cockpit reste fail-closed ==="

MUTATED_WORKFLOW="$TMPDIR_CI/ci-cockpit-job-if.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i '/^  cockpit:$/a\    if: false' "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "if: false au niveau du job est rejeté" "$MUTATED_WORKFLOW"

MUTATED_WORKFLOW="$TMPDIR_CI/ci-cockpit-step-if.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i '/^        run: npm ci$/a\        if: false' "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "if: false sur une étape obligatoire est rejeté" "$MUTATED_WORKFLOW"

MUTATED_WORKFLOW="$TMPDIR_CI/ci-cockpit-job-continue.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i '/^  cockpit:$/a\    continue-on-error: true' "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "continue-on-error au niveau du job est rejeté" "$MUTATED_WORKFLOW"

MUTATED_WORKFLOW="$TMPDIR_CI/ci-cockpit-step-continue.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i \
    '/^        run: npm ci$/a\        continue-on-error: true' \
    "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "continue-on-error sur une étape obligatoire est rejeté" "$MUTATED_WORKFLOW"

MUTATED_WORKFLOW="$TMPDIR_CI/ci-cockpit-job-shell.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i '/^  cockpit:$/a\    shell: "true {0}"' "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "un shell personnalisé au niveau du job est rejeté" "$MUTATED_WORKFLOW"

MUTATED_WORKFLOW="$TMPDIR_CI/ci-cockpit-step-shell.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i \
    '/^        run: npm ci$/a\        shell: "true {0}"' \
    "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "un shell personnalisé sur une étape obligatoire est rejeté" \
    "$MUTATED_WORKFLOW"

MUTATED_WORKFLOW="$TMPDIR_CI/ci-workflow-default-shell.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i '/^jobs:$/i\defaults:\n  run:\n    shell: "true {0}"\n' \
    "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "defaults.run.shell au niveau du workflow est rejeté" "$MUTATED_WORKFLOW"

MUTATED_WORKFLOW="$TMPDIR_CI/ci-cockpit-default-shell.yml"
cp "$REPO_ROOT/.github/workflows/ci.yml" "$MUTATED_WORKFLOW"
sed -i \
    '/^  cockpit:$/a\    defaults:\n      run:\n        shell: "true {0}"' \
    "$MUTATED_WORKFLOW"
assert_yaml_mutation_rejected \
    "defaults.run.shell au niveau du job est rejeté" "$MUTATED_WORKFLOW"

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
