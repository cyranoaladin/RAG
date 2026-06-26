# ADR-0007 — Calcul d'embeddings gouverné

- **Statut** : Accepté
- **Date** : 2026-06-26
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0006 (chunking gouverné)

## Contexte

124 chunks conformes ChunkMeta sont disponibles. Le calcul d'embeddings est la dernière étape avant l'indexation pgvector.

## Décision

- `embeddings_allowed: true` — scope : calcul des vecteurs d'embedding sur chunks conformes, écriture en artefacts locaux.
- N'autorise PAS l'indexation pgvector (`qdrant_allowed` et `ingestion_allowed` restent false).
- Le script vérifie le verrou avant d'agir (gating réel).

### Modèle

- **Pilote** : `all-MiniLM-L6-v2` (384 dims, sentence-transformers, ~80MB).
- **Production** : BGE-M3 (1024 dims, multilingue) — à basculer au lot de mise à l'échelle.
- Téléchargement modèle via HuggingFace (réseau déjà autorisé sous ADR-0004).
- Modèle figé par nom + révision ; vecteurs normalisés L2.

### Idempotence

- Clé = `chunk_id` + `chunk_sha256`. Si le sha n'a pas changé, le vecteur n'est pas recalculé.

### Métadonnées

- Chaque entrée d'embedding porte niveau/voie/audience/matiere/notions (pour le filtrage retrieval pgvector au Lot 14).

## Conséquences

- Les embeddings sont des artefacts versionnables, révisables avant indexation.
- Le changement de modèle nécessite un recalcul complet (sha change → idempotence force le recalcul).
