from __future__ import annotations

import os
from pathlib import Path

_DEFAULT_WORKSPACE_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = Path(os.environ.get("NEXUS_WORKSPACE_ROOT", str(_DEFAULT_WORKSPACE_ROOT)))
REPO_ROOT = WORKSPACE_ROOT / "services" / "rag-pedago"
RAG_LOCAL_ROOT = WORKSPACE_ROOT / "services" / "rag-engine"
PRODUCTION_RAG_UI_ROOT = Path(os.environ.get("NEXUS_RAG_UI_ROOT", "/srv/nexusreussite/rag-ui"))
