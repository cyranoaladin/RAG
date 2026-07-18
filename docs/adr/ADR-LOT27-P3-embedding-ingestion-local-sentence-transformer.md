# ADR: Migrate ingestion embedding from Ollama to local SentenceTransformer

## Status

Proposed

## Context

The RAG v2 pipeline has two embedding paths:

1. **Search** (`retrieval_v2_endpoint.py`): uses `embedding_contract.load_embedding_model()` to load `intfloat/multilingual-e5-large` locally via SentenceTransformer, applies `format_query()` prefix, encodes with `normalize_embeddings=True`, and queries `pgvector(1024)`.

2. **Ingestion** (`tasks.py` → `EmbeddingService`): uses `EmbeddingService` which calls Ollama `/api/embeddings` over HTTP, does NOT apply `format_passage()` prefix, and writes to `pgvector(1024)`.

This architecture has critical inconsistencies:

- **Model divergence**: search uses the local SentenceTransformer artifact; ingestion uses whatever Ollama serves under `intfloat/multilingual-e5-large`. These may produce different vectors for the same text.
- **Missing E5 prefix**: the E5 model family requires `"passage: "` prefix for indexed documents and `"query: "` prefix for search queries. Search applies `format_query()` but ingestion does NOT apply `format_passage()`. This breaks the E5 asymmetric retrieval contract.
- **Network dependency**: ingestion depends on Ollama being available and having the exact model pulled. The local SentenceTransformer artifact is already mounted read-only but unused by ingestion.
- **Cache key mismatch**: `EmbeddingService._cache_key` uses `embed:{model}:{sha256}` but does not include dimension, prefix, or normalization state.

## Current state (LOT 27 P3)

- Artefact `intfloat/multilingual-e5-large` (revision `3d7cfbdacd47fdda877c5cd8a79fbcc4f2a574f3`) generated and verified offline.
- Mounted read-only at `/models/e5-large` in ingestor/worker containers.
- `embedding_contract.py` enforces model=`intfloat/multilingual-e5-large`, dim=1024, fail-closed.
- `load_embedding_model()` loads from the artifact. `MODEL_LOAD_OK 1024` verified in container.
- `packages/contracts/embedding_utils.py` provides `format_passage()` and `format_query()`.
- pgvector schema: `vector(1024)`.
- All governance locks remain false. Ingestion is not activated.

## Decision

Migrate `EmbeddingService` so that ingestion v2 uses the same local SentenceTransformer model loaded by `embedding_contract.load_embedding_model()`, with `format_passage()` applied to every chunk before encoding.

### Concrete changes (LOT 27 P3 AD scope)

1. **`EmbeddingService.embed_one()`**: replace Ollama HTTP call with `embed_model.encode(format_passage(text), normalize_embeddings=True)` using the model from `load_embedding_model()`.
2. **`EmbeddingService.__init__()`**: accept an optional pre-loaded SentenceTransformer model instead of `ollama_url`.
3. **`EmbeddingService._assert_model_available()`**: verify model dimension = 1024 instead of checking Ollama tags.
4. **`tasks.py`**: pass the already-loaded `contract_model` to `EmbeddingService`.
5. **Cache key**: include dimension and `"passage"` prefix marker in cache key.
6. **Remove Ollama dependency**: `EmbeddingService` no longer calls `/api/embeddings`.

### Non-objectives

- No pgvector schema migration.
- No reingestion.
- No deployment.
- No Ollama removal from Compose (it may be used by other paths).
- No changes to search path (already correct).

## Security constraints

- No model download at runtime (`local_files_only=True`).
- No fallback to 768d or any other model.
- No padding or truncation.
- Dimension validated against pgvector before any write.
- Cache keys must be model+dim+prefix-aware to prevent cross-contamination.

## Target architecture

```
Ingestion:
  text → format_passage(text) → SentenceTransformer.encode(local, normalize=True)
       → validate dim=1024 → pgvector INSERT

Search:
  query → format_query(query) → SentenceTransformer.encode(local, normalize=True)
        → validate dim=1024 → pgvector SELECT (cosine similarity)
```

Both paths use the same model, same normalization, complementary E5 prefixes.

## Acceptance tests

1. `EmbeddingService.embed_one()` returns 1024d vector without Ollama.
2. `EmbeddingService.embed_one()` applies `format_passage()` prefix.
3. `EmbeddingService` refuses to start if model dimension != 1024.
4. Cache key includes `"passage"` marker.
5. `tasks.py` no longer imports or connects to Ollama for embeddings.
6. Full ingestion pipeline test (offline, no Ollama) produces 1024d vectors.
7. Search and ingestion embeddings are in the same vector space (cosine similarity test with known text).

## Rollback

- Revert to Ollama-based `EmbeddingService` by reverting the PR.
- No data migration needed (pgvector schema unchanged).
- Ingestion governance locks remain the final gate.

## Risks

| Risk | Mitigation |
|---|---|
| SentenceTransformer memory usage in worker | Model already loaded for contract validation; reuse the instance |
| Cache invalidation after prefix change | New cache key format prevents stale hits |
| E5 prefix applied twice | Test that `format_passage` is applied exactly once |
| Ollama still referenced in other v1 paths | Out of scope; v1 paths are separate |

## Blockers remaining after this ADR

| ID | Level | Description |
|---|---|---|
| B1 | P2 | Governance locks must be activated via `transition_authorization.yml` + ADR before any real ingestion |
| B2 | P3 | `search_api.py` (v1) still uses `nomic-ai/nomic-embed-text-v1.5` — separate migration |
