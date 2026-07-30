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
    local resolved
    if [[ -n "${PYTHON_BIN:-}" ]]; then
        resolved="$(command -v "$PYTHON_BIN" 2>/dev/null || true)"
        if [[ -n "$resolved" ]] && "$resolved" -c "import yaml" 2>/dev/null; then
            printf '%s\n' "$resolved"
            return 0
        fi
        echo "Interpréteur Python avec PyYAML introuvable: ${PYTHON_BIN}" >&2
        return 1
    fi

    candidate="$REPO_ROOT/services/rag-pedago/.venv/bin/python"
    if [[ -x "$candidate" ]] && "$candidate" -c "import yaml" 2>/dev/null; then
        printf '%s\n' "$candidate"
        return 0
    fi

    for candidate in python3 python; do
        resolved="$(command -v "$candidate" 2>/dev/null || true)"
        if [[ -n "$resolved" ]] && "$resolved" -c "import yaml" 2>/dev/null; then
            printf '%s\n' "$resolved"
            return 0
        fi
    done

    echo "Interpréteur Python avec PyYAML introuvable." >&2
    return 1
}

PYTHON_CMD="$(find_python)"
"$PYTHON_CMD" "$ARCHIVE_ROOT/scripts/lib/validate_cockpit_snapshots.py" \
  "$ARCHIVE_ROOT/services/cockpit/src/data/sources.json" \
  "$ARCHIVE_ROOT/services/rag-pedago/configs/eduscol_sources.yml" \
  "$ARCHIVE_ROOT/services/cockpit/src/data/collections.json" \
  "$ARCHIVE_ROOT/services/rag-engine/configs/rag_collections.yml"

cd "$ARCHIVE_ROOT/services/cockpit"
SOURCE_NODE_MODULES="$REPO_ROOT/services/cockpit/node_modules"
if [[ ! -x "$SOURCE_NODE_MODULES/.bin/next" ]]; then
  echo "Dépendances cockpit absentes: préparez-les hors de full-regression." >&2
  exit 1
fi

# L'arbre source reste propre, mais les dépendances déjà préparées sont
# réutilisées dans l'arbre temporaire. Une copie locale est nécessaire :
# Turbopack refuse un lien qui sort de la racine du projet. Cette porte ne
# déclenche donc jamais une installation réseau.
mkdir node_modules
tar -C "$SOURCE_NODE_MODULES" -cf - . | tar -C node_modules -xf -
npm run build
