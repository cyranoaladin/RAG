#!/usr/bin/env bash
# Confirms that CI local cannot recurse through an audit script.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CI_LOCAL="$REPO_ROOT/scripts/ci-local.sh"
PR_AUDIT="$REPO_ROOT/scripts/audit/rag-pr-audit.sh"

failures=0

if grep -Fq 'NEXUS_CI_LOCAL_RUNNING' "$CI_LOCAL"; then
    echo "PASS sentinel de réentrance présente"
else
    echo "FAIL sentinelle NEXUS_CI_LOCAL_RUNNING absente" >&2
    failures=$((failures + 1))
fi

if ! grep -Eq '(^|[[:space:]])(bash[[:space:]]+)?scripts/ci-local\.sh([[:space:]]|$)' "$PR_AUDIT"; then
    echo "PASS audit découplé de ci-local"
else
    echo "FAIL scripts/audit/rag-pr-audit.sh rappelle scripts/ci-local.sh" >&2
    failures=$((failures + 1))
fi

if grep -Eq 'rag-pr-audit\.sh' "$CI_LOCAL"; then
    echo "FAIL ci-local appelle un audit de PR" >&2
    failures=$((failures + 1))
else
    echo "PASS ci-local ne dépend pas d'un audit de PR"
fi

if [ "$failures" -gt 0 ]; then
    exit 1
fi
