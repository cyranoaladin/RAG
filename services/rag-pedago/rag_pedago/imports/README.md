# rag_pedago/imports/

Rôle : workflows metadata-only autour des manifests JSONL.

Peut contenir :

- import de manifests ;
- qualité ;
- readiness ;
- coverage ;
- gate ;
- review package et approval ;
- controlled import.

Interdit :

- ouvrir `source_uri` ;
- parser PDF ou documents ;
- réseau ;
- Qdrant, PostgreSQL, LLM runtime.

Tests :

- `python -m pytest tests/unit/test_manifest_*.py tests/unit/test_review*.py`
