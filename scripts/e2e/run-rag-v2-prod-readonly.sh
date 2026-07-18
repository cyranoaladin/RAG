#!/usr/bin/env bash
# run-rag-v2-prod-readonly.sh — Run the RAG v2 production read-only E2E test.
# Optionally verifies server-side search logs after the browser test.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

export RAG_UI_URL="${RAG_UI_URL:-https://rag-ui.nexusreussite.academy}"
export E2E_RESULTS="${E2E_RESULTS:-/tmp/rag-e2e-results}"
PROD_HOST="${RAG_PROD_HOST:-88.99.254.59}"

echo "=============================="
echo "  RAG v2 prod — read-only E2E"
echo "=============================="
echo "  URL:     $RAG_UI_URL"
echo "  Results: $E2E_RESULTS"
echo ""

mkdir -p "$E2E_RESULTS"

# Check Playwright is available
if ! npx playwright --version >/dev/null 2>&1; then
    echo "Playwright not found. Run: bash scripts/e2e/setup-playwright.sh"
    exit 1
fi

# Run Playwright test from the e2e directory (uses local node_modules)
cd "$SCRIPT_DIR"
npx playwright test \
    --config="playwright.config.js" \
    --reporter=list \
    --timeout=60000 \
    || E2E_EXIT=$?
cd "$REPO_ROOT"

E2E_EXIT=${E2E_EXIT:-0}

# --- Optional: server-side log verification ---
echo ""
echo "=============================="
echo "  Server-side log check"
echo "=============================="

if [ -f "$E2E_RESULTS/time-window.json" ]; then
    START_TIME=$(python3 -c "import json; print(json.load(open('$E2E_RESULTS/time-window.json'))['start'])" 2>/dev/null || echo "")
    END_TIME=$(python3 -c "import json; print(json.load(open('$E2E_RESULTS/time-window.json'))['end'])" 2>/dev/null || echo "")

    if [ -n "$START_TIME" ] && ssh -o ConnectTimeout=5 -o BatchMode=yes "root@$PROD_HOST" true 2>/dev/null; then
        echo "  Checking docker logs rag_ingestor for POST /search/v2..."
        SEARCH_LOGS=$(ssh "root@$PROD_HOST" "docker logs rag_ingestor --since='$START_TIME' --until='$END_TIME' 2>&1 | grep 'POST.*search' || true")
        if [ -n "$SEARCH_LOGS" ]; then
            echo "  CONFIRMED: search requests found in server logs."
            echo "$SEARCH_LOGS" | head -5
        else
            echo "  INFO: No search requests found in server logs (may be expected if query returned cached/empty)."
        fi
    else
        echo "  SKIP: server log check (SSH unavailable or no time window)."
    fi
else
    echo "  SKIP: no time-window.json produced."
fi

echo ""
echo "=============================="
echo "  Results in: $E2E_RESULTS"
echo "=============================="
ls -la "$E2E_RESULTS/" 2>/dev/null || true

exit "$E2E_EXIT"
