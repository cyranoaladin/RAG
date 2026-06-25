#!/usr/bin/env bash
# check-governance-locks.sh — Strict config-vs-baseline governance guard.
#
# Rules:
# 1. Every key in baseline must appear in config with the SAME value.
#    Any deviation → FAIL. No exceptions, no diff-based ADR bypass.
# 2. Every key at `true` in the baseline MUST have an ADR reference
#    (ADR-[0-9]+) on its own baseline line. A `true` without ADR → FAIL.
# 3. The baseline IS the registry of authorized states. Changing a lock
#    requires editing BOTH the baseline and the config in the same PR.
#
# Override paths for testing:
#   GOVERNANCE_CONTRACT_FILE  — path to the contract YAML
#   GOVERNANCE_BASELINE_FILE  — path to the baseline file
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTRACT_FILE="${GOVERNANCE_CONTRACT_FILE:-services/rag-pedago/configs/pedago_interface_contract.yml}"
BASELINE_FILE="${GOVERNANCE_BASELINE_FILE:-$SCRIPT_DIR/governance-locks.baseline}"

if [ ! -f "$CONTRACT_FILE" ]; then
    echo "ERROR: $CONTRACT_FILE not found"; exit 1
fi
if [ ! -f "$BASELINE_FILE" ]; then
    echo "ERROR: $BASELINE_FILE not found"; exit 1
fi

# --- Extract key:value from config (strip comments + whitespace) ---
extract_config() {
    { grep -E '^\s*\w+_allowed:\s*(true|false)' "$1" || true; } \
        | sed 's/#.*//' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//' | sort
}

# --- Extract key:value from baseline (strip comments for value comparison) ---
extract_baseline_values() {
    grep -E '\w+_allowed:\s*(true|false)' "$1" \
        | sed 's/#.*//' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//' | sort
}

CONFIG_STATE=$(extract_config "$CONTRACT_FILE")
BASELINE_STATE=$(extract_baseline_values "$BASELINE_FILE")

count_lines() {
    local text="$1"
    if [ -z "$text" ]; then echo 0; else echo "$text" | wc -l | tr -d ' '; fi
}

BASELINE_COUNT=$(count_lines "$BASELINE_STATE")
CONFIG_COUNT=$(count_lines "$CONFIG_STATE")
echo "Governance locks: baseline=$BASELINE_COUNT, config=$CONFIG_COUNT"

ERRORS=0

# --- Rule 1: strict config == baseline ---
DEVIATIONS=$(comm -3 <(echo "$BASELINE_STATE") <(echo "$CONFIG_STATE"))
if [ -n "$DEVIATIONS" ]; then
    echo "FAIL: config deviates from baseline:"
    # Show what's in baseline but not config
    MISSING=$(comm -23 <(echo "$BASELINE_STATE") <(echo "$CONFIG_STATE"))
    if [ -n "$MISSING" ]; then
        echo "  Expected but missing/changed in config:"
        echo "$MISSING" | sed 's/^/    /'
    fi
    # Show what's in config but not baseline
    EXTRA=$(comm -13 <(echo "$BASELINE_STATE") <(echo "$CONFIG_STATE"))
    if [ -n "$EXTRA" ]; then
        echo "  In config but not matching baseline:"
        echo "$EXTRA" | sed 's/^/    /'
    fi
    ERRORS=$((ERRORS + 1))
fi

# --- Rule 2: every `true` in baseline must have ADR on its line ---
while IFS= read -r line; do
    key=$(echo "$line" | sed 's/#.*//' | sed 's/^[[:space:]]*//' | sed 's/[[:space:]]*$//')
    value=$(echo "$key" | grep -oP ':\s*\K(true|false)')
    keyname=$(echo "$key" | grep -oP '^\w+')
    if [ "$value" = "true" ]; then
        # Check that the ORIGINAL baseline line (with comments) has ADR-[0-9]+
        adr_id=$(echo "$line" | grep -oP 'ADR-\d+' || true)
        if [ -z "$adr_id" ]; then
            echo "FAIL: $keyname is true in baseline without ADR reference on its line."
            ERRORS=$((ERRORS + 1))
        else
            # Verify the referenced ADR file exists
            adr_file=$(find docs/adr/ -name "${adr_id}*" -type f 2>/dev/null | head -1)
            if [ -z "$adr_file" ]; then
                echo "FAIL: $keyname references $adr_id but no file docs/adr/${adr_id}*.md exists."
                ERRORS=$((ERRORS + 1))
            fi
        fi
    fi
done < "$BASELINE_FILE"

if [ "$ERRORS" -gt 0 ]; then
    echo "BLOCKED: $ERRORS governance violation(s)."
    exit 1
fi

echo "OK: all governance locks match baseline ($BASELINE_COUNT keys verified)."
