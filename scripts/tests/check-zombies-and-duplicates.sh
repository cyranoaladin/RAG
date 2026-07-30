#!/usr/bin/env bash
# Static, deterministic hygiene check. Runtime processes and remote machines
# are deliberately outside full-regression's hermetic scope.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$REPO_ROOT"

errors=0

echo "=== Artéfacts zombies versionnés ==="
zombies="$(git ls-files -- '*.pid' '*.sock' '*.tmp' '*.tar.gz')"
if [[ -n "$zombies" ]]; then
    echo "FAIL: artéfacts éphémères versionnés:"
    echo "$zombies"
    errors=$((errors + 1))
else
    echo "PASS: aucun artéfact éphémère versionné"
fi

echo "=== Noms de conteneurs dupliqués ==="
mapfile -t compose_files < <(git ls-files 'services/rag-engine/infra/docker-compose*.yml')
container_names="$(
    if [[ ${#compose_files[@]} -gt 0 ]]; then
        awk '/^[[:space:]]*container_name:[[:space:]]*/ { print $2 }' "${compose_files[@]}"
    fi
)"
duplicates="$(printf '%s\n' "$container_names" | sed '/^$/d' | sort | uniq -d)"
if [[ -n "$duplicates" ]]; then
    echo "FAIL: noms de conteneurs dupliqués:"
    echo "$duplicates"
    errors=$((errors + 1))
else
    echo "PASS: aucun nom de conteneur dupliqué"
fi

if [[ "$errors" -gt 0 ]]; then
    exit 1
fi
