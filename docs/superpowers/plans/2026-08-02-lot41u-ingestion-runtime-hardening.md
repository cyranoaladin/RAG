# LOT41U Ingestion Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remplacer le runtime v2 mixte par une image lecture/revue fail-closed, appliquer automatiquement le head PostgreSQL 003 sur une base neuve et fermer toute surface d'ingestion ou legacy.

**Architecture:** `api_v2.py` devient l'unique application du stack v2. L'image copie une allowlist de modules, Compose applique et contrôle 003, et Nginx ne transmet qu'une allowlist BFF. L'ingestion reste absente jusqu'à une remise autoritaire `quality → gate → review`.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, psycopg 3, PostgreSQL 16/pgvector, Docker Compose, Nginx, pytest, Ruff, mypy.

---

## Chunk 1: Décision et application minimale

### Task 1: Acter la séparation du runtime

**Files:**
- Create: `docs/adr/ADR-0024-runtime-v2-lecture-revue-fail-closed.md`
- Modify: `docs/ROADMAP.md`
- Create: `services/rag-engine/tests/test_v2_runtime_surface.py`

- [ ] Écrire un test rouge exigeant un ADR accepté qui interdit le writer v2 avant LOT41A/LOT42, impose 003 et distingue le legacy.
- [ ] Run: `cd services/rag-engine && .venv/bin/python -m pytest -q tests/test_v2_runtime_surface.py::test_adr_closes_ungoverned_v2_ingestion`.
- [ ] Écrire l'ADR et raccorder le lot 41U à la roadmap, sans modifier les phases historiques.
- [ ] Relancer le test ; attendu : PASS.
- [ ] Commit: `docs: acte le runtime v2 lecture-revue`.

### Task 2: Vérifier le schéma 003 en lecture seule

**Files:**
- Create: `services/rag-engine/src/ingestor/schema_readiness_v2.py`
- Create: `services/rag-engine/tests/test_schema_readiness_v2.py`

- [ ] Écrire des tests rouges avec cursors factices : cinq colonnes de profil, index `idx_rag_chunks_profile_reviewed`, cinq contraintes LOT41, cas manquants, erreur psycopg, SQL sans mutation.
- [ ] Run: `.venv/bin/python -m pytest -q tests/test_schema_readiness_v2.py`; attendu : import absent.
- [ ] Implémenter `schema_head_003_ready(dsn)` avec `psycopg.connect`, catalogues PostgreSQL et ensembles immuables ; aucun fallback owner.
- [ ] Relancer pytest puis Ruff sur le module et le test ; attendu : PASS.
- [ ] Commit: `rag-engine: vérifie le head PostgreSQL v2`.

### Task 3: Créer `api_v2.py`

**Files:**
- Create: `services/rag-engine/src/ingestor/api_v2.py`
- Modify: `services/rag-engine/tests/test_v2_runtime_surface.py`
- Modify: `services/rag-engine/tests/test_ingestor_flattened_runtime.py`
- Modify: `services/rag-engine/tests/test_api_pool_lifecycle.py`
- Modify: `services/rag-engine/tests/test_embedding_contract.py`

- [ ] Écrire les tests rouges exigeant seulement santé, métriques, retrieval, catalogue, readiness et review ; interdire `/ingest*`, `/admin*`, `/search`, `/rag/query`, `/collections` et `/stats/*`.
- [ ] Tester import aplati, fermeture du pool, santé 200 avec DSN reader + 003 + dimension valide, 503 générique sur toute indisponibilité et métriques désactivables.
- [ ] Run: `.venv/bin/python -m pytest -q tests/test_v2_runtime_surface.py tests/test_ingestor_flattened_runtime.py tests/test_api_pool_lifecycle.py tests/test_embedding_contract.py`; attendu : FAIL.
- [ ] Implémenter l'application avec imports package/top-level, routeurs retrieval/review, lifespan, santé read-only, métriques et docs masquées en production.
- [ ] Relancer pytest et Ruff ; attendu : PASS.
- [ ] Commit: `rag-engine: isole l'API v2 lecture-revue`.

## Chunk 2: Image et stack sans writer

### Task 4: Réduire l'image v2

**Files:**
- Create: `services/rag-engine/src/ingestor/requirements.runtime-v2.txt`
- Modify: `services/rag-engine/infra/Dockerfile.ingestor-v2`
- Modify: `.dockerignore`
- Modify: `services/rag-engine/tests/test_v2_runtime_surface.py`
- Modify: `services/rag-engine/tests/test_prod_compose_config_mount.py`
- Modify: `services/rag-engine/tests/test_pg_pool.py`

- [ ] Écrire les tests rouges exigeant `api_v2:app`, une liste runtime unique et des copies explicites ; interdire `api.py`, `admin_api.py`, `ingest_v2*`, `tasks.py`, `database.py`, ChromaDB, Celery, Redis, Ollama, clients URL et parseurs.
- [ ] Run: pytest sur les trois fichiers de tests ; attendu : FAIL sur le Dockerfile global actuel.
- [ ] Conserver seulement FastAPI/Uvicorn, Pydantic, PyYAML, psycopg/binary/pool, sentence-transformers et prometheus-client ; conserver `pip check`.
- [ ] Construire `nexus-rag-engine-v2:lot41u`, puis vérifier dans le conteneur que `/app/api_v2.py` existe et que `/app/api.py` et `/app/tasks.py` sont absents.
- [ ] Relancer pytest ; attendu : PASS.
- [ ] Commit: `rag-engine: réduit l'image v2 au runtime gouverné`.

### Task 5: Rendre Compose frais conforme à 003

**Files:**
- Modify: `services/rag-engine/infra/docker-compose.v2.yml`
- Create: `services/rag-engine/infra/prometheus/prometheus.v2.yml`
- Modify: `services/rag-engine/Makefile`
- Modify: `services/rag-engine/tests/test_profile_filtering_migration.py`
- Modify: `services/rag-engine/tests/test_prod_compose_config_mount.py`
- Modify: `services/rag-engine/tests/test_embedding_model_artifact_contract.py`
- Modify: `services/rag-engine/tests/test_ingestion_embedding_path_audit_contract.py`

- [ ] Écrire les tests rouges exigeant le montage canonique 003, le healthcheck des cinq colonnes, `api_v2:app`, les DSN runtime obligatoires et l'absence de DSN owner, tokens ingest, uploads, worker, Redis, Ollama et UI.
- [ ] Exiger un Prometheus v2 minimal et `make v2-up` bloquant via `up --wait`, sans `||`.
- [ ] Run: pytest sur les quatre fichiers ; attendu : FAIL.
- [ ] Réduire Compose aux services PostgreSQL, ingestor lecture/revue et Prometheus ; supprimer les cibles Makefile d'écriture legacy.
- [ ] Rendre Compose avec des valeurs factices, puis démarrer un projet PostgreSQL temporaire et vérifier réellement colonnes, index et contraintes avant suppression de ce seul projet.
- [ ] Relancer pytest ; attendu : PASS.
- [ ] Commit: `rag-engine: bloque le stack v2 au schéma 003`.

## Chunk 3: Réseau et vérité opérationnelle

### Task 6: Fermer Nginx par allowlist

**Files:**
- Modify: `services/rag-engine/infra/nginx/rag-v2.conf`
- Modify: `services/rag-engine/infra/nginx/rag-api.conf.template`
- Modify: `services/rag-engine/tests/test_lot41_legacy_route_closure.py`

- [ ] Écrire les tests rouges : `/ingest` en 410 sans proxy, neuf routes exactes autorisées, métriques loopback, aucun upstream UI/admin/stats/eval, default 404.
- [ ] Run: pytest du fichier ; attendu : FAIL sur le proxy ingest et le pass-through.
- [ ] Implémenter l'allowlist sans utiliser `Host` ou `X-Forwarded-*` comme autorité.
- [ ] Relancer pytest et valider `nginx -t` sur les templates rendus ; attendu : PASS.
- [ ] Commit: `rag-engine: ferme le proxy v2 par allowlist`.

### Task 7: Aligner les procédures

**Files:**
- Modify: `docs/runbooks/go_live.md`
- Modify: `README.md`
- Modify: `services/rag-engine/README-PROD.md`
- Modify: `services/rag-engine/AGENTS.md`
- Modify: `services/rag-engine/tests/test_v2_runtime_surface.py`

- [ ] Écrire les tests rouges interdisant dans le go-live canonique `/ingest/v2`, l'alternative Chroma, preload Ollama et tokens humains directs.
- [ ] Exiger Cockpit BFF, migration des volumes existants, bootstrap frais 003 et ingestion fermée jusqu'à LOT41A/LOT42.
- [ ] Corriger uniquement les sections devenues fausses ; conserver l'historique clairement étiqueté et ne jamais modifier l'AGENTS racine.
- [ ] Relancer les tests et `git diff --check`; attendu : PASS.
- [ ] Commit: `docs: aligne le go-live sur le runtime v2 fermé`.

## Chunk 4: Preuves et livraison

### Task 8: Régression complète

- [ ] Lancer les suites ciblées runtime, schema, Nginx, migrations, Dockerfile, retrieval, review, identité et sécurité.
- [ ] Depuis `services/rag-engine`, lancer `make lint`, `make typecheck`, `make test`, puis `make test-integration`.
- [ ] Auditer `api:app`, `celery -A tasks`, `/ingest` et `DATABASE_URL_SYNC` dans les quatre fichiers actifs v2 ; aucune surface interdite ne doit rester.
- [ ] Corriger seulement les vraies régressions par nouveau cycle rouge/vert ; ne jamais affaiblir un garde-fou historique.

### Task 9: Rapport et CI racine

**Files:**
- Create: `docs/reports/lot_41u_ingestion_runtime_hardening.md`

- [ ] Lancer `bash scripts/ci-local.sh` depuis la racine du worktree.
- [ ] Consigner baseline, commits, cycles RED/GREEN, tests, limites et verrous dans le rapport ; garder `GO_LIVE: NO_GO` jusqu'à LOT41A/LOT42, revue golden et preuves externes.
- [ ] Commit: `docs: consigne le durcissement du runtime v2`.
- [ ] Rejouer CI locale, `git diff --check origin/main...HEAD`, `bash scripts/check-governance-locks.sh` et le scan de secrets sur le head final ; ne plus le modifier ensuite.

### Task 10: Revue, PR et fusion

- [ ] Appliquer `superpowers:requesting-code-review` sur `origin/main..HEAD` et corriger tout constat valide par TDD.
- [ ] Pousser la branche et ouvrir une PR ; jamais de push direct sur `main`.
- [ ] Attendre les six checks `pull_request` du head exact et résoudre tous les fils.
- [ ] Fusionner seulement quand la protection l'autorise, puis vérifier le SHA et le run `push` exact de `main`.
- [ ] LOT41U ferme les P1 runtime ; il ne transforme pas le verdict global en GO.
