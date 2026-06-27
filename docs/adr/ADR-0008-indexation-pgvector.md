# ADR-0008 — Indexation pgvector gouvernée

- **Statut** : Accepté
- **Date** : 2026-06-26
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0007 (embeddings), ADR-0003 (tenants par niveau)

## Contexte

124 embeddings (1024d, multilingual-e5-large, préfixe passage:) sont prêts. L'indexation pgvector est la dernière étape avant le retrieval fonctionnel.

## Décision

- `ingestion_allowed: true` — scope STRICT : indexation pgvector des embeddings pilotes, retrieval local uniquement.
- N'autorise PAS l'exposition API publique (`server_start_allowed` et `runtime_api_allowed` restent false).
- `qdrant_allowed` : obsolète (ADR-0001 = pgvector). Reste false, ne pas réutiliser.
- Le script d'indexation vérifie le verrou avant d'agir (gating réel).

### Schéma pgvector

- Table `rag_chunks` : `chunk_id` (PK), `doc_id`, `vector vector(1024)`, `niveau`, `voie`, `audience`, `matiere`, `notions`.
- Index HNSW sur le vecteur pour la recherche ANN.
- Upsert idempotent par `chunk_id` (ON CONFLICT → update).

### Retrieval

- Les requêtes utilisent `format_query()` (préfixe `query:`).
- Le filtrage SQL par `niveau`/`audience` est OBLIGATOIRE (un élève ne reçoit jamais un chunk d'un autre niveau/audience).

## Conséquences

- Premier retrieval fonctionnel de bout en bout.
- La dimension 1024 est fixée dans le schéma (ne plus changer).
