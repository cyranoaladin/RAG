# AGENTS.md — rag-engine

Moteur RAG local (ex `rag-local`) : ingestion, embeddings, retrieval hybride.

## Spécificités

- **Stockage vectoriel** : PostgreSQL + pgvector (HNSW + GIN). ChromaDB est déprécié.
- **Embeddings** : Ollama (`nomic-embed-text`), 768 dimensions.
- **Tests** : `make test` (unitaires), `make test-integration` (nécessite Docker Compose).
- **Qualité** : `make lint`, `make typecheck`, `make smoke`.

## Interdictions

- Ne pas reconnecter ChromaDB comme stockage principal.
- Ne pas exposer l'API directement sans reverse proxy en production.
- Ne pas modifier le schéma pgvector (`infra/postgres/init.sql`) sans migration.
