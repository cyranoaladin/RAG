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

### Modèle (DÉFINITIF)

- **Production** : `intfloat/multilingual-e5-large` (1024 dims, multilingue FR/EN/etc., ~1.3GB).
- **Dimension** : **1024** — définitive, conditionne le schéma pgvector (Lot 14). Ne plus changer.
- BGE-M3 écarté (poids ~2.3GB, overhead XPU sans gain mesurable vs e5-large sur le corpus FR).
- Téléchargement via HuggingFace — réseau autorisé sous ADR-0004 (scope « téléchargement modèle »).
- Vecteurs normalisés L2 (norme = 1.0).
- `MODEL_NAME` + `MODEL_DIM` figés dans `scripts/build_embeddings.py`.

### Préfixes e5 (OBLIGATOIRE)

Le modèle e5 exige des préfixes pour séparer l'espace requêtes/passages :
- **Embedding de chunks** : `passage: {texte}` (via `format_passage()`)
- **Requêtes au retrieval** : `query: {texte}` (via `format_query()`)
- Utilitaires centralisés dans `scrapers/embedding_utils.py`.
- Toute requête au retrieval (Lot 14+) DOIT utiliser `format_query()` sous peine de dégradation silencieuse.

### Idempotence

- Clé = `(chunk_sha256, MODEL_NAME, MODEL_DIM)`. Le vecteur n'est réutilisé que si les trois correspondent. Un changement de modèle/dimension force un recalcul complet.

### Métadonnées

- Chaque entrée d'embedding porte niveau/voie/audience/matiere/notions (pour le filtrage retrieval pgvector au Lot 14).

## Conséquences

- Les embeddings sont des artefacts versionnables, révisables avant indexation.
- Le changement de modèle nécessite un recalcul complet (sha change → idempotence force le recalcul).
