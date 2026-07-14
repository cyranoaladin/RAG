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
  - Exiger des appels de rendu Streamlit pour `API connectée`, `Backend RAG v2`, `Dashboard RAG v2`, `Catalogue scolaire Nexus Réussite`, `Recherche RAG v2`, le texte « seules les collections instanciées et interrogeables », `Ingestion RAG v2`, `Collection cible`, `Type de document`, `Droits`, `needs_review`, `Administration RAG v2`, `Catalogue v2 complet`, `Collections instanciées`, `Collections déclarées non instanciées`, `Collections retrievable`, `Quarantaine` et `Contrôles de cohérence`.
  - Exiger les métriques Dashboard `Déclarées`, `Instanciées` et `Non instanciées`.
  - Vérifier l'inventaire exact des routes de présentation : `/health`, `/catalogue/v2`, `/collections/v2`, `/search/v2`, `/ingest/v2/upload-files` et `/ingest/v2/urls` ; aucune autre route métier ne doit être ajoutée.
  - Interdire l'URL interne `http://ingestor:8001` dans tout texte rendu, `/stats`, `/ingest/upload-files`, `/ingest/urls`, `/ingest/drive`, `Collections ChromaDB` et les cinq collections legacy `rag_francais_premiere`, `rag_maths_premiere`, `rag_education`, `rag_web3`, `rag_divers`.
- [ ] **Step 2: Verify RED**
  - Run `pytest tests/test_ui_app_v2_admin.py -q` depuis `services/rag-engine`.
  - Expected: échec sur les nouveaux libellés de statut, sous-titre et groupements absents.
  - Consigner la sortie RED et son motif dans le rapport de lot.
- [ ] **Step 3: Implement minimal UI text/layout changes**
  - Remplacer l'URL interne de sidebar par le statut validé.
  - Ajouter titres, sous-titres et libellés sans modifier les appels API.
- [ ] **Step 4: Verify GREEN**
  - Run `pytest tests/test_ui_app_v2_admin.py -q`.
  - Expected: toutes les assertions passent.
  - Consigner la sortie GREEN dans le rapport de lot.

## Chunk 2: E2E et documentation Ops

### Task 2: Ajouter l'E2E versionné du lot

**Files:**
- Create: `scripts/e2e/lot27-p3-ui-readonly.js`
- Create: `scripts/e2e/run-lot27-p3-ui-readonly.sh`

- [ ] **Step 1: Write failing E2E assertions**
  - Couvrir Dashboard, Recherche, Ingestion et Administration ; vérifier les libellés de page, `Catalogue v2 complet`, les collections legacy et les absences `API 403`, `Forbidden`, `/stats` et `Collections ChromaDB` dans le contenu rendu comme dans les réponses réseau.
- [ ] **Step 2: Décider le traitement de la PR #56**
  - Constater que #56 est ouverte et draft ; conserver #56 ouverte et intégrer dans cette PR son adaptation E2E, car elle porte aussi le polissage UI LOT 27 P3.
  - Créer un worktree temporaire de lecture seule avec `git worktree add /tmp/rag-pr56-e2e codex/post-go-live-p3-zero-debt-hardening`, consigner son SHA, puis exécuter obligatoirement `git -C /tmp/rag-pr56-e2e bash scripts/e2e/run-rag-v2-prod-readonly.sh` ; documenter toute erreur d'exécution factuelle.
  - Porter ses assertions dans cette PR pour les quatre pages et `Catalogue v2 complet`, sans merger ni modifier #56.
- [ ] **Step 3: Verify RED**
  - Lancer le fichier avant son implémentation complète et constater l'échec attendu.
- [ ] **Step 4: Implement read-only runner**
  - Navigation sans interaction d'ingestion, sans sélection de fichier ni bouton de soumission.
  - Intercepter et faire échouer toute requête non GET/HEAD/OPTIONS par défaut ; n'autoriser que le POST `/search/v2`, explicitement qualifié de lecture. Cette règle couvre notamment `/ingest/v2/upload-files`, `/ingest/v2/urls` et toute route Drive.
- [ ] **Step 5: Verify GREEN**
  - Exécuter l'E2E contre l'UI publique seulement si l'outillage est disponible ; sinon documenter le motif factuel.

### Task 3: Documenter les conteneurs orphelins

**Files:**
- Create: `docs/ops/orphan_containers_lot27.md`

- [ ] **Step 1: Write documentation**
  - Citer l'inventaire de production observé le 2026-07-14 comme source lue seule.
  - Décrire, pour chacun de `infra-web-1`, `infra-postgres-1`, `infra-minio-1`, l'image, projet Compose, service, ports, état, impact prod, décision « ne pas supprimer sans audit propriétaire », risque faible conditionné à l'absence de conflit port/proxy et action future « audit Ops dédié ».
- [ ] **Step 2: Verify content**
  - Contrôler les trois noms et, pour chaque ligne, les neuf champs requis et la décision de non-suppression.

## Chunk 3: Rapport, qualité et PR

### Task 4: Produire le rapport de lot et vérifier

**Files:**
- Create: `docs/reports/lot_27_p3_ux_e2e_ops_closure.md`

- [ ] **Step 1: Documenter le périmètre et les commandes exécutées**
  - Consigner les sorties et codes de retour factuels de chaque vérification, les preuves RED/GREEN, le résultat E2E et, le cas échéant, toute dette préexistante avec son antériorité.
- [ ] **Step 2: Run required checks**
  - `make lint`, `make typecheck`, `make test` depuis `services/rag-engine`.
  - `bash scripts/check-governance-locks.sh`, `bash scripts/tests/test-governance-locks.sh`, `git diff --check` depuis la racine.
- [ ] **Step 3: Commit and create draft PR**
  - Commit avec un message scopé puis pousser `codex/lot27-p3-ux-e2e-ops-closure`.
  - Ouvrir sans merge exactement avec :
    ```bash
    gh pr create --draft --base main --head codex/lot27-p3-ux-e2e-ops-closure \
      --title "LOT 27 P3 — UX polish, E2E update and ops documentation" \
      --body "$(cat <<'EOF'
    ## Summary

    Closes the remaining P3 items after LOT 27 go-live.

    ## Fixes

    - UX polish for Streamlit frontend.
    - Hides/discreetly moves internal API URL from public-facing sidebar.
    - Keeps RAG v2 business logic unchanged.
    - Updates E2E expectations for Administration: `Catalogue v2 complet`.
    - Documents orphan containers observed during deployment.

    ## Scope

    P3 only.

    No backend contract change.
    No Nginx change.
    No DB migration.
    No data mutation.
    No deployment.

    ## Validation

    - rag-engine lint/typecheck/test
    - governance checks
    - git diff --check
    - E2E read-only if available
    EOF
    )"
    ```
