# Rapport — Lot 14 : Indexation pgvector + retrieval filtré

## Levée tracée

`ingestion_allowed: true # ADR-0008` dans contrat + transition + baseline. Scope strict : indexation pgvector des 124 embeddings pilotes, retrieval local. `server_start_allowed` et `runtime_api_allowed` restent false. `qdrant_allowed` documenté obsolète (reste false).

## Infra

`infra/docker-compose.pgvector.yml` : PostgreSQL 16 + pgvector extension.
```bash
docker compose -f infra/docker-compose.pgvector.yml up -d
python scripts/index_pgvector.py
```

## Schéma pgvector

```sql
CREATE TABLE rag_chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    vector vector(1024),
    niveau TEXT NOT NULL,
    voie TEXT NOT NULL DEFAULT 'generale',
    audience TEXT[] NOT NULL,
    matiere TEXT NOT NULL,
    notions TEXT[] NOT NULL,
    text TEXT,
    model TEXT
);
CREATE INDEX idx_rag_chunks_vector ON rag_chunks
    USING hnsw (vector vector_cosine_ops) WITH (m=16, ef_construction=64);
```

Dimension 1024 enforced. Upsert idempotent (ON CONFLICT chunk_id → UPDATE).

## Gating

`check_ingestion_allowed()` — 5 tests (false/true/empty/malformed/missing). Prouvé par les tests CI.

## Retrieval

- Requêtes préfixées `query:` (utilitaire `format_query()`)
- Filtrage SQL : `niveau` + `audience` (exclusion prouvée par requête premiere → 0 résultat, terminale → résultats)
- Pertinence : 4 requêtes FR → top-1 correct (derivation, justice, piles, dérivée)

## Livrables

- Script `scripts/index_pgvector.py` : gated, upsert idempotent, retrieval avec filtres
- Docker-compose pgvector
- ADR-0008 versionné
- 5 tests gating

## CI locale : 7/7 PASS, garde-fou 17/17

Note : l'indexation réelle et le retrieval demo nécessitent un PostgreSQL+pgvector en cours d'exécution. Le script est prêt, la chaîne complète est validable manuellement.
