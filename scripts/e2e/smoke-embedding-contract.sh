#!/usr/bin/env bash
set -euo pipefail

# Read-only preflight for the v2 embedding contract.  Run from the v2 compose
# directory after the exact 1024d model has been pre-provisioned in the API
# image.  It neither creates data nor calls a write endpoint.

api_container="${RAG_API_CONTAINER:-rag_ingestor}"

docker exec "$api_container" python3 - <<'PY'
import os

try:
    from embedding_contract import (
        CANONICAL_EMBED_DIM,
        CANONICAL_EMBED_MODEL,
        declared_embedding_dim,
        declared_embedding_model,
        load_embedding_model,
        pgvector_dimension,
        runtime_embedding_dimension,
        validate_embedding_contract,
    )
except ModuleNotFoundError as error:
    if error.name != "embedding_contract":
        raise
    from src.ingestor.embedding_contract import (
        CANONICAL_EMBED_DIM,
        CANONICAL_EMBED_MODEL,
        declared_embedding_dim,
        declared_embedding_model,
        load_embedding_model,
        pgvector_dimension,
        runtime_embedding_dimension,
        validate_embedding_contract,
    )

model = declared_embedding_model()
declared_dim = declared_embedding_dim()
dsn = os.environ.get("PG_RAG_DSN") or os.environ.get("DATABASE_URL_SYNC")
if not dsn:
    raise SystemExit("PGVECTOR_DSN_UNAVAILABLE")

embed_model = load_embedding_model()
runtime_dim = runtime_embedding_dimension(embed_model)
pg_dim = pgvector_dimension(dsn)
validate_embedding_contract(
    model=model,
    declared_dim=declared_dim,
    runtime_dim=runtime_dim,
    pgvector_dim=pg_dim,
)

print(f"embedding_model={model}")
print(f"embedding_dim_declared={declared_dim}")
print(f"embedding_dim_runtime={runtime_dim}")
print(f"pgvector_dim={pg_dim}")
assert model == CANONICAL_EMBED_MODEL
assert declared_dim == CANONICAL_EMBED_DIM
print("EMBEDDING_CONTRACT_OK")
PY
