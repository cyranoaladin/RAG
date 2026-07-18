#!/usr/bin/env bash
# full-regression.sh — Official full regression runner for the RAG mono-repo.
# Runs all validation gates with fail-fast (stops at first failure).
# Usage: bash scripts/tests/full-regression.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
cd "$REPO_ROOT"

PASS=0
TOTAL=0

step() {
    local name="$1"
    shift
    TOTAL=$((TOTAL + 1))
    echo ""
    echo "=============================="
    echo "  [$TOTAL] $name"
    echo "=============================="
    if "$@"; then
        PASS=$((PASS + 1))
        echo "  -> PASS"
    else
        echo ""
        echo "FAIL at step [$TOTAL]: $name"
        echo "Stopping (fail-fast)."
        exit 1
    fi
}

# --- Governance locks ---
step "governance-locks" bash scripts/check-governance-locks.sh
step "governance-locks-tests" bash scripts/tests/test-governance-locks.sh

# --- Whitespace check ---
step "git-diff-check" git diff --check HEAD~0

# --- rag-engine ---
step "rag-engine: lint" make -C services/rag-engine lint
step "rag-engine: typecheck" make -C services/rag-engine typecheck
step "rag-engine: test" make -C services/rag-engine test

# --- rag-pedago ---
step "rag-pedago: lint" make -C services/rag-pedago lint
step "rag-pedago: typecheck" make -C services/rag-pedago typecheck
step "rag-pedago: test" make -C services/rag-pedago test

echo ""
echo "=============================="
echo "  FULL REGRESSION — ALL PASS"
echo "=============================="
echo "  $PASS/$TOTAL steps passed."
exit 0
