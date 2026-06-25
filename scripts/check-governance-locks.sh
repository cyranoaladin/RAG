#!/usr/bin/env bash
# check-governance-locks.sh — Fail if any governance lock has changed value
# without an ADR reference on an added line in the diff.
#
# The baseline records the EXPECTED state of each lock (false or true).
# A lock at true in the baseline must have an ADR comment on its baseline line.
# Any deviation from baseline → fail (unless ADR on added diff line).
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

# Extract all *_allowed lines from contract (strip comments, whitespace)
extract_locks() {
    local file="$1"
    { grep -E '^\s*\w+_allowed:\s*(true|false)' "$file" || true; } \
        | sed 's/#.*//' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//' | sort
}

# Extract baseline (strip comments for comparison)
extract_baseline() {
    local file="$1"
    grep -E '\w+_allowed:\s*(true|false)' "$file" \
        | sed 's/#.*//' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//' | sort
}

CURRENT=$(extract_locks "$CONTRACT_FILE")
BASELINE=$(extract_baseline "$BASELINE_FILE")

count_lines() {
    local text="$1"
    if [ -z "$text" ]; then echo 0; else echo "$text" | wc -l | tr -d ' '; fi
}

BASELINE_COUNT=$(count_lines "$BASELINE")
CURRENT_COUNT=$(count_lines "$CURRENT")

echo "Governance locks: baseline=$BASELINE_COUNT, current=$CURRENT_COUNT"

# Key-by-key: every baseline entry must match in current
MISSING=$(comm -23 <(echo "$BASELINE") <( if [ -n "$CURRENT" ]; then echo "$CURRENT"; fi ))

if [ -n "$MISSING" ]; then
    echo "FAIL: the following locks deviate from baseline:"
    echo "$MISSING"

    # Check if an ADR is referenced on an added line in the diff
    if git diff origin/main...HEAD -- "$CONTRACT_FILE" 2>/dev/null | grep '^+' | grep -Eq 'ADR-[0-9]+'; then
        echo "ADR reference found on an added line in the diff — allowing."
        exit 0
    fi

    echo "No ADR reference found on added lines. Blocking."
    exit 1
fi

echo "OK: all governance locks match baseline ($CURRENT_COUNT keys verified)."
