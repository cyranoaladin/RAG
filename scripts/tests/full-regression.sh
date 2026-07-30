#!/usr/bin/env bash
# Deterministic, hermetic regression gate. Environment setup is deliberately
# outside this script; missing tools fail closed instead of being installed.
set -euo pipefail

# Aucun installateur ne doit pouvoir solliciter le réseau depuis cette porte.
export PIP_NO_INDEX=1
export PIP_DISABLE_PIP_VERSION_CHECK=1
export NPM_CONFIG_OFFLINE=true
export NPM_CONFIG_AUDIT=false
export NPM_CONFIG_FUND=false

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

PASS=0
TOTAL=0
NETWORK_DESELECTED=0
E2E_DESELECTED=0

step() {
    local name="$1"
    shift
    TOTAL=$((TOTAL + 1))
    echo ""
    echo "=============================="
    echo "  [$TOTAL] $name"
    echo "=============================="
    "$@"
    PASS=$((PASS + 1))
}

require_executable() {
    local executable="$1"
    if [[ ! -x "$executable" ]]; then
        echo "ERROR: environnement de régression incomplet: $executable" >&2
        echo "Préparez les environnements hors de cette cible, puis relancez." >&2
        exit 1
    fi
}

count_marked_tests() {
    local python_bin="$1"
    local workdir="$2"
    local pythonpath="$3"
    local marker="$4"
    local count
    count="$(
        cd "$workdir"
        PYTHONPATH="$pythonpath" "$python_bin" -m pytest --collect-only -q -m "$marker" tests \
            | awk -F ': ' '/^tests\/.*: [0-9]+$/ { count += $NF } END { print count + 0 }'
    )"
    printf '%s\n' "$count"
}

run_python_suite() {
    local label="$1"
    local workdir="$2"
    local python_bin="$3"
    local pythonpath="$4"
    local network_count e2e_count

    require_executable "$python_bin"
    network_count="$(count_marked_tests "$python_bin" "$workdir" "$pythonpath" network)"
    e2e_count="$(count_marked_tests "$python_bin" "$workdir" "$pythonpath" e2e)"
    NETWORK_DESELECTED=$((NETWORK_DESELECTED + network_count))
    E2E_DESELECTED=$((E2E_DESELECTED + e2e_count))

    step "$label: lint" bash -c "cd \"$workdir\" && \"$python_bin\" -m ruff check ."
    step "$label: typecheck" bash -c "cd \"$workdir\" && \"$python_bin\" -m mypy src"
    step "$label: tests hermétiques" bash -c "cd \"$workdir\" && PYTHONPATH=\"$pythonpath\" \"$python_bin\" -m pytest -q -m 'not network and not e2e' tests"
}

CONTRACTS_PYTHON="$REPO_ROOT/packages/contracts/.venv/bin/python"
PEDAGO_PYTHON="$REPO_ROOT/services/rag-pedago/.venv/bin/python"
ENGINE_PYTHON="$REPO_ROOT/services/rag-engine/.venv/bin/python"

step "gouvernance: verrous" bash scripts/check-governance-locks.sh
step "gouvernance: tests" bash scripts/tests/test-governance-locks.sh
step "CI locale: topologie non récursive" bash scripts/tests/test-ci-local-topology.sh
step "hygiène: diff" git diff --check HEAD
step "hygiène: zombies et doublons versionnés" bash scripts/tests/check-zombies-and-duplicates.sh
step "E2E: politique read-only" node --test scripts/e2e/read_only_policy.test.js

require_executable "$CONTRACTS_PYTHON"
NETWORK_DESELECTED=$((NETWORK_DESELECTED + $(count_marked_tests "$CONTRACTS_PYTHON" "$REPO_ROOT/packages/contracts" "src" network)))
E2E_DESELECTED=$((E2E_DESELECTED + $(count_marked_tests "$CONTRACTS_PYTHON" "$REPO_ROOT/packages/contracts" "src" e2e)))
step "contracts: lint" bash -c "cd packages/contracts && \"$CONTRACTS_PYTHON\" -m ruff check ."
step "contracts: tests hermétiques" bash -c "cd packages/contracts && PYTHONPATH=src \"$CONTRACTS_PYTHON\" -m pytest -q -m 'not network and not e2e' tests"

run_python_suite "rag-engine" "$REPO_ROOT/services/rag-engine" "$ENGINE_PYTHON" "src"

require_executable "$PEDAGO_PYTHON"
NETWORK_DESELECTED=$((NETWORK_DESELECTED + $(count_marked_tests "$PEDAGO_PYTHON" "$REPO_ROOT/services/rag-pedago" "." network)))
E2E_DESELECTED=$((E2E_DESELECTED + $(count_marked_tests "$PEDAGO_PYTHON" "$REPO_ROOT/services/rag-pedago" "." e2e)))
step "rag-pedago: lint" bash -c "cd services/rag-pedago && \"$PEDAGO_PYTHON\" -m ruff check ."
step "rag-pedago: typecheck" bash -c "cd services/rag-pedago && \"$PEDAGO_PYTHON\" -m mypy schema pipeline retrieval services rag_pedago scrapers agents"
step "rag-pedago: tests hermétiques" bash -c "cd services/rag-pedago && PYTHONPATH=. \"$PEDAGO_PYTHON\" -m pytest -q -m 'not network and not e2e' tests"

step "cockpit: dépendances préparées" test -x services/cockpit/node_modules/.bin/vitest
step "cockpit: lint" bash -c "cd services/cockpit && npm run lint"
step "cockpit: tests" bash -c "cd services/cockpit && npm test -- --run"
step "cockpit: build" bash -c "cd services/cockpit && NEXT_TELEMETRY_DISABLED=1 npm run build"
step "cockpit: cohérence" "$PEDAGO_PYTHON" scripts/tests/test-cockpit-snapshot-coherence.py
step "cockpit: build propre" bash scripts/tests/test-cockpit-clean-build.sh
step "smoke racine" python -m pytest -q

echo ""
echo "=============================="
echo "  FULL REGRESSION — ALL PASS"
echo "=============================="
echo "  $PASS/$TOTAL étapes passées."
echo "  Hors périmètre explicite : network=$NETWORK_DESELECTED, e2e=$E2E_DESELECTED."
