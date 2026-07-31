#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
TMP_ROOT="$(mktemp -d)"
trap 'rm -rf "$TMP_ROOT"' EXIT

mkdir -p "$TMP_ROOT/repo/scripts"
awk '
    /^SCRIPT_DIR=/ && !inserted {
        print "echo \"FAIL: re-entry guard was bypassed\" >&2"
        print "exit 86"
        inserted = 1
    }
    { print }
    END { if (!inserted) exit 1 }
' "$REPO_ROOT/scripts/ci-local.sh" > "$TMP_ROOT/repo/scripts/ci-local.sh"

set +e
OUTPUT="$({
    NEXUS_CI_LOCAL_RUNNING=1 \
        bash "$TMP_ROOT/repo/scripts/ci-local.sh"
} 2>&1)"
STATUS=$?
set -e

if [ "$STATUS" -ne 2 ]; then
    echo "FAIL: expected re-entry exit 2, got $STATUS" >&2
    echo "$OUTPUT" >&2
    exit 1
fi
grep -Fq "ERROR: ci-local.sh refuse une réentrance" <<<"$OUTPUT"
if grep -Fq "FAIL: re-entry guard was bypassed" <<<"$OUTPUT"; then
    echo "FAIL: re-entry was rejected after the safe stop point" >&2
    exit 1
fi

create_parent_child_probe() {
    local source_file="$1"
    local probe_file="$2"

    awk '
        /^SCRIPT_DIR=/ && !inserted {
            print "if [ \"${NEXUS_CI_TOPOLOGY_PARENT:-0}\" = \"1\" ]; then"
            print "    unset NEXUS_CI_TOPOLOGY_PARENT"
            print "    exec bash \"$0\""
            print "fi"
            print "echo \"FAIL: child reached re-entry sentinel\" >&2"
            print "exit 86"
            inserted = 1
        }
        { print }
        END { if (!inserted) exit 1 }
    ' "$source_file" > "$probe_file"
}

run_parent_child_probe() {
    local source_file="$1"
    local probe_file="$2"

    create_parent_child_probe "$source_file" "$probe_file"
    set +e
    PARENT_CHILD_OUTPUT="$({
        env -u NEXUS_CI_LOCAL_RUNNING \
            NEXUS_CI_TOPOLOGY_PARENT=1 \
            bash "$probe_file"
    } 2>&1)"
    PARENT_CHILD_STATUS=$?
    set -e
}

parent_child_was_rejected() {
    local status="$1"
    local output="$2"

    [ "$status" -eq 2 ] \
        && grep -Fq "ERROR: ci-local.sh refuse une réentrance" <<<"$output" \
        && ! grep -Fq "FAIL: child reached re-entry sentinel" <<<"$output"
}

PARENT_CHILD_PROBE="$TMP_ROOT/repo/scripts/ci-local-parent-child.sh"
run_parent_child_probe \
    "$REPO_ROOT/scripts/ci-local.sh" \
    "$PARENT_CHILD_PROBE"
if ! parent_child_was_rejected \
    "$PARENT_CHILD_STATUS" \
    "$PARENT_CHILD_OUTPUT"; then
    echo "FAIL: child process was not rejected before the sentinel" >&2
    echo "$PARENT_CHILD_OUTPUT" >&2
    exit 1
fi

NO_EXPORT_SOURCE="$TMP_ROOT/repo/scripts/ci-local-without-export.sh"
awk '$0 != "export NEXUS_CI_LOCAL_RUNNING=1" { print }' \
    "$REPO_ROOT/scripts/ci-local.sh" > "$NO_EXPORT_SOURCE"
run_parent_child_probe \
    "$NO_EXPORT_SOURCE" \
    "$TMP_ROOT/repo/scripts/ci-local-without-export-probe.sh"
if parent_child_was_rejected \
    "$PARENT_CHILD_STATUS" \
    "$PARENT_CHILD_OUTPUT"; then
    echo "FAIL: parent-child probe accepts a missing marker export" >&2
    exit 1
fi
if [ "$PARENT_CHILD_STATUS" -ne 86 ] \
    || ! grep -Fq "FAIL: child reached re-entry sentinel" \
        <<<"$PARENT_CHILD_OUTPUT"; then
    echo "FAIL: missing-export mutation did not reach the sentinel" >&2
    echo "$PARENT_CHILD_OUTPUT" >&2
    exit 1
fi

assert_no_call_reference() {
    local source_file="$1"
    local forbidden_reference="$2"
    local failure_message="$3"

    if grep -Fq "$forbidden_reference" "$source_file"; then
        echo "FAIL: $failure_message" >&2
        return 1
    fi
    return 0
}

assert_no_call_reference \
    "$REPO_ROOT/scripts/audit/rag-pr-audit.sh" \
    "ci-local.sh" \
    "rag-pr-audit.sh invokes ci-local.sh"
assert_no_call_reference \
    "$REPO_ROOT/scripts/ci-local.sh" \
    "rag-pr-audit.sh" \
    "ci-local.sh invokes rag-pr-audit.sh"

MUTATED_AUDIT="$TMP_ROOT/rag-pr-audit-with-quoted-call.sh"
printf '%s\n' 'bash "$REPO_ROOT/scripts/ci-local.sh"' > "$MUTATED_AUDIT"
if assert_no_call_reference \
    "$MUTATED_AUDIT" \
    "ci-local.sh" \
    "quoted audit mutation invokes ci-local.sh" >/dev/null 2>&1; then
    echo "FAIL: quoted ci-local.sh call was not rejected" >&2
    exit 1
fi

MUTATED_CI_LOCAL="$TMP_ROOT/ci-local-with-quoted-call.sh"
printf '%s\n' \
    'bash "$REPO_ROOT/scripts/audit/rag-pr-audit.sh"' \
    > "$MUTATED_CI_LOCAL"
if assert_no_call_reference \
    "$MUTATED_CI_LOCAL" \
    "rag-pr-audit.sh" \
    "quoted CI mutation invokes rag-pr-audit.sh" >/dev/null 2>&1; then
    echo "FAIL: quoted rag-pr-audit.sh call was not rejected" >&2
    exit 1
fi

echo "PASS: CI topology is acyclic and re-entry fails closed"
