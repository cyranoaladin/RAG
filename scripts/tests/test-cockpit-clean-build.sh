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

find_python() {
  local candidate
  if [[ -n "${PYTHON_BIN:-}" ]]; then
    if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
      command -v "$PYTHON_BIN"
      return 0
    fi
    echo "Interpréteur Python introuvable: ${PYTHON_BIN}" >&2
    return 1
  fi

  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1; then
      command -v "$candidate"
      return 0
    fi
  done

  echo "Interpréteur Python introuvable (essayé: python3, python)." >&2
  return 1
}

PYTHON_CMD="$(find_python)"
"$PYTHON_CMD" "$ARCHIVE_ROOT/scripts/lib/validate_cockpit_snapshots.py" \
  "$ARCHIVE_ROOT/services/cockpit/src/data/sources.json" \
  "$ARCHIVE_ROOT/services/rag-pedago/configs/eduscol_sources.yml" \
  "$ARCHIVE_ROOT/services/cockpit/src/data/collections.json" \
  "$ARCHIVE_ROOT/services/rag-engine/configs/rag_collections.yml"

cd "$ARCHIVE_ROOT/services/cockpit"
npm ci
npm run build
