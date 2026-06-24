#!/usr/bin/env bash
# check-governance-locks.sh — Fail if governance locks have been weakened
# without an ADR reference in the commit diff.
set -euo pipefail

CONTRACT_FILE="services/rag-pedago/configs/pedago_interface_contract.yml"
EXPECTED_MIN=17  # baseline count of "allowed: false" at Lot 0

if [ ! -f "$CONTRACT_FILE" ]; then
    echo "ERROR: $CONTRACT_FILE not found"
    exit 1
fi

ACTUAL=$(grep -c 'allowed: false' "$CONTRACT_FILE")

echo "Governance locks: expected >= $EXPECTED_MIN, found $ACTUAL"

if [ "$ACTUAL" -lt "$EXPECTED_MIN" ]; then
    echo "FAIL: lock count dropped from $EXPECTED_MIN to $ACTUAL."
    echo "A governance lock was weakened. This requires a referenced ADR."

    # Check if the diff references an ADR
    if git diff HEAD~1 -- "$CONTRACT_FILE" 2>/dev/null | grep -qi 'ADR-'; then
        echo "ADR reference found in diff — allowing."
        exit 0
    fi

    echo "No ADR reference found in the diff. Blocking."
    exit 1
fi

echo "OK: governance locks intact."
