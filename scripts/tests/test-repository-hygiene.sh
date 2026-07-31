#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
GUARD="$REPO_ROOT/scripts/check-repository-hygiene.sh"
WORKFLOW="$REPO_ROOT/.github/workflows/ci.yml"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

BASE_REPO="$TMP_ROOT/base"
TEST_REPO="$TMP_ROOT/worktree"
BARE_REPO="$TMP_ROOT/bare"
mkdir -p "$BASE_REPO/scripts"
cp "$GUARD" "$BASE_REPO/scripts/check-repository-hygiene.sh"
git -C "$BASE_REPO" init -q
git -C "$BASE_REPO" config user.name "LOT37R test"
git -C "$BASE_REPO" config user.email "lot37r@example.invalid"
git -C "$BASE_REPO" add scripts/check-repository-hygiene.sh
git -C "$BASE_REPO" commit -qm "test: initialise hygiene fixture"
git -C "$BASE_REPO" worktree add -qb hygiene-worktree "$TEST_REPO"
mkdir -p "$TEST_REPO/docs/reports"
test -f "$TEST_REPO/.git"

bash "$TEST_REPO/scripts/check-repository-hygiene.sh" "$TEST_REPO"

git init --bare -q "$BARE_REPO"
set +e
BARE_OUTPUT="$(bash "$GUARD" "$BARE_REPO" 2>&1)"
BARE_STATUS=$?
set -e
if [ "$BARE_STATUS" -ne 2 ]; then
    echo "FAIL: bare repository returned $BARE_STATUS instead of 2" >&2
    exit 1
fi
if ! grep -Fq "ERROR: repository root is not a Git worktree: $BARE_REPO" \
    <<<"$BARE_OUTPUT"; then
    echo "FAIL: bare repository error message is missing" >&2
    exit 1
fi

assert_forbidden_root_artifact() {
    local artifact="$1"
    local output
    local status
    local rendered

    set +e
    output="$(
        bash "$TEST_REPO/scripts/check-repository-hygiene.sh" "$TEST_REPO" \
            2>&1
    )"
    status=$?
    set -e

    printf -v rendered '%q' "$artifact"
    if [ "$status" -ne 1 ]; then
        printf 'FAIL: %q returned %s instead of 1\n' "$artifact" "$status" >&2
        return 1
    fi
    if ! grep -Fq "  $rendered" <<<"$output"; then
        printf 'FAIL: output does not render %q unambiguously\n' \
            "$artifact" >&2
        return 1
    fi
}

printf 'manifest\n' > "$TEST_REPO/MANIFEST_LOT99.md"
git -C "$TEST_REPO" add MANIFEST_LOT99.md
assert_forbidden_root_artifact "MANIFEST_LOT99.md"
git -C "$TEST_REPO" mv MANIFEST_LOT99.md docs/reports/MANIFEST_LOT99.md
bash "$TEST_REPO/scripts/check-repository-hygiene.sh" "$TEST_REPO"

printf 'archive\n' > "$TEST_REPO/runtime.tar.gz"
git -C "$TEST_REPO" add runtime.tar.gz
assert_forbidden_root_artifact "runtime.tar.gz"
git -C "$TEST_REPO" rm -q --cached runtime.tar.gz
bash "$TEST_REPO/scripts/check-repository-hygiene.sh" "$TEST_REPO"

ROOT_ARTIFACTS=(
    "runtime archive.tar"
    "runtime.tgz"
    $'runtime\nbundle.zip'
)
for artifact in "${ROOT_ARTIFACTS[@]}"; do
    printf 'artifact\n' > "$TEST_REPO/$artifact"
    git -C "$TEST_REPO" add -- "$artifact"
    assert_forbidden_root_artifact "$artifact"
    git -C "$TEST_REPO" rm -q -f -- "$artifact"
done

resolve_yaml_python_candidate() {
    local candidate="$1"
    local resolved

    if [[ "$candidate" == */* ]]; then
        [ -x "$candidate" ] || return 1
        resolved="$candidate"
    else
        resolved="$(command -v "$candidate" 2>/dev/null || true)"
        [ -n "$resolved" ] || return 1
    fi
    "$resolved" -c "import yaml" >/dev/null 2>&1 || return 1
    printf '%s\n' "$resolved"
}

find_yaml_python() {
    local candidate
    local resolved
    local fallbacks=(
        "$REPO_ROOT/services/rag-pedago/.venv/bin/python"
        "python3.11"
        "python3"
    )

    if [ -n "${YAML_PYTHON_BIN:-}" ]; then
        if resolved="$(resolve_yaml_python_candidate "$YAML_PYTHON_BIN")"; then
            printf '%s\n' "$resolved"
            return 0
        fi
        printf 'ERROR: YAML_PYTHON_BIN is invalid or cannot import PyYAML: %q\n' \
            "$YAML_PYTHON_BIN" >&2
        return 2
    fi

    for candidate in "${fallbacks[@]}"; do
        if resolved="$(resolve_yaml_python_candidate "$candidate")"; then
            printf '%s\n' "$resolved"
            return 0
        fi
    done
    echo "ERROR: Python 3 with PyYAML is required to validate ci.yml" >&2
    return 2
}

set +e
INVALID_OVERRIDE_OUTPUT="$(YAML_PYTHON_BIN=/bin/false find_yaml_python 2>&1)"
INVALID_OVERRIDE_STATUS=$?
set -e
if [ "$INVALID_OVERRIDE_STATUS" -ne 2 ]; then
    echo "FAIL: invalid YAML_PYTHON_BIN did not fail with status 2" >&2
    exit 1
fi
if ! grep -Fq "ERROR: YAML_PYTHON_BIN is invalid" \
    <<<"$INVALID_OVERRIDE_OUTPUT"; then
    echo "FAIL: invalid YAML_PYTHON_BIN error message is missing" >&2
    exit 1
fi

set +e
YAML_VALIDATOR_PYTHON="$(find_yaml_python)"
YAML_VALIDATOR_STATUS=$?
set -e
if [ "$YAML_VALIDATOR_STATUS" -ne 0 ]; then
    exit "$YAML_VALIDATOR_STATUS"
fi

validate_repository_controls_workflow() {
    local workflow_file="$1"

    "$YAML_VALIDATOR_PYTHON" - "$workflow_file" <<'PY'
from pathlib import Path
import sys

import yaml

workflow_path = Path(sys.argv[1])
try:
    document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
except (OSError, yaml.YAMLError) as exc:
    print(f"workflow YAML illisible: {exc}", file=sys.stderr)
    raise SystemExit(1)

if not isinstance(document, dict):
    print("workflow YAML must be a mapping", file=sys.stderr)
    raise SystemExit(1)
jobs = document.get("jobs")
if not isinstance(jobs, dict):
    print("workflow jobs must be a mapping", file=sys.stderr)
    raise SystemExit(1)
repository_controls = jobs.get("repository-controls")
if not isinstance(repository_controls, dict):
    print("jobs.repository-controls must be a mapping", file=sys.stderr)
    raise SystemExit(1)
steps = repository_controls.get("steps")
if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
    print("jobs.repository-controls.steps must be a list of mappings", file=sys.stderr)
    raise SystemExit(1)

expected_steps = [
    {"uses": "actions/checkout@v4"},
    {
        "uses": "actions/setup-python@v5",
        "with": {"python-version": "3.11"},
    },
    {"run": "pip install PyYAML==6.0.3"},
    {"run": "bash scripts/check-repository-hygiene.sh"},
    {
        "run": (
            "YAML_PYTHON_BIN=python "
            "bash scripts/tests/test-repository-hygiene.sh"
        )
    },
    {"run": "bash scripts/tests/test-ci-local-topology.sh"},
    {"run": "python scripts/tests/test-main-protection-policy.py"},
    {
        "run": (
            "YAML_PYTHON_BIN=python NEXUS_CI_LOCAL_RUNNING=1 "
            "bash scripts/tests/test-ci-local-failsafe.sh"
        )
    },
]
if steps != expected_steps:
    print("jobs.repository-controls.steps differs from the required list", file=sys.stderr)
    raise SystemExit(1)
PY
}

validate_repository_controls_workflow "$WORKFLOW"

MUTATED_WORKFLOW="$TMP_ROOT/ci-mutated.yml"
printf '%s\n' \
    'name: mutated CI' \
    'jobs:' \
    '  repository-controls:' \
    '    name: "repository controls"' \
    '    runs-on: ubuntu-latest' \
    '    steps:' \
    '      - uses: actions/checkout@v4' \
    '      - run: true' \
    '        # uses: actions/setup-python@v5' \
    '        # python-version: "3.11"' \
    '      - run: true' \
    '        # run: pip install PyYAML==6.0.3' \
    '      - run: bash scripts/check-repository-hygiene.sh' \
    '      - run: YAML_PYTHON_BIN=python bash scripts/tests/test-repository-hygiene.sh' \
    '      - run: bash scripts/tests/test-ci-local-topology.sh' \
    '      - run: true' \
    '        # run: YAML_PYTHON_BIN=python NEXUS_CI_LOCAL_RUNNING=1 bash scripts/tests/test-ci-local-failsafe.sh' \
    > "$MUTATED_WORKFLOW"
set +e
MUTATION_OUTPUT="$(
    validate_repository_controls_workflow "$MUTATED_WORKFLOW" 2>&1
)"
MUTATION_STATUS=$?
set -e
if [ "$MUTATION_STATUS" -eq 0 ]; then
    echo "FAIL: no-op repository-controls mutation was accepted" >&2
    exit 1
fi
if ! grep -Fq "steps differs from the required list" <<<"$MUTATION_OUTPUT"; then
    echo "FAIL: no-op mutation was not rejected by structural comparison" >&2
    exit 1
fi

echo "PASS: repository hygiene inspects tracked root files only"
