#!/usr/bin/env bash
# ci-local.sh — Local CI reproducing the GitHub Actions pipeline.
# Runs contracts, rag-pedago, rag-engine, and governance locks checks.
# Exits non-zero if any target fails.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
source "$SCRIPT_DIR/lib/ci-common.sh"
cd "$REPO_ROOT"

PYTHON_BIN="$(command -v python3.11 || command -v python3.12 || command -v python3 || true)"
if ! require_python_311 "$PYTHON_BIN"; then
    exit 1
fi
echo "Using Python executable: $PYTHON_BIN ($($PYTHON_BIN --version))"

PASS=0
FAIL=0
RESULTS=()

run_target() {
    local name="$1"
    shift
    echo ""
    echo "=============================="
    echo "  $name"
    echo "=============================="
    if "$@"; then
        RESULTS+=("PASS  $name")
        ((PASS++))
    else
        RESULTS+=("FAIL  $name")
        ((FAIL++))
    fi
}

# --- packages/contracts ---
run_contracts() {
    local venv="/tmp/ci-local-contracts-venv"
    rm -rf "$venv"
    "$PYTHON_BIN" -m venv "$venv"
    "$venv/bin/pip" install -q -e packages/contracts
    "$venv/bin/python" -c "from nexus_contracts import RetrievalRequest, StudentProfile; print('contracts: import OK')"
}
run_target "packages/contracts" run_contracts

# --- services/rag-pedago ---
run_pedago() {
    cd "$REPO_ROOT/services/rag-pedago"
    rm -rf .venv
    "$PYTHON_BIN" -m venv .venv
    source .venv/bin/activate
    if ! make install; then
        echo "FAIL: rag-pedago install failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- lint ---"
    if ! make lint; then
        echo "FAIL: rag-pedago lint failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- typecheck ---"
    if ! make typecheck; then
        echo "FAIL: rag-pedago typecheck failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- test ---"
    local test_exit
    run_checked make test
    test_exit=$?

    if [ "$test_exit" -ne 0 ]; then
        echo "FAIL: rag-pedago tests failed (exit $test_exit)"
        deactivate 2>/dev/null || true
        cd "$REPO_ROOT"
        return "$test_exit"
    fi

    deactivate 2>/dev/null || true
    cd "$REPO_ROOT"
}
run_target "services/rag-pedago" run_pedago

# --- services/rag-engine ---
run_engine() {
    cd "$REPO_ROOT/services/rag-engine"
    rm -rf .venv
    if ! make install; then
        echo "FAIL: rag-engine install failed"
        cd "$REPO_ROOT"; return 1
    fi
    source .venv/bin/activate

    echo "--- lint ---"
    if ! make lint; then
        echo "FAIL: rag-engine lint failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- typecheck ---"
    if ! make typecheck; then
        echo "FAIL: rag-engine typecheck failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- test ---"
    if ! make test; then
        echo "FAIL: rag-engine tests failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    deactivate 2>/dev/null || true
    cd "$REPO_ROOT"
}
run_target "services/rag-engine" run_engine

# --- governance locks ---
run_target "governance-locks" bash scripts/check-governance-locks.sh

# --- taxonomy validation ---
run_target "taxonomy-validation" bash -c "cd $REPO_ROOT/services/rag-pedago && source .venv/bin/activate && python scripts/validate_taxonomy.py"

# --- source evidence check (revue PR #74, round 11) ---
run_target "source-evidence-check" bash -c "cd $REPO_ROOT/services/rag-pedago && source .venv/bin/activate && python scripts/export_source_validation_evidence.py --check"

# --- governance guard tests ---
run_target "governance-guard-tests" bash scripts/tests/test-governance-locks.sh

# --- ci failsafe tests ---
run_target "ci-failsafe-tests" bash scripts/tests/test-ci-local-failsafe.sh

# --- Summary ---
echo ""
echo "=============================="
echo "  CI LOCAL — SUMMARY"
echo "=============================="
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""
echo "Total: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
