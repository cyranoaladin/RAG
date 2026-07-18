# LOT 27 P3 — Ingestion Embedding Path Audit

## Date

2026-07-18

## Main commit

6417277949674a0ad3bbc630dae923166842509a

## Files inspected

| File | Role |
|---|---|
| `services/rag-engine/src/ingestor/embedding_contract.py` | Fail-closed contract: model, dimension, pgvector validation |
| `services/rag-engine/src/ingestor/embedding_service.py` | Ollama HTTP client with Redis cache |
| `services/rag-engine/src/ingestor/tasks.py` | Celery worker: orchestrates ingestion pipeline |
| `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py` | Search v2: local SentenceTransformer + format_query |
| `services/rag-engine/src/ingestor/api.py` | API v1 endpoints (Ollama/LangChain path) |
| `services/rag-engine/src/ingestor/search_api.py` | Search v1 (Chroma, nomic-ai model) |
| `services/rag-engine/src/ingestor/database.py` | pgvector upsert/query operations |
| `packages/contracts/src/nexus_contracts/embedding_utils.py` | E5 prefix functions: format_query, format_passage |
| `services/rag-engine/infra/docker-compose.v2.yml` | Compose: Ollama service, model mount |

## Search v2 flow

| Step | Implementation | File | Line |
|---|---|---|---|
| Model load | `load_embedding_model()` → SentenceTransformer local | `retrieval_v2_endpoint.py` | 151 |
| Query format | `format_query(q)` → `"query: {text}"` | `retrieval_v2_endpoint.py` | 345 |
| Encode | `embed_model.encode(formatted, normalize_embeddings=True)` | `retrieval_v2_endpoint.py` | 345 |
| Dimension | 1024 (validated by contract) | `embedding_contract.py` | 60-65 |
| DB access | pgvector SELECT (cosine similarity) | `retrieval_v2_endpoint.py` | 350+ |
| Ollama dependency | **None** | — | — |
| Writes DB | **No** | — | — |

## Ingestion v2 flow

| Step | Implementation | File | Line |
|---|---|---|---|
| Contract validation | `load_embedding_model()` + `validate_runtime_embedding_contract()` | `tasks.py` | 89-90 |
| Embedding service | `EmbeddingService(ollama_url, model)` | `tasks.py` | 92-95 |
| Model availability | `_assert_model_available()` → Ollama `/api/tags` | `embedding_service.py` | 87-106 |
| Embed call | `embed_svc.embed_batch()` → Ollama `/api/embeddings` | `tasks.py` | 142 |
| Passage format | **NOT APPLIED** — raw text sent to Ollama | `embedding_service.py` | 146-147 |
| Dimension check | `len(embedding) != declared_embedding_dim()` | `embedding_service.py` | 160 |
| DB write | `db.insert_chunks()` → pgvector INSERT | `tasks.py` | 158 |
| Ollama dependency | **Required** (HTTP calls) | `embedding_service.py` | 145-154 |

## Worker flow

| Element | Status |
|---|---|
| Celery worker | Defined but not started in smoke tests |
| Ollama dependency | Required for `EmbeddingService.connect()` and `embed_one()` |
| Model mount | Used only for contract validation, not for actual embedding |
| Risk if Ollama absent | `_assert_model_available()` raises `EMBEDDING_MODEL_UNAVAILABLE` |

## Identified gaps

| ID | Level | Description | Proof |
|---|---|---|---|
| G1 | P0 | `format_passage()` not applied to chunks before embedding in ingestion path | `grep -n format_passage tasks.py embedding_service.py` returns empty |
| G2 | P1 | Ingestion uses Ollama HTTP while search uses local SentenceTransformer — potential vector space divergence | `tasks.py:92-95` creates `EmbeddingService(ollama_url=...)` |
| G3 | P1 | Local model artifact mounted but unused by ingestion | `tasks.py:89` loads model for validation only, `tasks.py:142` calls Ollama |
| G4 | P2 | Cache key `embed:{model}:{sha256}` does not include E5 prefix or normalization | `embedding_service.py:111` |
| G5 | P2 | `search_api.py` (v1) defaults to `nomic-ai/nomic-embed-text-v1.5` (768d) | `search_api.py:82` |
| G6 | P3 | `/health` shows `embedding_contract_ok=false` because runtime dim is not loaded at startup | `embedding_contract.py:183` intentionally defers loading |

## Decision

See ADR: `docs/adr/ADR-LOT27-P3-embedding-ingestion-local-sentence-transformer.md`

## Implementation plan (LOT 27 P3 AD — next lot)

1. Modify `EmbeddingService` to accept a pre-loaded SentenceTransformer model.
2. Replace Ollama HTTP calls with `model.encode(format_passage(text), normalize_embeddings=True)`.
3. Update cache key to include `"passage"` marker.
4. Update `tasks.py` to pass the contract model to `EmbeddingService`.
5. Add tests proving:
   - No Ollama dependency for embedding.
   - `format_passage()` applied exactly once.
   - Output dimension = 1024.
   - Vector space consistency between search and ingestion.
6. Governance locks remain the final gate before any real ingestion.

## Tests needed

| Test | Purpose |
|---|---|
| `EmbeddingService` embeds without Ollama | Proves local-only path |
| `format_passage` applied to every chunk | Proves E5 contract |
| Output dim = 1024 for all chunks | Proves pgvector compatibility |
| Same model instance for ingestion and search | Proves vector space consistency |
| Cache key includes prefix marker | Prevents cross-contamination |
| No Ollama import in embedding hot path | Proves decoupling |

## Interdictions

- Aucun deploiement.
- Aucune ingestion.
- Aucun deploiement en production.
- Aucune modification DB.
- Aucun telechargement de modele.
