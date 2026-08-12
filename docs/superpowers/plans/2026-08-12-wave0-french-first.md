# Wave 0 French-First Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publier le PDF Français 3e scellé dans pgvector, traiter le signal PII Maths séparément et tenter une alternative sûre si nécessaire.

**Architecture:** Un resolver artifact-bound produit une projection gouvernée commune aux Workers A/B. La preuve PII reste indexée par SHA, et Phase B lie l'attestation exacte avant toute transition. Les flux de revue et alternatives Maths restent sans état partagé avec le vertical Français.

**Tech Stack:** Python 3.11+, Pydantic, PyYAML, psycopg 3, PostgreSQL 16, pgvector, pytest/testcontainers, ruff, mypy.

---

## Chunk 1: Currentness et placement

### Task 1: Overlay currentness exact

**Files:**
- Create: `services/rag-pedago/configs/prerentree_2026_2027/wave0_currentness_evidence.yml`
- Create: `services/rag-engine/src/ingestor/verified_pedagogical_placement.py`
- Create: `services/rag-engine/tests/test_wave0_verified_placement.py`

- [ ] Écrire les tests rouges du loader : positif 2 SHA, SHA/path/manifest/année/matière/niveau divergents et doublon.
- [ ] Exécuter le test ciblé et constater l'import manquant.
- [ ] Ajouter la preuve exacte et le loader minimal fail-closed.
- [ ] Exécuter le test ciblé jusqu'au vert.

### Task 2: Resolver et profils Français/Maths

**Files:**
- Create: `services/rag-engine/configs/ingestion_profiles/staging/francais_troisieme_tc_wave0_v1.yml`
- Create: `services/rag-engine/configs/ingestion_profiles/staging/maths_troisieme_tc_wave0_v1.yml`
- Modify: `services/rag-engine/configs/rag_collections.yml`
- Modify: `services/rag-engine/src/ingestor/verified_pedagogical_placement.py`
- Modify: `services/rag-engine/tests/test_wave0_verified_placement.py`

- [ ] Écrire les tests rouges placement unique, 0/>1, `3e -> troisieme`, `college`, matière et TypeDoc.
- [ ] Exécuter et vérifier les échecs fonctionnels attendus.
- [ ] Implémenter les mappings explicites et profils
  `BOEN_special_11_2018-07-26_aj_2020` minimaux.
- [ ] Exécuter les tests ciblés, ruff et mypy ciblés.

## Chunk 2: Worker A Français

### Task 3: Conformité et droits scellés

**Files:**
- Modify: `services/rag-engine/src/ingestor/ingestion_agents/classifier.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/runner.py`
- Modify: `services/rag-engine/tests/integration/test_lot44e_worker_e2e.py`
- Create: `services/rag-engine/tests/integration/test_wave0_worker_a.py`

- [ ] Écrire le test rouge qui conserve trois `False` sans placement.
- [ ] Écrire le test rouge de conformité positive et provenance `CLASSIFIED` avec placement.
- [ ] Écrire le test rouge `source_path` payload divergent et chemin catalogue transmis aux droits.
- [ ] Exécuter et relever les motifs rouges exacts.
- [ ] Ajouter l'entrée de conformité vérifiée et l'intégration resolver minimale.
- [ ] Faire atteindre `NEEDS_REVIEW` au Français avec `rejection_reasons=[]`.
- [ ] Exécuter les tests Worker A jusqu'au vert.

## Chunk 3: Worker B Français

### Task 4: Attestation exacte et transactions

**Files:**
- Modify: `services/rag-engine/src/ingestor/ingestion_control/publication_attestation.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_control/governed_publication_path.py`
- Modify: `services/rag-engine/src/ingestor/ingestion_worker/publication_resume.py`
- Create: `services/rag-engine/tests/integration/test_wave0_publication_resume.py`

- [ ] Écrire le test rouge attestation A/job B sans transition ni produit.
- [ ] Écrire le test rouge droits via `verified_placement.source_path`.
- [ ] Écrire le test rouge control/product idle à l'entrée du publisher.
- [ ] Exécuter et confirmer les échecs attendus.
- [ ] Propager `expected_attestation_id` avant le premier CAS.
- [ ] Committer preflight/promotion avant publication sans SELECT parasite.
- [ ] Exécuter les tests ciblés jusqu'au vert.

## Chunk 4: E2E pgvector réel

### Task 5: Pilote Français et déduplication

**Files:**
- Create: `services/rag-engine/scripts/wave0_ingest_pilots.py`
- Create: `services/rag-engine/tests/integration/test_wave0_real_pilots.py`
- Create: `docs/reports/lot_wave0_maths_francais_ingestion.md`

- [ ] Matérialiser exactement les vrais octets Français dans un scratch 0700 et vérifier le SHA.
- [ ] Écrire l'E2E rouge Worker A -> LocalGitHub LOT42 -> Worker B -> pgvector.
- [ ] Exécuter avec deux PostgreSQL jetables et relever le premier blocker.
- [ ] Corriger chaque blocker par un test rouge minimal puis vert.
- [ ] Vérifier 1 artifact, >=1 placement et >0 chunks Français.
- [ ] Relancer et vérifier zéro doublon et `embedded=false`.

### Task 6: Maths original ou alternative

- [ ] Intégrer la classification contrôlée sans modifier la preuve source.
- [ ] Si non libéré, choisir la meilleure alternative PII-cleared et ajouter son currentness artifact-bound.
- [ ] Passer le pilote Maths par le même pipeline sans branche de code matière.
- [ ] Vérifier ses compteurs ou consigner le gate exact des trois alternatives.

## Chunk 5: Vérification et livraison

### Task 7: Qualité et revue

- [ ] Exécuter les suites ciblées Wave 0 fraîches.
- [ ] Exécuter lint, typecheck et tests des services touchés.
- [ ] Exécuter `bash scripts/ci-local.sh` et consigner le résultat.
- [ ] Auditer les verrous et l'absence de currentness hors périmètre.
- [ ] Demander une revue de conformité puis une revue qualité.
- [ ] Corriger tout point Critical/Important et revérifier.
- [ ] Committer un vertical slice cohérent avec les deux SHA et métriques.
