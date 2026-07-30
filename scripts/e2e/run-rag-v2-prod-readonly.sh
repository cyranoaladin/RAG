#!/usr/bin/env bash
# Explicit production E2E. It is intentionally absent from full-regression.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
for required in RAG_E2E_UI_URL RAG_E2E_API_URL RAG_E2E_STUDENT_TOKEN; do
    if [[ -z "${!required:-}" ]]; then
        echo "ERROR: $required doit être fourni explicitement" >&2
        exit 1
    fi
done

if [[ ! -d "$SCRIPT_DIR/node_modules" ]]; then
    echo "ERROR: Playwright absent. Exécutez d'abord scripts/e2e/setup-playwright.sh." >&2
    exit 1
fi

if [[ -z "${E2E_RESULTS:-}" ]]; then
    E2E_RESULTS="$(mktemp -d)"
fi
export E2E_RESULTS
mkdir -p "$E2E_RESULTS"

export NODE_PATH="$SCRIPT_DIR/node_modules${NODE_PATH:+:$NODE_PATH}"
if ! node -e "require.resolve('playwright')" >/dev/null 2>&1; then
    echo "ERROR: Playwright absent de scripts/e2e/node_modules." >&2
    exit 1
fi

node "$SCRIPT_DIR/rag-v2-prod-readonly.js"
echo "Résultats E2E: $E2E_RESULTS"
