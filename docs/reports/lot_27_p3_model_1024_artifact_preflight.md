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
4. Montage read-only dans les conteneurs ingestor/worker via `RAG_EMBEDDING_MODEL_CACHE_DIR`

Le runtime ne telecharge jamais le modele. Si le cache est absent, le service refuse de demarrer (fail-closed).

## Procedure de generation locale

```bash
export MODEL_ARTIFACT_DIR=/path/to/artifact/e5-large-1024
export EMBEDDING_MODEL_REVISION=main  # ou commit hash specifique
bash scripts/e2e/prepare-embedding-model-artifact.sh
```

Prerequis :
- Python 3.11+ avec `huggingface_hub` et `sentence_transformers`
- Acces internet (uniquement pendant la preparation)
- Le repertoire cible doit etre HORS du depot Git

## Procedure de verification offline

```bash
export MODEL_ARTIFACT_DIR=/path/to/artifact/e5-large-1024
bash scripts/e2e/verify-embedding-model-artifact.sh
```

Verifications :
- `manifest.json` present et coherent (model_id, canonical_dim)
- `SHA256SUMS` present, tous les checksums valides
- Aucune reference Nomic dans l'artefact
- Chargement offline du modele (`local_files_only=True`, `HF_HUB_OFFLINE=1`)
- Dimension runtime == 1024

## Manifeste attendu

```json
{
  "model_id": "intfloat/multilingual-e5-large",
  "canonical_dim": 1024,
  "revision_requested": "<commit_or_tag>",
  "file_count": <n>,
  "total_size_bytes": <n>,
  "generated_at": "<ISO8601>",
  "repo_commit": "<git_sha>",
  "python_version": "<version>",
  "huggingface_hub_version": "<version>",
  "sentence_transformers_version": "<version>"
}
```

## Montage read-only dans Compose

Le fichier `docker-compose.v2.yml` supporte un volume conditionnel :

```yaml
environment:
  RAG_EMBEDDING_MODEL_CACHE_DIR: "${RAG_EMBEDDING_MODEL_CACHE_DIR:-}"
volumes:
  - ${RAG_EMBEDDING_MODEL_CACHE_DIR:-/dev/null}:/models/e5-large:ro
```

Le montage est un prerequis de deploiement, pas active implicitement.
Sans `RAG_EMBEDDING_MODEL_CACHE_DIR` defini, le service reste fail-closed.

## Criteres d'acceptation avant deploiement

- [ ] Artefact genere localement avec `prepare-embedding-model-artifact.sh`
- [ ] Verification passee avec `verify-embedding-model-artifact.sh`
- [ ] Checksums SHA256 tous valides
- [ ] Dimension confirmee a 1024
- [ ] Aucune reference Nomic dans l'artefact
- [ ] Volume monte read-only dans Compose
- [ ] Smoke embedding contract passe dans la stack locale

## Criteres de rollback

- Si le modele produit des embeddings incoherents : revenir au montage precedent (sans le volume)
- Le runtime reste fail-closed : retirer `RAG_EMBEDDING_MODEL_CACHE_DIR` suffit a bloquer
- Les donnees pgvector ne sont pas touchees par ce lot

## Interdictions

- Aucun telechargement de modele au runtime
- Aucun fallback vers `nomic-embed-text:v1.5` (768d)
- Aucun padding/truncation de vecteurs
- Aucun commit du modele dans Git

## Prochaine etape

Generer reellement l'artefact hors production, puis tester la stack locale complete
avec le modele monte en read-only.
