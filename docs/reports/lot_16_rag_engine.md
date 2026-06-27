# Rapport — Lot 16 : Migration retrieval vers rag-engine

## Objectif

Résoudre DETTE-14-RAGENGINE : l'indexation pgvector et le retrieval résidaient dans rag-pedago (plan de contrôle) alors qu'ils relèvent du plan de données (rag-engine, ADR-0001).

## Déplacements

| Fichier | Avant | Après |
|---|---|---|
| `index_pgvector.py` | `services/rag-pedago/scripts/` | `services/rag-engine/scripts/` |
| `test_index_pgvector.py` | `services/rag-pedago/tests/unit/` | `services/rag-engine/tests/` |
| `docker-compose.pgvector.yml` | `services/rag-pedago/infra/` | `services/rag-engine/infra/` |
| `embedding_utils.py` | `services/rag-pedago/scrapers/` | `packages/contracts/src/nexus_contracts/` (source unique) |

`services/rag-pedago/scrapers/embedding_utils.py` conservé comme re-export (`from nexus_contracts.embedding_utils import ...`).

## Gouvernance cross-service (ADR-0010)

- rag-engine lit le contrat de gouvernance de rag-pedago via `WORKSPACE_ROOT` (pas de 2e baseline).
- Résolution de chemin : `Path(__file__).resolve().parents[3]` → racine repo → `services/rag-pedago/configs/pedago_interface_contract.yml`.
- `check_ingestion_allowed()` refuse si le verrou est faux (exit 1).
- Le manifeste de revue (`review_manifest.json`) produit par rag-pedago est consommé par rag-engine.
- `format_passage()`/`format_query()` partagés via `nexus_contracts.embedding_utils` (source unique, re-export dans rag-pedago).

### Preuve par mutation cross-service

```
=== ingestion_allowed=true (contrat rag-pedago) ===
check_ingestion_allowed() = True
→ Indexeur démarre, 124 chunks indexés

=== ingestion_allowed FLIPPÉ à false (contrat rag-pedago réel modifié) ===
check_ingestion_allowed() = False
$ python3 services/rag-engine/scripts/index_pgvector.py
BLOCKED: ingestion_allowed is false
EXIT CODE: 1

=== Contrat restauré ===
check_ingestion_allowed() = True
```

Le gate lit RÉELLEMENT le contrat de rag-pedago depuis rag-engine. Le chemin est vérifié :
```
Script:   .../services/rag-engine/scripts/index_pgvector.py
WS root:  .../Bureau/RAG
Contract: .../services/rag-pedago/configs/pedago_interface_contract.yml
Exists:   True
```

## Exécution réelle — iso-fonctionnalité prouvée

Retrieval depuis `services/rag-engine/scripts/index_pgvector.py`, scores **identiques** au Lot 14 :

| Requête | Score Lot 16 | Score Lot 14 | Delta |
|---|---|---|---|
| dérivée d'une fonction | 0.875 | 0.875 | 0 |
| la justice dans la philosophie | 0.872 | 0.872 | 0 |
| pile et file informatique | 0.844 | 0.844 | 0 |
| suites numériques | 0.835 | 0.835 | 0 |

### Coexistence (filtres)

```
=== COEXISTENCE: niveau filter ===
terminale results: 3 — niveaux: ['terminale', 'terminale', 'terminale']
premiere results:  1 — niveaux: ['premiere']
PASS: niveau filter isolates correctly

audience=libre results: 0
audience=aefe results:  1
```

### Idempotence

```
1er run:  Indexed: 124, rejected: 0, not_in_manifest: 0 → DB count: 126
2e  run:  Indexed: 124, rejected: 0, not_in_manifest: 0 → DB count: 126
Idempotent: True
```

### Rejet manifeste

```
Manifest: 124 approved chunks

REJECTION: chunk not in manifest
is_admitted("fake_chunk#99", "fake_sha") = (False, "not_in_manifest")

REJECTION: sha mismatch
is_admitted("terminale_grand_oral_expression_orale#0", "wrong_sha") = (False, "sha_mismatch")

ADMISSION: correct
is_admitted("terminale_grand_oral_expression_orale#0", correct_sha) = (True, "ok")
```

## embedding_utils — source unique validée

```
rag-pedago import (via re-export scrapers/embedding_utils.py):
  format_passage("test") = "passage: test"
  Source: packages/contracts/src/nexus_contracts/embedding_utils.py

rag-engine import (direct nexus_contracts):
  format_passage("test") = "passage: test"
  Source: packages/contracts/src/nexus_contracts/embedding_utils.py
```

Même fichier source des deux côtés.

## Flags sensibles — accès strict (pas de .get())

`curated_ingestion_allowed: false` ajouté explicitement dans `source_admission_policy.yml` (racine) pour cohérence avec les autres flags sensibles. Déjà présent dans `transition_authorization.yml`.

Le test `test_governance_policy_scope_consistency.py` utilise l'accès **strict** `admission[flag]` / `transition[flag]` (pas `.get()`). Un flag sensible absent fait échouer le test (KeyError).

Les 5 flags sensibles sont vérifiés :

```
real_documents_allowed:    pedago=False, admission=False, transition=False
qdrant_allowed:            pedago=False, admission=False, transition=False
server_start_allowed:      pedago=False, admission=False, transition=False
runtime_api_allowed:       pedago=False, admission=False, transition=False
curated_ingestion_allowed: pedago=False, admission=False, transition=False
```

## Tests (10 tests unitaires)

- 5 tests gating (verrou true/false/empty/malformed/missing)
- 3 tests `is_admitted()` (mutation-proof : sha invalide, id absent, sha correct)
- 2 tests manifeste (chargement correct, fichier absent → dict vide)

**Note** : `tests/integration/test_pgvector.py` couvre `ingestor.database.RagDatabase` (système historique rag-engine), PAS le `index_pgvector.py` déplacé. Iso-fonctionnalité prouvée par exécution manuelle (cf. supra). Tracé au BACKLOG : `DETTE-16-ITEST-RETRIEVAL`.

## CI locale : 7/7 PASS

```
PASS  packages/contracts
PASS  services/rag-pedago
PASS  services/rag-engine
PASS  governance-locks
PASS  taxonomy-validation
PASS  governance-guard-tests
PASS  ci-failsafe-tests

Total: 7 passed, 0 failed
```

Baseline : 18 clés.

## BACKLOG

- `DETTE-14-RAGENGINE` : **Résolu** (ce lot)
- `DETTE-16-ITEST-RETRIEVAL` : Pas de test d'intégration automatisé pour `index_pgvector.py` déplacé. À ajouter.
