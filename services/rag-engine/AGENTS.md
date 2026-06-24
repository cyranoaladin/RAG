# AGENTS.md — rag-engine

Moteur RAG local (ex `rag-local`) : ingestion, embeddings, retrieval hybride.

## Stockage vectoriel

- **Cible** : PostgreSQL + pgvector (HNSW + GIN). Schéma dans `infra/postgres/init.sql`, stack dans `docker-compose.v2.yml`.
- **Défaut courant** : ChromaDB (`docker-compose.yml` / `docker-compose.prod.yml`).
- **Bascule effective** : planifiée au Lot 1.2.

## Spécificités

- **Embeddings** : Ollama (`nomic-embed-text`), 768 dimensions.
- **Tests** : `make test` (unitaires), `make test-integration` (nécessite Docker Compose).
- **Qualité** : `make lint`, `make typecheck`, `make smoke`.

## Interdictions

- Ne pas exposer l'API directement sans reverse proxy en production.
- Ne pas modifier le schéma pgvector (`infra/postgres/init.sql`) sans migration.
