# AGENTS.md — rag-engine

Moteur RAG local (ex `rag-local`) : ingestion, embeddings, retrieval hybride.

## Stockage vectoriel

- **Runtime v2 canonique** : PostgreSQL + pgvector (HNSW + GIN), strictement **lecture/revue**, lancé par `api_v2:app` dans `docker-compose.v2.yml`.
- **Historique isolé** : les stacks et modules legacy restent auditables, mais ne sont ni copiés dans l'image v2 ni exposés par son proxy.
- **Bascule effective** : planifiée au Lot 1.2.

## Spécificités

- **Embeddings v2** : artefact local `intfloat/multilingual-e5-large`, 1024 dimensions, sans téléchargement ni fallback runtime.
- **Autorité HTTP** : les opérations humaines passent uniquement par le Cockpit BFF et une identité interne signée ; aucun token humain direct n'ouvre le moteur v2.
- **Writer** : absent du runtime v2 jusqu'aux autorités LOT41A/LOT42 prouvant `quality → gate → review`.
- **Tests** : `make test` (unitaires), `make test-integration` (nécessite Docker Compose).
- **Qualité** : `make lint`, `make typecheck`, `make smoke`.

## Interdictions

- Ne pas exposer l'API directement sans reverse proxy en production.
- Ne pas modifier le schéma pgvector (`infra/postgres/init.sql`) sans migration.
