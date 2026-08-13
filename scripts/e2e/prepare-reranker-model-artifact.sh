#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# prepare-reranker-model-artifact.sh
#
# Downloads the canonical reranker model into an external artifact directory
# — the reranker counterpart of prepare-embedding-model-artifact.sh (which
# only ever covered the embedding model; LOT H2-B remédiation, finding
# P2-real-model-ci-coverage). Runs ONLY in a local/artifact-build or CI
# context, NEVER in production runtime. Produces a verified, checksummed
# model cache, in the exact manifest.json/SHA256SUMS shape that
# reranker_contract.verify_reranker_artifact expects.
#
# Required environment:
#   MODEL_ARTIFACT_DIR       — absolute path to the artifact output directory
#   RERANKER_MODEL_REVISION  — HuggingFace revision (commit hash, never "main")
#
# Optional:
#   RERANKER_MODEL_ID        — default: cross-encoder/ms-marco-MiniLM-L-6-v2
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CANONICAL_MODEL="cross-encoder/ms-marco-MiniLM-L-6-v2"

# --- Guards ---

if [ -z "${MODEL_ARTIFACT_DIR:-}" ]; then
    echo "ERROR: MODEL_ARTIFACT_DIR is not set." >&2
    exit 1
fi

case "$MODEL_ARTIFACT_DIR" in
    /*)  ;;
    *)
        echo "ERROR: MODEL_ARTIFACT_DIR must be an absolute path." >&2
        echo "       Got: $MODEL_ARTIFACT_DIR" >&2
        exit 1
        ;;
esac

if [ -z "${RERANKER_MODEL_REVISION:-}" ]; then
    echo "ERROR: RERANKER_MODEL_REVISION is not set." >&2
    exit 1
fi

MODEL_ID="${RERANKER_MODEL_ID:-$CANONICAL_MODEL}"

if [ "$MODEL_ID" != "$CANONICAL_MODEL" ]; then
    echo "ERROR: Only $CANONICAL_MODEL is allowed. Got: $MODEL_ID" >&2
    exit 1
fi

REAL_ARTIFACT="$(realpath -m "$MODEL_ARTIFACT_DIR")"
REAL_REPO="$(realpath "$REPO_ROOT")"

if [ "$REAL_ARTIFACT" = "/" ]; then
    echo "ERROR: MODEL_ARTIFACT_DIR must not be the filesystem root." >&2
    exit 1
fi

case "$REAL_ARTIFACT" in
    "$REAL_REPO"|"$REAL_REPO"/*)
        echo "ERROR: MODEL_ARTIFACT_DIR must be outside the git repository." >&2
        echo "       Got: $REAL_ARTIFACT" >&2
        echo "       Repo: $REAL_REPO" >&2
        exit 1
        ;;
esac

MODEL_ARTIFACT_DIR="$REAL_ARTIFACT"

if [ "${RAG_ENV:-}" = "production" ]; then
    echo "ERROR: This script must not run in production (RAG_ENV=production)." >&2
    exit 1
fi

# --- Download model snapshot ---

mkdir -p "$MODEL_ARTIFACT_DIR"

echo "Downloading model: $MODEL_ID (revision: $RERANKER_MODEL_REVISION)"
echo "Target directory: $MODEL_ARTIFACT_DIR"

python3 -c "
import os

from huggingface_hub import snapshot_download

target = os.environ['MODEL_ARTIFACT_DIR']
model_id = '$MODEL_ID'
revision = os.environ['RERANKER_MODEL_REVISION']

local_dir = snapshot_download(
    repo_id=model_id,
    revision=revision,
    local_dir=target,
)
print(f'Downloaded to: {local_dir}')
"

echo "Download complete."

# --- Generate manifest.json ---

echo "Generating manifest.json..."

FILE_COUNT=$(find "$MODEL_ARTIFACT_DIR" -type f ! -name SHA256SUMS ! -name manifest.json | wc -l)
TOTAL_SIZE=$(find "$MODEL_ARTIFACT_DIR" -type f ! -name SHA256SUMS ! -name manifest.json -exec stat --format='%s' {} + 2>/dev/null | paste -sd+ | bc 2>/dev/null || echo "0")
REPO_COMMIT=$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo "unknown")
PYTHON_VERSION=$(python3 --version 2>/dev/null | head -1 || echo "unknown")
HF_HUB_VERSION=$(python3 -c "import huggingface_hub; print(huggingface_hub.__version__)" 2>/dev/null || echo "unknown")
ST_VERSION=$(python3 -c "import sentence_transformers; print(sentence_transformers.__version__)" 2>/dev/null || echo "unknown")

python3 -c "
import json

manifest = {
    'model_id': '$MODEL_ID',
    'revision_requested': '${RERANKER_MODEL_REVISION}',
    'file_count': $FILE_COUNT,
    'total_size_bytes': $TOTAL_SIZE,
    'generated_at': __import__('datetime').datetime.utcnow().isoformat() + 'Z',
    'repo_commit': '$REPO_COMMIT',
    'python_version': '$PYTHON_VERSION',
    'huggingface_hub_version': '$HF_HUB_VERSION',
    'sentence_transformers_version': '$ST_VERSION',
}

with open('$MODEL_ARTIFACT_DIR/manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)

print(json.dumps(manifest, indent=2))
"

# --- Generate the exact SHA256 inventory, including manifest.json ---

echo "Generating SHA256SUMS..."
CHECKSUM_FILE="$MODEL_ARTIFACT_DIR/SHA256SUMS"

(cd "$MODEL_ARTIFACT_DIR" && \
    find . -type f ! -name SHA256SUMS -print0 | \
    sort -z | \
    xargs -0 sha256sum | \
    sed 's|  \./|  |' \
) > "$CHECKSUM_FILE"

echo "SHA256SUMS generated: $(wc -l < "$CHECKSUM_FILE") files."
INVENTORY_SHA256="$(sha256sum "$CHECKSUM_FILE" | awk '{print $1}')"

echo ""
echo "=== Artifact preparation complete ==="
echo "Directory: $MODEL_ARTIFACT_DIR"
echo "Manifest:  $MODEL_ARTIFACT_DIR/manifest.json"
echo "Checksums: $MODEL_ARTIFACT_DIR/SHA256SUMS"
echo "Inventory SHA-256 (conserver hors artefact): $INVENTORY_SHA256"
