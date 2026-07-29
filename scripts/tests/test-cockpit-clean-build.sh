#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
BUILD_TREE="${COCKPIT_BUILD_TREE:-HEAD}"

if ! TREE_OID="$(
  git -C "$REPO_ROOT" rev-parse \
    --verify --quiet --end-of-options "${BUILD_TREE}^{tree}"
)"; then
  echo "COCKPIT_BUILD_TREE ne désigne pas un arbre Git valide: ${BUILD_TREE}" >&2
  exit 2
fi

ARCHIVE_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/nexus-cockpit-clean-build.XXXXXX")"
cleanup() {
  rm -rf -- "$ARCHIVE_ROOT"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

git -C "$REPO_ROOT" archive "$TREE_OID" | tar -x -C "$ARCHIVE_ROOT"

cd "$ARCHIVE_ROOT/services/cockpit"
npm ci
npm run build
