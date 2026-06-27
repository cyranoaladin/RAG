# ADR-0010 — Gouvernance cross-service

- **Statut** : Accepté
- **Date** : 2026-06-27
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0001 (séparation plan de contrôle / plan de données)

## Contexte

rag-pedago (plan de contrôle) produit les embeddings et le manifeste de revue. rag-engine (plan de données) indexe dans pgvector et sert le retrieval. L'indexation doit être gouvernée par les verrous de rag-pedago sans dupliquer la baseline.

## Décision

- **Source de vérité unique** : les verrous de gouvernance résident dans `services/rag-pedago/configs/pedago_interface_contract.yml`. Il n'y a PAS de 2e baseline dans rag-engine.
- **Lecture cross-service** : rag-engine lit le contrat de rag-pedago via un chemin résolu depuis la racine du workspace (`WORKSPACE_ROOT / "services/rag-pedago/configs/..."`).
- **Gating réel** : `check_ingestion_allowed()` dans rag-engine lit ce contrat et refuse si false (exit 1).
- **Manifeste de revue** : produit par rag-pedago (`build_review_manifest.py`), consommé par rag-engine (`index_pgvector.py`). Le manifeste est la preuve que la qualité a été vérifiée avant indexation.
- **`embedding_utils`** (format_passage/format_query) : source unique dans `packages/contracts` (nexus_contracts.embedding_utils), importé par les deux services.

## Conséquences

- Un seul endroit à modifier pour les verrous (rag-pedago).
- rag-engine ne peut pas indexer sans que rag-pedago ait approuvé (manifeste + verrou).
- Le garde-fou `check-governance-locks.sh` reste l'autorité unique (baseline = 18 clés).
