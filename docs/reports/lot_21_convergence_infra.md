# Rapport de lot 21 — Convergence : infrastructure et contrat

**Branche** : `lot-21-convergence-infra`
**Date** : 30 juin 2026
**Périmètre** : dépôt/infra uniquement, aucune action prod.

---

## Livrables

| # | Item | Fichier | Preuve |
|---|---|---|---|
| 1 | ADR définitif | `docs/adr/ADR-0013-convergence-dual-engine.md` | Statut « accepté », intègre D-M03 (cockpit différé), D-PERIMETRE (NSI d'abord) |
| 2 | `rag_collections.yml` v2 | `services/rag-engine/configs/rag_collections.yml` | 22 collections, 3 `instanciee: true` (2 NSI + quarantaine), 0 Chroma résiduel |
| 3 | Invariant anti-auto-création | `src/ingestor/collection_config.py` (fonctions v2) + `tests/test_collection_config_v2.py` | 8 tests passent : unknown → `CollectionUnknownError`, non instanciée → `CollectionNotInstanciatedError` |
| 4 | Table `rag_chunks` | `services/rag-engine/scripts/schema_rag_chunks.sql` | DDL citations-ready : `rights`, `source_uri`, `source_label`, `type_doc`, `doc_id` ≠ `chunk_id`, 7 index (HNSW + 6 B-tree/GIN) |
| 5 | Compose pgvector dédié | `services/rag-engine/infra/docker-compose.pgvector-rag.yml` | Démarrage vérifié, extension vector 0.8.1, table `rag_chunks` + index créés à l'init |
| 6 | Backlog tracé | Ce rapport | O-03 (taxonomie options), J-06 (niveau français) |

---

## Détails

### 1. ADR-0013

Numéroté (suite de ADR-0012). Intègre toutes les décisions de lead (A-1→A-8, D-M03, D-PERIMETRE, A-7 amendé). L'ancien draft `ADR_CONVERGENCE_DRAFT.md` reste dans `docs/audits/` comme historique.

### 2. `rag_collections.yml` v2

- Format v2 : `physical_backend` (pgvector, table `rag_chunks`, DSN via `PG_RAG_DSN`), plus de section `chroma`.
- 22 collections au catalogue, convention `rag_nexus_{matiere}_{niveau}_{statut}` + 5 exceptions nommées.
- Flag `instanciee` par collection. Instanciées : `rag_nexus_nsi_premiere_specialite`, `rag_nexus_nsi_terminale_specialite`, `rag_nexus_quarantine`.

### 3. Invariant anti-auto-création (M-04)

Nouvelles fonctions dans `collection_config.py` :
- `resolve_collection_v2(name, config)` : lève `CollectionUnknownError` ou `CollectionNotInstanciatedError`.
- `list_instanciated_collections(config)` : retourne les noms des collections instanciées.

Tests (`test_collection_config_v2.py`, 8 tests) :
```
tests/test_collection_config_v2.py ........    [100%]
```

### 4. Table `rag_chunks`

Mapping champ → contrat :

| Colonne | Contrat (`nexus-contracts`) | Rôle F-01 |
|---|---|---|
| `chunk_id` (PK) | `ChunkMetadata` | Identifiant unique du chunk |
| `doc_id` | `ChunkMetadata.doc_id` | Identifiant du document source (distinct de `chunk_id`) |
| `source_label` | `Citation.source_label` | Label humain |
| `source_uri` | `Citation.source_uri` | URI de la source |
| `rights` | `Citation.rights` | Droits (par provenance, A-4) |
| `type_doc` | `ChunkMetadata.type_doc` | Type de document |
| `official` | `ChunkMetadata.official` | Source officielle ? |
| `chunk_sha256` | intégrité/dédup | Hash du chunk |
| `collection` | routage | Collection cible `rag_nexus_*` |

### 5. Compose pgvector dédié

- Image : `pgvector/pgvector:pg15`
- Port : `127.0.0.1:5436` (par défaut, configurable via `PG_RAG_PORT`)
- Base : `nexus_rag` (séparée de `nexus_prod`, A-1)
- Init : `schema_rag_chunks.sql` monté en `docker-entrypoint-initdb.d/`
- Vérifié : démarrage OK, extension vector 0.8.1, table + 7 index créés

### 6. Backlog tracé

- **O-03** : compléter la taxonomie (options hors maths, maths complémentaires/expertes, enseignement scientifique, EMC)
- **J-06** : résoudre le niveau réel de `rag_francais_premiere` avant toute instanciation française
- **I-04** : benchmark débit e5-large CPU (LOT 25)

---

## Tests

```
8 passed in 0.10s (test_collection_config_v2.py)
```

Tests préexistants du rag-engine : 10 erreurs d'import (dépendances manquantes : `chromadb`, `langchain`, etc.) — **préexistantes**, pas de régression introduite par ce lot.

---

## Point d'étape

**LOT 21 prêt pour commit/PR.** Infrastructure posée : ADR accepté, catalogue de 22 collections avec flags d'instanciation, invariant anti-auto-création testé, table `rag_chunks` citations-ready, pgvector dédié provisionné. Aucune collection remplie — le LOT suivant exécute la chaîne taxonomie→index sur NSI Terminale.
