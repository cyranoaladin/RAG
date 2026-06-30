#!/usr/bin/env bash
set -euo pipefail

confirm_readonly=false
expected_sha=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --confirm-readonly)
      confirm_readonly=true
      shift
      ;;
    --expected-sha)
      expected_sha="${2:-}"
      shift 2
      ;;
    --delete)
      echo "Refusing destructive option" >&2
      exit 1
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

if [ "$confirm_readonly" != "true" ]; then
  echo "Missing --confirm-readonly" >&2
  exit 1
fi

if [ -z "$expected_sha" ]; then
  echo "Missing --expected-sha" >&2
  exit 1
fi

if [ -z "${PROD_TARGET:-}" ]; then
  echo "PROD_TARGET is required" >&2
  exit 1
fi

current_branch="$(git branch --show-current)"
if [ "$current_branch" != "main" ]; then
  echo "Dry-run must be executed from main" >&2
  exit 1
fi

if [ -n "$(git status --short)" ]; then
  echo "Workspace must be clean" >&2
  exit 1
fi

current_sha="$(git rev-parse HEAD)"
if [ "$current_sha" != "$expected_sha" ]; then
  echo "SHA mismatch: current HEAD does not match expected SHA" >&2
  exit 1
fi

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

emit_rsync() {
  destination="$1"
  shift
  command="rsync -nci"
  for path in "$@"; do
    case "$path" in
      *".env"*|*"creds"*|*"credential"*|*"secret"*)
        echo "Refusing sensitive path in dry-run plan" >&2
        exit 1
        ;;
    esac
    command="$command $path"
  done
  command="$command ${PROD_TARGET%/}/$destination"
  case "$command" in
    *" --delete"*|*"rsync -ci "*|*"rsync -aci "*)
      echo "Refusing unsafe rsync command" >&2
      exit 1
      ;;
  esac
  printf '%s\n' "$command"
}

emit_rsync "ingestor/" \
  "services/rag-engine/src/ingestor/api.py" \
  "services/rag-engine/src/ingestor/admin_api.py" \
  "services/rag-engine/src/ingestor/collection_config.py" \
  "services/rag-engine/src/ingestor/retrieval_contract_adapter.py"

emit_rsync "ui/" \
  "services/rag-engine/src/ui/app_v2.py"

emit_rsync "configs/" \
  "services/rag-engine/configs/rag_collections.yml" \
  "services/rag-engine/configs/legacy_collection_mapping.yml"

emit_rsync "./" \
  "services/rag-engine/infra/docker-compose.prod.yml" \
  "services/rag-engine/infra/docker-compose.override.prod.yml"
