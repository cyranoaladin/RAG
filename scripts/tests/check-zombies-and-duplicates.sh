#!/usr/bin/env bash
# check-zombies-and-duplicates.sh — Detect zombie processes and container duplicates.
# Exit 1 if any zombie or duplicate is found.
set -euo pipefail

ERRORS=0

echo "=============================="
echo "  Local zombie processes"
echo "=============================="
# Exclude known browser sandbox zombies (zypak-sandbox, chrome-sandbox)
ZOMBIES=$(ps -eo pid,ppid,stat,cmd 2>/dev/null | awk '$3 ~ /Z/ && !/zypak-sandbox/ && !/chrome-sandbox/ {print}' || true)
if [ -n "$ZOMBIES" ]; then
    echo "FAIL: zombie processes found:"
    echo "$ZOMBIES"
    ((ERRORS++))
else
    echo "  No zombies (excluding known browser sandbox artifacts)."
fi

echo ""
echo "=============================="
echo "  Local stale test runners"
echo "=============================="
STALE=$(pgrep -af 'playwright-rag-v2-prod|temp-execution|pip.*requirements.lock|ci-local.sh' 2>/dev/null || true)
if [ -n "$STALE" ]; then
    echo "WARN: stale processes found:"
    echo "$STALE"
else
    echo "  No stale test runners."
fi

echo ""
echo "=============================="
echo "  Production containers (read-only SSH)"
echo "=============================="
PROD_HOST="${RAG_PROD_HOST:-88.99.254.59}"

if ssh -o ConnectTimeout=5 -o BatchMode=yes "root@$PROD_HOST" true 2>/dev/null; then
    ssh "root@$PROD_HOST" bash -s <<'REMOTE'
set -euo pipefail

echo "--- Duplicate container names ---"
DUPES=$(docker ps --format "{{.Names}}" | sort | uniq -d)
if [ -n "$DUPES" ]; then
    echo "FAIL: duplicate containers:"
    echo "$DUPES"
    exit 1
else
    echo "  No duplicates."
fi

echo ""
echo "--- RAG containers ---"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -E "rag_|compose-" || echo "  (none running)"

echo ""
echo "--- Remote zombies ---"
RZOMBIES=$(ps -eo pid,ppid,stat,cmd | awk '$3 ~ /Z/ {print}' || true)
if [ -n "$RZOMBIES" ]; then
    echo "WARN: remote zombie processes:"
    echo "$RZOMBIES"
else
    echo "  No remote zombies."
fi
REMOTE
else
    echo "  SKIP: cannot reach $PROD_HOST via SSH (non-blocking)."
fi

echo ""
echo "=============================="
if [ "$ERRORS" -gt 0 ]; then
    echo "  RESULT: $ERRORS issue(s) found."
    exit 1
else
    echo "  RESULT: clean."
fi
exit 0
