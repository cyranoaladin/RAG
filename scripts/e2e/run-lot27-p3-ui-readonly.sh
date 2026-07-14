#!/usr/bin/env bash
# Lance les vérifications Playwright LOT 27 P3 sans action métier.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

export RAG_UI_URL="${RAG_UI_URL:-https://rag-ui.nexusreussite.academy}"
export E2E_RESULTS="${E2E_RESULTS:-/tmp/rag-lot27-p3-e2e-results}"

# Un worktree n'embarque pas node_modules. Réutiliser, si présent, celui du
# worktree principal sans inscrire de chemin machine-local dans le dépôt.
if ! node -e "require.resolve('playwright')" >/dev/null 2>&1; then
  PRIMARY_WORKTREE="$(git -C "$REPO_ROOT" worktree list --porcelain | awk '/^worktree / { sub(/^worktree /, ""); print; exit }')"
  if [[ -n "$PRIMARY_WORKTREE" && -d "$PRIMARY_WORKTREE/scripts/e2e/node_modules" ]]; then
    export NODE_PATH="$PRIMARY_WORKTREE/scripts/e2e/node_modules${NODE_PATH:+:$NODE_PATH}"
  fi
fi

if ! node -e "require.resolve('playwright')" >/dev/null 2>&1; then
  echo "Playwright introuvable. Installez les dépendances E2E puis relancez." >&2
  exit 1
fi

mkdir -p "$E2E_RESULTS"
node "$SCRIPT_DIR/lot27-p3-ui-readonly.js"
