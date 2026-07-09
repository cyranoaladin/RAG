# LOT 26.1 — Cadrage de convergence (ADR-0014)

**Date** : 2026-07-09
**Issue pilotage** : #47
**Branche** : `codex/lot26-1-adr-convergence`
**Statut** : prêt à revue (lot cadrage)

---

## Objectif du lot

Formaliser l’architecture de convergence autour du dépôt canonique et produire le cadrage documenté pour les lots LOT 26.2 → LOT 26.10.

Référence de cadrage : `docs/reports/lot_26_cahier_charges_fusion_rag.md`, introduit par la PR #48. Cette PR #49 dépend de #48 si #48 n’est pas encore mergée.

## Travaux réalisés

### 1) Documentation et ADR

- Création de l’ADR : `docs/adr/ADR-0014-fusion-rag-local-rag-anything.md`
- Confirmation des décisions de convergence :
  - dépôt canonique = `cyranoaladin/RAG` (seul).
  - `rag-local` = legacy lisible/intégré en source (pas de fusion à plat).
  - `RAG-Anything` = adaptateur multimodal optionnel.
  - coexistence legacy/v2 planifiée via shadow puis canary.
  - `rag_nexus_*` + `instanciee` pour le pilotage v2 ; pas d’auto-création.
  - la nomenclature `{population}_{niveau}` n’est pas une règle opérationnelle v2 ; la base de vérité est `collection / niveau / audience / matière / statut`.

### Corrections effectuées (suite à revue)

- Référence de cadrage corrigée dans l’ADR pour indiquer explicitement la dépendance à la PR #48 (fichier référencé non encore dans `main`).
- D6 corrigée :
  - suppression de la règle `{population}_{niveau}` comme règle opérationnelle v2 ;
  - base de vérité v2 alignée sur `services/rag-engine/configs/rag_collections.yml` et `packages/contracts` ;
  - ajout de la contrainte : aucune propagation v2 de la convention sans ADR dédié.
- D4 clarifiée :
  - ajout de la règle “La recherche élève des nouveaux parcours lit uniquement rag-engine v2.” ;
  - ajout de l’interdiction de fallback legacy silencieux ;
  - ajout de la contrainte d’usage legacy uniquement pour continuité ou migration.

### 2) Rapport de cadrage de lot

- Création de `docs/reports/lot_26_1_cadrage_fusion.md`.
- Capture des décisions lot 26.1 avec limites de périmètre et invariants de non-régression.

### 3) Contrôle gouvernance

Les scripts de garde-fous imposés ont été exécutés après corrections :

- `bash scripts/check-governance-locks.sh`
- `bash scripts/tests/test-governance-locks.sh`

Résultats :

- `check-governance-locks.sh` : `Governance locks: baseline=18, config=18` puis `OK: all governance locks match baseline (18 keys verified).`
- `test-governance-locks.sh` : `16 passed, 0 failed, 16 total` (cas de tests validés, dont tests de non-régression ADR/baseline).

## Vérifications de périmètre

- Aucun fichier de runtime n’a été modifié.
- Aucun verrou de gouvernance n’a été touché.
- Aucun secret n’a été ajouté.
- Aucun déploiement production n’a été effectué.
- Validation d’exploitation: PR #49 reste en draft tant que ces corrections sont intégrées et re-vérifiées.

## Limites du lot

- La migration effective/implémentation reste aux lots suivants.
- Les mécanismes de sécurité centralisés, retrieval fail-closed, review workflow, migration Drive et adapter multimodal ne sont pas implémentés dans ce lot.

## Références

- `docs/reports/lot_26_cahier_charges_fusion_rag.md`
- `docs/adr/ADR-0014-fusion-rag-local-rag-anything.md`
- `services/rag-engine/configs/rag_collections.yml`
- `services/rag-engine/src/ingestor/collection_config.py`
- `docs/audits/AUDIT_FRONTEND_rag-ui.md`
- `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py`
- `services/rag-engine/src/ingestor/ingest_v2.py`
- `services/rag-engine/src/ingestor/ingest_v2_endpoint.py`
