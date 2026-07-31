#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="${1:-$(git rev-parse --show-toplevel)}"
if ! INSIDE_WORK_TREE="$(
    git -C "$REPO_ROOT" rev-parse --is-inside-work-tree 2>/dev/null
)" || [ "$INSIDE_WORK_TREE" != "true" ]; then
    echo "ERROR: repository root is not a Git worktree: $REPO_ROOT" >&2
    exit 2
fi

TRACKED_LIST="$(mktemp)"
trap 'rm -f "$TRACKED_LIST"' EXIT
if ! git -C "$REPO_ROOT" ls-files -z -- \
        ':(top,glob)MANIFEST_LOT*.md' \
        ':(top,glob)*.tar' \
        ':(top,glob)*.tar.gz' \
        ':(top,glob)*.tgz' \
        ':(top,glob)*.zip' > "$TRACKED_LIST"; then
    echo "ERROR: unable to inspect tracked repository files" >&2
    exit 2
fi
mapfile -d '' -t OFFENDERS < "$TRACKED_LIST"

if [ "${#OFFENDERS[@]}" -ne 0 ]; then
    echo "ERROR: tracked delivery artifacts are forbidden at repository root:" >&2
    printf '  %q\n' "${OFFENDERS[@]}" >&2
    exit 1
fi

echo "PASS: tracked repository root is clean"
