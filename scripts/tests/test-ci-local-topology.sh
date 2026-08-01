#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

mkdir -p "$TMP_ROOT/repo/scripts"
awk '
    /^SCRIPT_DIR=/ && !inserted {
        print "echo \"FAIL: re-entry guard was bypassed\" >&2"
        print "exit 86"
        inserted = 1
    }
    { print }
    END { if (!inserted) exit 1 }
' "$REPO_ROOT/scripts/ci-local.sh" > "$TMP_ROOT/repo/scripts/ci-local.sh"

set +e
OUTPUT="$({
    NEXUS_CI_LOCAL_RUNNING=1 \
        bash "$TMP_ROOT/repo/scripts/ci-local.sh"
} 2>&1)"
STATUS=$?
set -e

if [ "$STATUS" -ne 2 ]; then
    echo "FAIL: expected re-entry exit 2, got $STATUS" >&2
    echo "$OUTPUT" >&2
    exit 1
fi
grep -Fq "ERROR: ci-local.sh refuse une réentrance" <<<"$OUTPUT"
if grep -Fq "FAIL: re-entry guard was bypassed" <<<"$OUTPUT"; then
    echo "FAIL: re-entry was rejected after the safe stop point" >&2
    exit 1
fi

create_parent_child_probe() {
    local source_file="$1"
    local probe_file="$2"

    awk '
        /^SCRIPT_DIR=/ && !inserted {
            print "if [ \"${NEXUS_CI_TOPOLOGY_PARENT:-0}\" = \"1\" ]; then"
            print "    unset NEXUS_CI_TOPOLOGY_PARENT"
            print "    exec bash \"$0\""
            print "fi"
            print "echo \"FAIL: child reached re-entry sentinel\" >&2"
            print "exit 86"
            inserted = 1
        }
        { print }
        END { if (!inserted) exit 1 }
    ' "$source_file" > "$probe_file"
}

run_parent_child_probe() {
    local source_file="$1"
    local probe_file="$2"

    create_parent_child_probe "$source_file" "$probe_file"
    set +e
    PARENT_CHILD_OUTPUT="$({
        env -u NEXUS_CI_LOCAL_RUNNING \
            NEXUS_CI_TOPOLOGY_PARENT=1 \
            bash "$probe_file"
    } 2>&1)"
    PARENT_CHILD_STATUS=$?
    set -e
}

parent_child_was_rejected() {
    local status="$1"
    local output="$2"

    [ "$status" -eq 2 ] \
        && grep -Fq "ERROR: ci-local.sh refuse une réentrance" <<<"$output" \
        && ! grep -Fq "FAIL: child reached re-entry sentinel" <<<"$output"
}

PARENT_CHILD_PROBE="$TMP_ROOT/repo/scripts/ci-local-parent-child.sh"
run_parent_child_probe \
    "$REPO_ROOT/scripts/ci-local.sh" \
    "$PARENT_CHILD_PROBE"
if ! parent_child_was_rejected \
    "$PARENT_CHILD_STATUS" \
    "$PARENT_CHILD_OUTPUT"; then
    echo "FAIL: child process was not rejected before the sentinel" >&2
    echo "$PARENT_CHILD_OUTPUT" >&2
    exit 1
fi

NO_EXPORT_SOURCE="$TMP_ROOT/repo/scripts/ci-local-without-export.sh"
awk '$0 != "export NEXUS_CI_LOCAL_RUNNING=1" { print }' \
    "$REPO_ROOT/scripts/ci-local.sh" > "$NO_EXPORT_SOURCE"
run_parent_child_probe \
    "$NO_EXPORT_SOURCE" \
    "$TMP_ROOT/repo/scripts/ci-local-without-export-probe.sh"
if parent_child_was_rejected \
    "$PARENT_CHILD_STATUS" \
    "$PARENT_CHILD_OUTPUT"; then
    echo "FAIL: parent-child probe accepts a missing marker export" >&2
    exit 1
fi
if [ "$PARENT_CHILD_STATUS" -ne 86 ] \
    || ! grep -Fq "FAIL: child reached re-entry sentinel" \
        <<<"$PARENT_CHILD_OUTPUT"; then
    echo "FAIL: missing-export mutation did not reach the sentinel" >&2
    echo "$PARENT_CHILD_OUTPUT" >&2
    exit 1
fi

assert_no_call_reference() {
    local source_file="$1"
    local forbidden_reference="$2"
    local failure_message="$3"

    if grep -Fq "$forbidden_reference" "$source_file"; then
        echo "FAIL: $failure_message" >&2
        return 1
    fi
    return 0
}

assert_no_call_reference \
    "$REPO_ROOT/scripts/audit/rag-pr-audit.sh" \
    "ci-local.sh" \
    "rag-pr-audit.sh invokes ci-local.sh"
assert_no_call_reference \
    "$REPO_ROOT/scripts/ci-local.sh" \
    "rag-pr-audit.sh" \
    "ci-local.sh invokes rag-pr-audit.sh"

MUTATED_AUDIT="$TMP_ROOT/rag-pr-audit-with-quoted-call.sh"
printf '%s\n' 'bash "$REPO_ROOT/scripts/ci-local.sh"' > "$MUTATED_AUDIT"
if assert_no_call_reference \
    "$MUTATED_AUDIT" \
    "ci-local.sh" \
    "quoted audit mutation invokes ci-local.sh" >/dev/null 2>&1; then
    echo "FAIL: quoted ci-local.sh call was not rejected" >&2
    exit 1
fi

MUTATED_CI_LOCAL="$TMP_ROOT/ci-local-with-quoted-call.sh"
printf '%s\n' \
    'bash "$REPO_ROOT/scripts/audit/rag-pr-audit.sh"' \
    > "$MUTATED_CI_LOCAL"
if assert_no_call_reference \
    "$MUTATED_CI_LOCAL" \
    "rag-pr-audit.sh" \
    "quoted CI mutation invokes rag-pr-audit.sh" >/dev/null 2>&1; then
    echo "FAIL: quoted rag-pr-audit.sh call was not rejected" >&2
    exit 1
fi

find_yaml_python() {
    local candidate

    if [ -n "${YAML_PYTHON_BIN:-}" ] \
        && "$YAML_PYTHON_BIN" -c "import yaml" 2>/dev/null; then
        printf '%s\n' "$YAML_PYTHON_BIN"
        return 0
    fi

    for candidate in \
        "$REPO_ROOT/services/rag-pedago/.venv/bin/python" \
        "$REPO_ROOT/services/rag-engine/.venv/bin/python" \
        "$(command -v python3 || true)"; do
        if [ -n "$candidate" ] \
            && [ -x "$candidate" ] \
            && "$candidate" -c "import yaml" 2>/dev/null; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    echo "FAIL: Python avec PyYAML introuvable" >&2
    return 1
}

validate_hybrid_integration_step() {
    local workflow_file="$1"
    local yaml_python

    yaml_python="$(find_yaml_python)"
    "$yaml_python" - "$workflow_file" <<'PY'
import sys
from pathlib import Path

import yaml

workflow_path = Path(sys.argv[1])
try:
    document = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
except (OSError, yaml.YAMLError) as exc:
    print(f"workflow YAML illisible: {exc}", file=sys.stderr)
    raise SystemExit(1) from exc

jobs = document.get("jobs") if isinstance(document, dict) else None
if not isinstance(jobs, dict):
    print("jobs est absent ou invalide", file=sys.stderr)
    raise SystemExit(1)

engine = jobs.get("rag-engine")
engine_steps = engine.get("steps") if isinstance(engine, dict) else None
if not isinstance(engine_steps, list):
    print("jobs.rag-engine.steps est absent ou invalide", file=sys.stderr)
    raise SystemExit(1)

errors: list[str] = []
make_control_variables = {"MAKEFLAGS", "GNUMAKEFLAGS", "MFLAGS"}


def validate_make_environment(scope: object, label: str) -> None:
    if not isinstance(scope, dict) or "env" not in scope:
        return
    environment = scope.get("env")
    if not isinstance(environment, dict):
        errors.append(f"{label}.env est invalide")
        return
    forbidden = sorted(make_control_variables.intersection(environment))
    if forbidden:
        errors.append(
            f"{label}.env contrôle GNU Make via: {', '.join(forbidden)}"
        )


def validate_run_defaults(scope: object, label: str) -> None:
    if not isinstance(scope, dict) or "defaults" not in scope:
        return
    defaults = scope.get("defaults")
    if not isinstance(defaults, dict):
        errors.append(f"{label}.defaults est invalide")
        return
    run_defaults = defaults.get("run")
    if run_defaults is None:
        return
    if not isinstance(run_defaults, dict):
        errors.append(f"{label}.defaults.run est invalide")
    elif "shell" in run_defaults:
        errors.append(f"{label}.defaults.run.shell est interdit")


for forbidden_key in ("if", "continue-on-error", "shell"):
    if forbidden_key in engine:
        errors.append(f"jobs.rag-engine.{forbidden_key} est interdit")

validate_run_defaults(document, "workflow")
validate_run_defaults(engine, "jobs.rag-engine")
validate_make_environment(document, "workflow")
validate_make_environment(engine, "jobs.rag-engine")
for step_index, step in enumerate(engine_steps):
    validate_make_environment(step, f"jobs.rag-engine.steps[{step_index}]")

integration_command = "make test-integration-hybrid"
working_directory = "services/rag-engine"
all_occurrences: list[tuple[str, int, dict[object, object]]] = []
for job_name, job in jobs.items():
    steps = job.get("steps") if isinstance(job, dict) else None
    if not isinstance(steps, list):
        continue
    for step_index, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        run_value = step.get("run")
        if isinstance(run_value, str) and integration_command in run_value:
            all_occurrences.append((str(job_name), step_index, step))

exact_occurrences = [
    occurrence
    for occurrence in all_occurrences
    if occurrence[2].get("run") == integration_command
    and occurrence[2].get("working-directory") == working_directory
]
if len(all_occurrences) != 1 or len(exact_occurrences) != 1:
    errors.append(
        "make test-integration-hybrid doit apparaître exactement une fois, "
        "sans suffixe et dans services/rag-engine"
    )
else:
    job_name, integration_index, integration_step = exact_occurrences[0]
    if job_name != "rag-engine":
        errors.append("le smoke hybride appartient à un autre job")
    for forbidden_key in ("if", "continue-on-error", "shell"):
        if forbidden_key in integration_step:
            errors.append(
                f"le step smoke hybride contient la clé interdite {forbidden_key}"
            )

    test_indexes = [
        index
        for index, step in enumerate(engine_steps)
        if isinstance(step, dict)
        and step.get("run") == "make test"
        and step.get("working-directory") == working_directory
    ]
    if len(test_indexes) != 1:
        errors.append("le step exact make test de rag-engine doit être unique")
    elif integration_index <= test_indexes[0]:
        errors.append("le smoke hybride doit être placé après make test")

if errors:
    for error in errors:
        print(f"- {error}", file=sys.stderr)
    raise SystemExit(1)
PY
}

mutate_hybrid_fixture() {
    local source_file="$1"
    local destination_file="$2"
    local mutation="$3"
    local yaml_python

    yaml_python="$(find_yaml_python)"
    "$yaml_python" - "$source_file" "$destination_file" "$mutation" <<'PY'
import sys
from pathlib import Path

import yaml

source = Path(sys.argv[1])
destination = Path(sys.argv[2])
mutation = sys.argv[3]
document = yaml.safe_load(source.read_text(encoding="utf-8"))
jobs = document["jobs"]
engine_steps = jobs["rag-engine"]["steps"]
integration_index = next(
    index
    for index, step in enumerate(engine_steps)
    if step.get("run") == "make test-integration-hybrid"
)
integration_step = engine_steps[integration_index]

if mutation == "step-if-false":
    integration_step["if"] = False
elif mutation == "step-continue-on-error":
    integration_step["continue-on-error"] = True
elif mutation == "step-shell":
    integration_step["shell"] = "bash {0}"
elif mutation == "tolerant-suffix":
    integration_step["run"] += " || true"
elif mutation == "other-job":
    jobs["repository-controls"]["steps"].append(engine_steps.pop(integration_index))
elif mutation == "before-tests":
    integration_step = engine_steps.pop(integration_index)
    test_index = next(
        index for index, step in enumerate(engine_steps) if step.get("run") == "make test"
    )
    engine_steps.insert(test_index, integration_step)
elif mutation == "job-if-false":
    jobs["rag-engine"]["if"] = False
elif mutation == "job-continue-on-error":
    jobs["rag-engine"]["continue-on-error"] = True
elif mutation == "workflow-default-shell":
    document["defaults"] = {"run": {"shell": "true {0}"}}
elif mutation == "job-default-shell":
    jobs["rag-engine"]["defaults"] = {"run": {"shell": "true {0}"}}
elif mutation.startswith(("workflow-env-", "job-env-", "step-env-")):
    level, _, variable_slug = mutation.partition("-env-")
    variable = variable_slug.upper()
    if level == "workflow":
        scope = document
    elif level == "job":
        scope = jobs["rag-engine"]
    else:
        scope = integration_step
    scope["env"] = {variable: "-i"}
else:
    raise SystemExit(f"mutation inconnue: {mutation}")

destination.write_text(
    yaml.safe_dump(document, sort_keys=False),
    encoding="utf-8",
)
PY
}

CANONICAL_WORKFLOW="$TMP_ROOT/canonical-hybrid-ci.yml"
cat > "$CANONICAL_WORKFLOW" <<'YAML'
jobs:
  rag-engine:
    steps:
      - working-directory: services/rag-engine
        run: make test
      - working-directory: services/rag-engine
        run: make test-integration-hybrid
  repository-controls:
    steps: []
YAML

if ! validate_hybrid_integration_step "$CANONICAL_WORKFLOW"; then
    echo "FAIL: la fixture canonique du smoke hybride est rejetée" >&2
    exit 1
fi
echo "PASS: la fixture canonique du smoke hybride est acceptée"

HYBRID_MUTATIONS_REJECTED=0
for mutation in \
    step-if-false \
    step-continue-on-error \
    step-shell \
    tolerant-suffix \
    other-job \
    before-tests \
    job-if-false \
    job-continue-on-error \
    workflow-default-shell \
    job-default-shell \
    workflow-env-makeflags \
    workflow-env-gnumakeflags \
    workflow-env-mflags \
    job-env-makeflags \
    job-env-gnumakeflags \
    job-env-mflags \
    step-env-makeflags \
    step-env-gnumakeflags \
    step-env-mflags; do
    MUTATED_WORKFLOW="$TMP_ROOT/hybrid-$mutation.yml"
    mutate_hybrid_fixture "$CANONICAL_WORKFLOW" "$MUTATED_WORKFLOW" "$mutation"
    if validate_hybrid_integration_step "$MUTATED_WORKFLOW" >/dev/null 2>&1; then
        echo "FAIL: la mutation hybride $mutation est acceptée" >&2
        exit 1
    fi
    HYBRID_MUTATIONS_REJECTED=$((HYBRID_MUTATIONS_REJECTED + 1))
done
if [ "$HYBRID_MUTATIONS_REJECTED" -ne 19 ]; then
    echo "FAIL: dix-neuf mutations hybrides doivent être refusées" >&2
    exit 1
fi
echo "PASS: les dix-neuf mutations du smoke hybride sont refusées"

if ! validate_hybrid_integration_step "$REPO_ROOT/.github/workflows/ci.yml"; then
    echo "FAIL: le smoke hybride GitHub est absent ou contournable" >&2
    exit 1
fi

echo "PASS: CI topology is acyclic and re-entry fails closed"
