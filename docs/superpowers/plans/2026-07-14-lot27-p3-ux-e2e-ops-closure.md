# LOT 27 P3 UX E2E Ops Closure Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clore les P3 LOT 27 par un polissage UI sans changement métier, des E2E v2 complets et une documentation des conteneurs orphelins.

**Architecture:** `app_v2.py` conserve toutes ses routes et flux ; seuls les textes et regroupements Streamlit évoluent. Les tests statiques couvrent les invariants UI et un E2E versionné couvre les quatre écrans. La documentation Ops ne déclenche aucune opération Docker.

**Tech Stack:** Python 3.11, Streamlit, pytest, Playwright, Bash, Markdown.

---

## Chunk 1: Tests et polissage UI

### Task 1: Étendre les tests UI statiques

**Files:**
- Modify: `services/rag-engine/tests/test_ui_app_v2_admin.py`
- Modify: `services/rag-engine/src/ui/app_v2.py`

- [ ] **Step 1: Write failing tests**
  - Exiger `API connectée`, `Backend RAG v2`, le sous-titre Dashboard, l'aide Recherche, le rappel `needs_review`, `Catalogue v2 complet`.
  - Interdire `st.sidebar.caption(f"API : `{API_BASE}`")`, `/stats`, les routes legacy et les collections legacy.
- [ ] **Step 2: Verify RED**
  - Run `pytest tests/test_ui_app_v2_admin.py -q` depuis `services/rag-engine`.
  - Expected: échec sur les nouveaux libellés absents.
- [ ] **Step 3: Implement minimal UI text/layout changes**
  - Remplacer l'URL interne de sidebar par le statut validé.
  - Ajouter titres, sous-titres et libellés sans modifier les appels API.
- [ ] **Step 4: Verify GREEN**
  - Run `pytest tests/test_ui_app_v2_admin.py -q`.
  - Expected: toutes les assertions passent.

## Chunk 2: E2E et documentation Ops

### Task 2: Ajouter l'E2E versionné du lot

**Files:**
- Create: `scripts/e2e/lot27-p3-ui-readonly.js`
- Create: `scripts/e2e/run-lot27-p3-ui-readonly.sh`

- [ ] **Step 1: Write failing E2E assertions**
  - Couvrir Dashboard, Recherche, Ingestion et Administration ; vérifier `Catalogue v2 complet` et les interdits.
- [ ] **Step 2: Verify RED**
  - Lancer le fichier avant son implémentation complète et constater l'échec attendu.
- [ ] **Step 3: Implement read-only runner**
  - Navigation sans interaction d'ingestion ni modification de données.
- [ ] **Step 4: Verify GREEN**
  - Exécuter l'E2E contre l'UI publique seulement si l'outillage est disponible ; sinon documenter le motif factuel.

### Task 3: Documenter les conteneurs orphelins

**Files:**
- Create: `docs/ops/orphan_containers_lot27.md`

- [ ] **Step 1: Write documentation**
  - Décrire image, projet Compose, service, ports, état, impact, risque et action future des trois conteneurs observés.
- [ ] **Step 2: Verify content**
  - Contrôler les trois noms et la décision de non-suppression.

## Chunk 3: Rapport, qualité et PR

### Task 4: Produire le rapport de lot et vérifier

**Files:**
- Create: `docs/reports/lot_27_p3_ux_e2e_ops_closure.md`

- [ ] **Step 1: Documenter le périmètre et les commandes exécutées**
- [ ] **Step 2: Run required checks**
  - `make lint`, `make typecheck`, `make test` depuis `services/rag-engine`.
  - `bash scripts/check-governance-locks.sh`, `bash scripts/tests/test-governance-locks.sh`, `git diff --check` depuis la racine.
- [ ] **Step 3: Commit and create draft PR**
  - Commit avec un message scopé puis pousser `codex/lot27-p3-ux-e2e-ops-closure`.
  - Ouvrir la PR draft au titre exigé, sans merge.
