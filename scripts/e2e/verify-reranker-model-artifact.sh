#!/usr/bin/env bash
# Vérifier un artefact CrossEncoder préprovisionné, sans accès réseau.
set -euo pipefail

canonical_model="cross-encoder/ms-marco-MiniLM-L-6-v2"
artifact_dir="${MODEL_ARTIFACT_DIR:-}"

if [[ -z "$artifact_dir" || ! -d "$artifact_dir" ]]; then
    printf '%s\n' "ERROR: MODEL_ARTIFACT_DIR doit désigner un répertoire." >&2
    exit 1
fi
if [[ ! -f "$artifact_dir/manifest.json" ]]; then
    printf '%s\n' "ERROR: manifest.json absent." >&2
    exit 1
fi
if [[ ! -f "$artifact_dir/SHA256SUMS" ]]; then
    printf '%s\n' "ERROR: SHA256SUMS absent." >&2
    exit 1
fi

MODEL_ARTIFACT_DIR="$artifact_dir" CANONICAL_MODEL="$canonical_model" python3 - <<'PY'
import json
import os
from pathlib import Path

artifact = Path(os.environ["MODEL_ARTIFACT_DIR"])
manifest = json.loads((artifact / "manifest.json").read_text(encoding="utf-8"))
if manifest.get("model_id") != os.environ["CANONICAL_MODEL"]:
    raise SystemExit("ERROR: model_id reranker non canonique.")
PY

(
    cd "$artifact_dir"
    sha256sum --check --quiet SHA256SUMS
)

if [[ "${SKIP_LOAD_TEST:-0}" != "1" ]]; then
    MODEL_ARTIFACT_DIR="$artifact_dir" \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    python3 - <<'PY'
import os
from sentence_transformers import CrossEncoder

CrossEncoder(
    os.environ["MODEL_ARTIFACT_DIR"],
    max_length=512,
    local_files_only=True,
)
PY
fi

printf '%s\n' "RERANKER_ARTIFACT_VERIFIED=PASS"
