# LOT 26.1 — Cadrage de convergence (ADR-0014)

**Date** : 2026-07-09
**Issue pilotage** : #47
**Branche** : `codex/lot26-1-adr-convergence`
**Statut** : prêt à revue (lot cadrage)

---

## Objectif du lot

Formaliser l’architecture de convergence autour du dépôt canonique et produire le cadrage documenté pour les lots LOT 26.2 → LOT 26.10.

## Travaux réalisés

### 1) Documentation et ADR

- Création de l’ADR : `docs/adr/ADR-0014-fusion-rag-local-rag-anything.md`
- Confirmation des décisions de convergence :
  - dépôt canonique = `cyranoaladin/RAG` (seul).
  - `rag-local` = legacy lisible/intégré en source (pas de fusion à plat).
  - `RAG-Anything` = adaptateur multimodal optionnel.
  - coexistence legacy/v2 planifiée via shadow puis canary.
  - `rag_nexus_*` + `instanciee` pour le pilotage v2 ; pas d’auto-création.
  - tenant logique attendu en `{population}_{niveau}`.

### 2) Rapport de cadrage de lot

- Création de `docs/reports/lot_26_1_cadrage_fusion.md`.
- Capture des décisions lot 26.1 avec limites de périmètre et invariants de non-régression.

### 3) Contrôle gouvernance

Les scripts de garde-fous imposés ont été exécutés après création des documents :

- `bash scripts/check-governance-locks.sh`
- `bash scripts/tests/test-governance-locks.sh`

## Vérifications de périmètre

- Aucun fichier de runtime n’a été modifié.
- Aucun verrou de gouvernance n’a été touché.
- Aucun secret n’a été ajouté.

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
