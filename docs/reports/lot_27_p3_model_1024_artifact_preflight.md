# LOT 27 P3 — Model 1024d Artifact Preflight

## Contexte

Le pipeline RAG v2 requiert le modele `intfloat/multilingual-e5-large` (1024d).
Ce modele est absent des images/runtime actuels. Le contrat d'embedding (`embedding_contract.py`)
est deja fail-closed : `local_files_only=True`, aucun fallback, aucun padding.

Le blocage : aucun mecanisme ne pre-provisionne ce modele de maniere verifiable
et reproductible avant le deploiement.

## Decision d'architecture

**Artefact modele externe**, non commite dans Git :

1. Un repertoire modele pre-rempli par `scripts/e2e/prepare-embedding-model-artifact.sh`
2. Un manifeste JSON (`manifest.json`) avec metadata verifiables
3. Des checksums SHA256 (`SHA256SUMS`) pour chaque fichier
4. Montage read-only dans les conteneurs ingestor/worker

Le runtime ne telecharge jamais le modele. Si le cache est absent, le service refuse de demarrer (fail-closed).

## Semantique hote / conteneur

Deux variables distinctes evitent toute confusion :

| Variable | Scope | Valeur |
|---|---|---|
| `RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR` | `.env` hote | Chemin absolu vers l'artefact sur la machine hote |
| `RAG_EMBEDDING_MODEL_CACHE_DIR` | Conteneur | `/models/e5-large` (fixe, jamais un chemin hote) |

Le volume Compose mappe l'un vers l'autre :
```yaml
volumes:
  - ${RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR:-./data/.no-model-cache}:/models/e5-large:ro
environment:
  RAG_EMBEDDING_MODEL_CACHE_DIR: "/models/e5-large"
```

## Comportement de `load_embedding_model()`

1. Si `RAG_EMBEDDING_MODEL_CACHE_DIR` est defini :
   - Verifie que le repertoire existe
   - Charge `SentenceTransformer(cache_dir, local_files_only=True)`
   - Echoue avec `EMBEDDING_MODEL_ARTIFACT_PATH_MISSING` si absent
2. Sinon :
   - Charge `SentenceTransformer("intfloat/multilingual-e5-large", local_files_only=True)`
   - Echoue avec `EMBEDDING_MODEL_UNAVAILABLE` si pas en cache local

Dans les deux cas : aucun telechargement, aucun fallback.

## Statut de `EmbeddingService` (Ollama) — BLOCKER CONTROLE

**`EMBEDDING_SERVICE_OLLAMA_PATH_STILL_ACTIVE`**

Le worker d'ingestion (`tasks.py`) utilise encore `EmbeddingService` qui appelle
Ollama (`/api/embeddings`) pour produire les vecteurs ecrits en pgvector.
`load_embedding_model()` n'est utilise que pour la validation contractuelle
(verification de dimension), pas pour l'embedding reel.

Consequence : le montage de l'artefact local SentenceTransformer ne suffit PAS
a rendre l'ingestion v2 fonctionnelle. L'ingestion reste dependante d'Ollama.

Ce blocage est :
- Documente ici et dans les tests de contrat
- Expose par des tests explicites (`TestOllamaEmbeddingPathBlocker`)
- A traiter dans un lot ulterieur (migration embedding ingestion vers SentenceTransformer local)

## Procedure de generation locale

```bash
export MODEL_ARTIFACT_DIR=/path/to/artifact/e5-large-1024   # absolu, hors repo
export EMBEDDING_MODEL_REVISION=main  # ou commit hash specifique
bash scripts/e2e/prepare-embedding-model-artifact.sh
```

Prerequis :
- Python 3.11+ avec `huggingface_hub` et `sentence_transformers`
- Acces internet (uniquement pendant la preparation)
- Le repertoire cible doit etre un chemin absolu HORS du depot Git

## Procedure de verification offline

```bash
export MODEL_ARTIFACT_DIR=/path/to/artifact/e5-large-1024
bash scripts/e2e/verify-embedding-model-artifact.sh
```

## Manifeste attendu

```json
{
  "model_id": "intfloat/multilingual-e5-large",
  "canonical_dim": 1024,
  "revision_requested": "<commit_or_tag>",
  "file_count": "<n>",
  "total_size_bytes": "<n>",
  "generated_at": "<ISO8601>",
  "repo_commit": "<git_sha>",
  "python_version": "<version>",
  "huggingface_hub_version": "<version>",
  "sentence_transformers_version": "<version>"
}
```

## Criteres d'acceptation avant deploiement

- [ ] Artefact genere localement avec `prepare-embedding-model-artifact.sh`
- [ ] Verification passee avec `verify-embedding-model-artifact.sh`
- [ ] Checksums SHA256 tous valides
- [ ] Dimension confirmee a 1024
- [ ] Aucune reference Nomic dans l'artefact
- [ ] `RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR` pointe vers l'artefact verifie
- [ ] Volume monte read-only dans Compose
- [ ] Smoke embedding contract passe dans la stack locale
- [ ] **BLOCKER** : migration embedding ingestion hors Ollama (lot ulterieur)

## Criteres de rollback

- Retirer `RAG_EMBEDDING_MODEL_ARTIFACT_HOST_DIR` du `.env` suffit a bloquer
- Le runtime reste fail-closed
- Les donnees pgvector ne sont pas touchees par ce lot

## Interdictions

- Aucun telechargement de modele au runtime
- Aucun fallback vers `nomic-embed-text:v1.5` (768d)
- Aucun padding/truncation de vecteurs
- Aucun commit du modele dans Git
- Aucun deploiement dans ce lot

## Prochaine etape

1. Generer reellement l'artefact hors production
2. Tester la stack locale complete avec le modele monte en read-only
3. Migrer le chemin d'embedding ingestion de Ollama vers SentenceTransformer local
