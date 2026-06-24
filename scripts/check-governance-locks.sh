#!/usr/bin/env bash
# check-governance-locks.sh — Fail if any governance lock has been weakened
# without an ADR reference on an added line in the diff.
#
# Override paths for testing:
#   GOVERNANCE_CONTRACT_FILE  — path to the contract YAML
#   GOVERNANCE_BASELINE_FILE  — path to the baseline file
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTRACT_FILE="${GOVERNANCE_CONTRACT_FILE:-services/rag-pedago/configs/pedago_interface_contract.yml}"
BASELINE_FILE="${GOVERNANCE_BASELINE_FILE:-$SCRIPT_DIR/governance-locks.baseline}"

if [ ! -f "$CONTRACT_FILE" ]; then
    echo "ERROR: $CONTRACT_FILE not found"
    exit 1
fi

if [ ! -f "$BASELINE_FILE" ]; then
    echo "ERROR: $BASELINE_FILE not found"
    exit 1
fi

# Extract current locks (sorted). Tolerate zero matches from grep.
CURRENT=$( { grep -E '^\s*\w+_allowed:\s*false' "$CONTRACT_FILE" || true; } | sed 's/^[[:space:]]*//' | sort )
BASELINE=$(sort "$BASELINE_FILE")

# Count non-empty lines (echo on empty string still produces 1 line with wc -l)
count_lines() {
    local text="$1"
    if [ -z "$text" ]; then
        echo 0
    else
        echo "$text" | wc -l | tr -d ' '
    fi
}

BASELINE_COUNT=$(count_lines "$BASELINE")
CURRENT_COUNT=$(count_lines "$CURRENT")

echo "Governance locks: baseline=$BASELINE_COUNT, current=$CURRENT_COUNT"

# Key-by-key comparison: every baseline line must be present in current
MISSING=$(comm -23 <(echo "$BASELINE") <( if [ -n "$CURRENT" ]; then echo "$CURRENT"; fi ) )

if [ -n "$MISSING" ]; then
    echo "FAIL: the following locks from baseline are missing or weakened:"
    echo "$MISSING"

    # Check if an ADR is referenced on an added line in the diff
    if git diff origin/main...HEAD -- "$CONTRACT_FILE" 2>/dev/null | grep '^+' | grep -Eq 'ADR-[0-9]+'; then
        echo "ADR reference found on an added line in the diff — allowing."
        exit 0
    fi

    echo "No ADR reference found on added lines. Blocking."
    exit 1
fi

# Also check count hasn't decreased
if [ "$CURRENT_COUNT" -lt "$BASELINE_COUNT" ]; then
    echo "FAIL: lock count decreased from $BASELINE_COUNT to $CURRENT_COUNT."
    exit 1
fi

echo "OK: all governance locks intact ($CURRENT_COUNT keys verified)."
