#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# prepare-embedding-model-artifact.sh
#
# Downloads the canonical embedding model into an external artifact directory.
# This script runs ONLY in a local/artifact-build context, NEVER in production
# runtime.  It produces a verified, checksummed model cache that can later be
# mounted read-only into ingestor/worker containers.
#
# Required environment:
#   MODEL_ARTIFACT_DIR          — absolute path to the artifact output directory
#   EMBEDDING_MODEL_REVISION    — HuggingFace revision (commit hash or tag)
#
# Optional:
#   EMBEDDING_MODEL_ID          — default: intfloat/multilingual-e5-large
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

CANONICAL_MODEL="intfloat/multilingual-e5-large"
CANONICAL_DIM=1024

# --- Guards ---

if [ -z "${MODEL_ARTIFACT_DIR:-}" ]; then
    echo "ERROR: MODEL_ARTIFACT_DIR is not set." >&2
    exit 1
fi

# Must be an absolute path
case "$MODEL_ARTIFACT_DIR" in
    /*)  ;;
    *)
        echo "ERROR: MODEL_ARTIFACT_DIR must be an absolute path." >&2
        echo "       Got: $MODEL_ARTIFACT_DIR" >&2
        exit 1
        ;;
esac

if [ -z "${EMBEDDING_MODEL_REVISION:-}" ]; then
    echo "ERROR: EMBEDDING_MODEL_REVISION is not set." >&2
    exit 1
fi

MODEL_ID="${EMBEDDING_MODEL_ID:-$CANONICAL_MODEL}"

if [ "$MODEL_ID" != "$CANONICAL_MODEL" ]; then
    echo "ERROR: Only $CANONICAL_MODEL is allowed. Got: $MODEL_ID" >&2
    exit 1
fi

# Normalize to canonical form (no trailing slash, symlinks resolved where
# possible).  realpath -m works even if the directory does not exist yet.
REAL_ARTIFACT="$(realpath -m "$MODEL_ARTIFACT_DIR")"
REAL_REPO="$(realpath "$REPO_ROOT")"

# Refuse filesystem root
if [ "$REAL_ARTIFACT" = "/" ]; then
    echo "ERROR: MODEL_ARTIFACT_DIR must not be the filesystem root." >&2
    exit 1
fi

# Refuse if artifact dir is the repo root or inside it
case "$REAL_ARTIFACT" in
    "$REAL_REPO"|"$REAL_REPO"/*)
        echo "ERROR: MODEL_ARTIFACT_DIR must be outside the git repository." >&2
        echo "       Got: $REAL_ARTIFACT" >&2
        echo "       Repo: $REAL_REPO" >&2
        exit 1
        ;;
esac

# Reassign to normalized path — all subsequent operations use this
MODEL_ARTIFACT_DIR="$REAL_ARTIFACT"

# Refuse in production
if [ "${RAG_ENV:-}" = "production" ]; then
    echo "ERROR: This script must not run in production (RAG_ENV=production)." >&2
    exit 1
fi

# --- Download model snapshot ---

mkdir -p "$MODEL_ARTIFACT_DIR"

echo "Downloading model: $MODEL_ID (revision: $EMBEDDING_MODEL_REVISION)"
echo "Target directory: $MODEL_ARTIFACT_DIR"

# ACQUISITION ONLY.  Nothing below this block may alter the sealing stage:
# the SHA256SUMS generation and the inventory fingerprint are the authority of
# this script and are byte-identical to their pre-2026-08-28 form.
#
# Offline path (HF_HUB_OFFLINE=1): `snapshot_download` bypasses the shared hub
# cache whenever `local_dir` is passed — the huggingface_hub documentation is
# explicit ("the `cache_dir` will not be used, and a `.cache/huggingface/`
# folder will be created at the root of `local_dir`").  A fresh target
# directory therefore has nothing to resolve from, and the call fails with
# LocalEntryNotFoundError even when the pinned revision is fully cached.
#
# Resolving WITHOUT `local_dir` returns the hub cache snapshot, which is then
# copied into the artifact directory.  The revision stays pinned either way.
# Hub cache entries are symlinks into ../../blobs; the copy dereferences them,
# because the runtime verifier rejects symlinked artifacts.
python3 -c "
import os
import shutil
import sys
from pathlib import Path

from huggingface_hub import snapshot_download

target = Path(os.environ['MODEL_ARTIFACT_DIR'])
model_id = '$MODEL_ID'
revision = os.environ['EMBEDDING_MODEL_REVISION']
offline = os.environ.get('HF_HUB_OFFLINE', '') not in ('', '0', 'false', 'False')

if not offline:
    local_dir = snapshot_download(
        repo_id=model_id,
        revision=revision,
        local_dir=str(target),
    )
    print(f'Downloaded to: {local_dir}')
    sys.exit(0)

resolved = Path(
    snapshot_download(repo_id=model_id, revision=revision)
).resolve(strict=True)
print(f'Resolved from local hub cache (offline): {resolved}')

copied = 0
for source in sorted(resolved.rglob('*')):
    if not source.is_file():
        continue
    relative = source.relative_to(resolved)
    if relative.parts and relative.parts[0] == '.cache':
        continue
    destination = target / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    # copyfile follows symlinks: the hub cache stores blobs behind links, and
    # the runtime verifier refuses any symlink inside an artifact.
    shutil.copyfile(source, destination)
    shutil.copymode(source, destination)
    copied += 1

if not copied:
    raise SystemExit('offline snapshot resolved to an empty directory')
print(f'Copied {copied} files into: {target}')
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
import json, sys

manifest = {
    'model_id': '$MODEL_ID',
    'canonical_dim': $CANONICAL_DIM,
    'revision_requested': '${EMBEDDING_MODEL_REVISION}',
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

# Generate checksums from inside the artifact dir so paths are relative.
# The manifest carries the canonical identity and must itself be authenticated.
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
