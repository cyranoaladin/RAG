#!/usr/bin/env bash
# Vérifier un artefact CrossEncoder préprovisionné, sans accès réseau.
set -euo pipefail

artifact_dir="${MODEL_ARTIFACT_DIR:-}"
repository_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ -z "$artifact_dir" || ! -d "$artifact_dir" ]]; then
    printf '%s\n' "ERROR: MODEL_ARTIFACT_DIR doit désigner un répertoire." >&2
    exit 1
fi
MODEL_ARTIFACT_DIR="$artifact_dir" \
PYTHONPATH="$repository_root/services/rag-engine/src${PYTHONPATH:+:$PYTHONPATH}" \
HF_HUB_OFFLINE=1 \
TRANSFORMERS_OFFLINE=1 \
python3 - <<'PY'
import os
from pathlib import Path

from ingestor.reranker_contract import (
    load_reranker_model,
    verify_reranker_artifact,
)

artifact = verify_reranker_artifact(Path(os.environ["MODEL_ARTIFACT_DIR"]))
if os.environ.get("SKIP_LOAD_TEST", "0") != "1":
    os.environ["RAG_RERANKER_MODEL_CACHE_DIR"] = str(artifact)
    # load_reranker_model impose également local_files_only=True.
    load_reranker_model()
PY


printf '%s\n' "RERANKER_ARTIFACT_VERIFIED=PASS"
