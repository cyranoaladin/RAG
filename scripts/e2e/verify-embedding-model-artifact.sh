#!/usr/bin/env bash
set -euo pipefail

# ============================================================================
# verify-embedding-model-artifact.sh
#
# Offline verification of a pre-built embedding model artifact.
# Does NOT download anything. Validates manifest, checksums, and optionally
# loads the model in local_files_only mode to confirm dimension.
#
# Required environment:
#   MODEL_ARTIFACT_DIR    — path to the model artifact directory
#
# Optional:
#   SKIP_LOAD_TEST        — set to "1" to skip the SentenceTransformer load test
# ============================================================================

CANONICAL_MODEL="intfloat/multilingual-e5-large"
CANONICAL_DIM=1024

ERRORS=0

fail() {
    echo "FAIL: $1" >&2
    ERRORS=$((ERRORS + 1))
}

# --- Guards ---

if [ -z "${MODEL_ARTIFACT_DIR:-}" ]; then
    echo "ERROR: MODEL_ARTIFACT_DIR is not set." >&2
    exit 1
fi

if [ ! -d "$MODEL_ARTIFACT_DIR" ]; then
    echo "ERROR: MODEL_ARTIFACT_DIR does not exist: $MODEL_ARTIFACT_DIR" >&2
    exit 1
fi

echo "Verifying artifact: $MODEL_ARTIFACT_DIR"

# --- Check manifest.json ---

MANIFEST="$MODEL_ARTIFACT_DIR/manifest.json"
if [ ! -f "$MANIFEST" ]; then
    fail "manifest.json not found"
else
    echo "OK: manifest.json exists"

    MODEL_ID=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m.get('model_id',''))" 2>/dev/null || echo "")
    MANIFEST_DIM=$(python3 -c "import json; m=json.load(open('$MANIFEST')); print(m.get('canonical_dim',0))" 2>/dev/null || echo "0")

    if [ "$MODEL_ID" != "$CANONICAL_MODEL" ]; then
        fail "manifest model_id='$MODEL_ID', expected '$CANONICAL_MODEL'"
    else
        echo "OK: model_id=$MODEL_ID"
    fi

    if [ "$MANIFEST_DIM" != "$CANONICAL_DIM" ]; then
        fail "manifest canonical_dim=$MANIFEST_DIM, expected $CANONICAL_DIM"
    else
        echo "OK: canonical_dim=$MANIFEST_DIM"
    fi
fi

# --- Check SHA256SUMS ---

CHECKSUMS="$MODEL_ARTIFACT_DIR/SHA256SUMS"
if [ ! -f "$CHECKSUMS" ]; then
    fail "SHA256SUMS not found"
else
    echo "OK: SHA256SUMS exists ($(wc -l < "$CHECKSUMS") entries)"

    pushd "$MODEL_ARTIFACT_DIR" > /dev/null
    if ! sha256sum --check --quiet "$CHECKSUMS" 2>/dev/null; then
        fail "SHA256SUMS verification failed"
    else
        echo "OK: all checksums verified"
    fi
    popd > /dev/null
fi

# --- Check no Nomic fallback ---
#
# Only detect explicit forbidden embedding model references.  Do NOT use a
# broad "nomic" substring match — the tokenizer vocabulary legitimately
# contains words like "economic", "economica", "economico".

FORBIDDEN_PATTERNS=(
    'nomic-embed-text'
    'nomic-embed-text:v1.5'
    'nomic-ai/nomic'
    'nomic_embed'
    'EMBED_DIM=768'
    'vector(768)'
)

NOMIC_HIT=0
for pattern in "${FORBIDDEN_PATTERNS[@]}"; do
    if grep -r -l --include='*.json' --include='*.yml' --include='*.yaml' \
         --include='*.py' --include='*.cfg' --include='*.toml' \
         -F "$pattern" "$MODEL_ARTIFACT_DIR" 2>/dev/null | head -1 | grep -q .; then
        fail "Forbidden embedding reference detected: $pattern"
        NOMIC_HIT=1
    fi
done

if [ "$NOMIC_HIT" -eq 0 ]; then
    echo "OK: no Nomic/768d fallback detected"
fi

# --- Optional: load model in offline mode ---

if [ "${SKIP_LOAD_TEST:-0}" != "1" ]; then
    echo "Loading model in local_files_only mode..."
    python3 -c "
import os, sys

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_DATASETS_OFFLINE'] = '1'

from sentence_transformers import SentenceTransformer

artifact_dir = os.environ['MODEL_ARTIFACT_DIR']
model = SentenceTransformer(artifact_dir, local_files_only=True)
dim = model.get_sentence_embedding_dimension()

if dim != $CANONICAL_DIM:
    print(f'FAIL: runtime dimension={dim}, expected=$CANONICAL_DIM', file=sys.stderr)
    sys.exit(1)

print(f'OK: model loaded offline, dimension={dim}')
" || {
        fail "offline model load test failed"
    }
else
    echo "SKIP: load test skipped (SKIP_LOAD_TEST=1)"
fi

# --- Summary ---

echo ""
if [ "$ERRORS" -gt 0 ]; then
    echo "VERIFICATION FAILED: $ERRORS error(s)" >&2
    exit 1
fi

echo "=== Artifact verification passed ==="
