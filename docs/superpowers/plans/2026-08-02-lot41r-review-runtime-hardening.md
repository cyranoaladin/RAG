# LOT41R Review Runtime Hardening Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Corriger les trois P1 post-LOT40/41 : démarrage de l'image ingestor aplatie, chemin de review humain via le BFF authentifié et reprise Redis après une panne transitoire.

**Architecture:** Le moteur conserve son image aplatie mais ses deux modules LOT40 acceptent les imports package et top-level. `nexus-contracts` 0.5.0 porte les modèles de review navigateur/BFF/moteur et leurs réponses ; deux routes Cockpit explicites valident session, rôle et scope avant de transmettre les credentials serveur. Le store Redis reste fail-closed et ne met en cache que la tentative de connexion courante.

**Tech Stack:** Python 3.11, FastAPI, Pydantic 2, pytest, Next.js 16 App Router, TypeScript 5.9, Vitest, Redis, JSON Schema, Ruff, mypy, ESLint.

**Spec:** `docs/superpowers/specs/2026-08-02-lot41r-review-runtime-hardening-design.md`

---

## Cartographie des fichiers

| Fichier | Responsabilité |
| --- | --- |
| `services/rag-engine/tests/test_ingestor_flattened_runtime.py` | Reproduire exactement l'import `uvicorn api:app` du layout Docker aplati |
| `services/rag-engine/src/ingestor/retrieval_pg_v2.py` | Compatibilité d'import des primitives hybrides et du scope |
| `services/rag-engine/src/ingestor/retrieval_scope_v2.py` | Compatibilité d'import de la configuration et de l'identité |
| `packages/contracts/src/nexus_contracts/review.py` | Modèles canoniques queue/décision et réponses |
| `packages/contracts/tests/test_review_contract.py` | Validation stricte, bornes, séparation navigateur/moteur |
| `packages/contracts/{pyproject.toml,scripts/export_schemas.py,src/nexus_contracts/__init__.py}` | Version 0.5.0 et export public |
| `services/cockpit/scripts/generate-contracts.mjs` | Génération TypeScript et validateurs review |
| `docs/adr/ADR-0023-review-bff-et-durcissement-runtime.md` | Extension du périmètre ADR-0002 et frontière BFF |
| `services/rag-engine/src/ingestor/review_v2_endpoint.py` | Consommer le contrat partagé et dériver le tenant signé |
| `services/rag-engine/tests/{test_review_v2.py,test_lot41_review_scope.py}` | Refus du champ historique et preuves de scope/transition |
| `services/cockpit/src/app/api/_engine.ts` | Allowlist des endpoints review et query string bornée |
| `services/cockpit/src/app/api/review/_auth.ts` | Autorisation BFF commune `admin|reviewer` |
| `services/cockpit/src/app/api/review/{queue,decide}/route.ts` | Proxies same-origin explicites |
| `services/cockpit/src/app/api/review/{queue,decide}/route.test.ts` | Auth, rôle, scope, contrat, erreurs et non-divulgation |
| `services/cockpit/src/server/revocation-store.ts` | Cache conditionnel de la tentative Redis courante |
| `services/cockpit/src/server/revocation-store.redis.test.ts` | Panne concurrente, reprise et course ancienne/nouvelle tentative |
| `docs/runbooks/go_live.md` | Parcours opérateur via Cockpit BFF |
| `docs/checklists/production_go_live_checklist.md` | Contrôles production alignés sur le BFF |
| `docs/reports/lot_41r_review_runtime_hardening.md` | Preuves, SHA, CI et verdict du lot |

## Chunk 1 — Runtime aplati et contrat partagé

### Task 1: Verrouiller le démarrage de l'image ingestor aplatie

**Files:**
- Create: `services/rag-engine/tests/test_ingestor_flattened_runtime.py`
- Modify: `services/rag-engine/src/ingestor/retrieval_pg_v2.py`
- Modify: `services/rag-engine/src/ingestor/retrieval_scope_v2.py`

- [ ] **Step 1: Écrire le test rouge du vrai entrypoint**

Créer un test qui lance `sys.executable -I -c` depuis un répertoire temporaire,
insère seulement `packages/contracts/src` et `services/rag-engine/src/ingestor`
dans `sys.path`, importe `api` puis vérifie `api.app.title`.

```python
def test_flattened_ingestor_runtime_imports_api(tmp_path: Path) -> None:
    code = (
        "import sys; "
        f"sys.path.insert(0, {str(CONTRACTS_SRC)!r}); "
        f"sys.path.insert(0, {str(INGESTOR_SRC)!r}); "
        "import api; print(api.app.title)"
    )
    completed = subprocess.run(
        [sys.executable, "-I", "-c", code],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.strip() == "RAG Ingestor API"
```

- [ ] **Step 2: Vérifier le rouge**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_ingestor_flattened_runtime.py -q`

Expected: FAIL avec `ModuleNotFoundError: No module named 'ingestor'` depuis `retrieval_pg_v2.py`.

- [ ] **Step 3: Ajouter les deux fallbacks minimaux**

Dans chacun des deux modules, tenter les imports relatifs puis ré-essayer en
top-level uniquement lorsque `__package__` est vide. Si le module est chargé en
mode package, toute erreur interne doit être relevée sans fallback afin de ne
pas masquer une dépendance réellement cassée. Ne pas modifier le Dockerfile ni
les entrypoints Uvicorn/Celery.

- [ ] **Step 4: Vérifier le vert et les deux modes d'import**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_ingestor_flattened_runtime.py tests/test_retrieval_pg_v2.py tests/test_retrieval_scope_v2.py -q`

Expected: PASS.

- [ ] **Step 5: Vérifier qualité et commit**

Run: `cd services/rag-engine && .venv/bin/ruff check src/ingestor/retrieval_pg_v2.py src/ingestor/retrieval_scope_v2.py tests/test_ingestor_flattened_runtime.py && .venv/bin/mypy src/ingestor/retrieval_pg_v2.py src/ingestor/retrieval_scope_v2.py`

Expected: PASS.

```bash
git add services/rag-engine/src/ingestor/retrieval_pg_v2.py \
  services/rag-engine/src/ingestor/retrieval_scope_v2.py \
  services/rag-engine/tests/test_ingestor_flattened_runtime.py
git commit -m "rag-engine: supporter le runtime ingestor aplati"
```

### Task 2: Publier le protocole de review dans `nexus-contracts` 0.5.0

**Files:**
- Create: `packages/contracts/src/nexus_contracts/review.py`
- Create: `packages/contracts/tests/test_review_contract.py`
- Create: `docs/adr/ADR-0023-review-bff-et-durcissement-runtime.md`
- Modify: `packages/contracts/src/nexus_contracts/__init__.py`
- Modify: `packages/contracts/pyproject.toml`
- Modify: `packages/contracts/scripts/export_schemas.py`
- Modify: `packages/contracts/tests/test_schema_export.py`
- Modify: `services/cockpit/scripts/generate-contracts.mjs`
- Generate: `packages/contracts/schema/review-*.json` (cinq messages d'échange)
- Generate: `services/cockpit/src/generated/contracts.ts`
- Generate: `services/cockpit/src/generated/validators.ts`
- Generate: `services/cockpit/src/generated/schema/review-*.json`

- [ ] **Step 1: Écrire les tests rouges du contrat**

Tester les invariants suivants :

- `ReviewQueuePayload` accepte uniquement `collection`, `limit` 1..500 et
  `offset >= 0`, sans tenant ni clé extra ;
- `ReviewDecisionPayload` accepte seulement `doc|chunk` et
  `reviewed|quarantined`, sans `tenant` ni `reason` ;
- `ReviewDecisionRequest` exige le tenant serveur ;
- les deux réponses refusent types coercitifs, compte négatif et clé extra ;
- version package `0.5.0`, IDs de schéma `/v0.5/` et liste déterministe complète.

- [ ] **Step 2: Vérifier le rouge**

Run: `PYTHONPATH=packages/contracts/src services/rag-engine/.venv/bin/python -m pytest packages/contracts/tests/test_review_contract.py packages/contracts/tests/test_schema_export.py -q`

Expected: FAIL à l'import des modèles review et sur la version `0.4.0`.

- [ ] **Step 3: Implémenter les modèles canoniques minimaux**

Utiliser `StrictBaseModel`, `StrictInt`, `StrictStr`, `CollectionName` et
`BoundedSlug`. Les six modèles sont exactement :

- `ReviewQueuePayload(collection: CollectionName|None=None, limit:
  StrictInt=50 [1..500], offset: StrictInt=0 [>=0])` ;
- `ReviewDecisionPayload(target_type: Literal['doc','chunk']='doc', target_id:
  StrictStr [1..256], decision: Literal['reviewed','quarantined'], collection:
  CollectionName|None=None)` ;
- `ReviewDecisionRequest`, mêmes champs que le payload plus `tenant:
  BoundedSlug` requis ;
- `ReviewQueueDocument(doc_id: StrictStr [1..256], collection:
  CollectionName, source_label/source_uri/rights/source_kind/type_doc:
  StrictStr, y compris vide et sans maximum additionnel,
  chunk_count: StrictInt [>=1], first_indexed: datetime|None, last_indexed:
  datetime|None)` ; ces champs de provenance suivent le domaine des colonnes
  PostgreSQL `TEXT` afin que la queue puisse exposer les lignes historiques à
  la review ou permettre leur mise en quarantaine ;
- `ReviewQueueResponse(total_pending_docs: StrictInt [>=0], returned:
  StrictInt [>=0], offset: StrictInt [>=0], documents:
  list[ReviewQueueDocument])`, avec validation `returned == len(documents)` ;
- `ReviewDecisionResponse(target_type, target_id, decision, chunks_affected:
  StrictInt [>=1], cache_invalidated_this_worker: bool,
  max_stale_other_workers_s: Literal[0])`.

Les cinq schémas racine sont `review-queue-payload.json`,
`review-decision-payload.json`, `review-decision-request.json`,
`review-queue-response.json` et `review-decision-response.json` ;
`ReviewQueueDocument` reste une définition imbriquée. Aucun champ libre ni I/O
ne doit entrer dans le package.

- [ ] **Step 4: Bumper SemVer et écrire l'ADR**

Passer `pyproject.toml` à `0.5.0` et `CONTRACT_VERSION` à `0.5`. L'ADR-0023 doit
amender explicitement le périmètre de l'ADR-0002, lier ADR-0022, expliquer la
séparation navigateur/BFF/moteur, le retrait de `reason`, le rollback et le fait
qu'aucun verrou n'est activé.

- [ ] **Step 5: Étendre les exports Python et Cockpit**

Ajouter les cinq schémas review à `SCHEMAS`, à la liste `schemas` du générateur
Cockpit et aux validateurs nécessaires. Exécuter :

Run: `PYTHONPATH=packages/contracts/src services/rag-engine/.venv/bin/python packages/contracts/scripts/export_schemas.py`

Run: `cd services/cockpit && npm run contracts:generate`

Expected: schémas et TypeScript générés sans édition manuelle.

- [ ] **Step 6: Vérifier contrat et génération**

Run: `PYTHONPATH=packages/contracts/src services/rag-engine/.venv/bin/python -m pytest packages/contracts/tests -q`

Run: `cd services/cockpit && npm run contracts:check && npm run typecheck`

Expected: PASS ; `reason` et `tenant` sont refusés par le payload navigateur.

- [ ] **Step 7: Vérifier qualité et commit**

Run: `PYTHONPATH=packages/contracts/src services/rag-engine/.venv/bin/python -m ruff check packages/contracts`

Run: `git diff --check && bash scripts/check-governance-locks.sh`

Expected: PASS et 18 verrous inchangés.

```bash
git add packages/contracts services/cockpit/scripts/generate-contracts.mjs \
  services/cockpit/src/generated docs/adr/ADR-0023-review-bff-et-durcissement-runtime.md
git commit -m "contracts: publier le protocole de review 0.5.0"
```

## Chunk 2 — Moteur canonique et routes BFF

### Task 3: Raccorder le moteur au contrat partagé

**Files:**
- Modify: `services/rag-engine/src/ingestor/review_v2_endpoint.py`
- Modify: `services/rag-engine/tests/test_review_v2.py`
- Modify: `services/rag-engine/tests/test_lot41_review_scope.py`

- [ ] **Step 1: Écrire les tests rouges du raccord**

Remplacer les imports du modèle local par `ReviewDecisionRequest` et ajouter :

- POST avec `reason` → `422` avant toute DB ;
- POST sans tenant → `422` ;
- POST avec tenant différent de l'identité → `403` avant DB ;
- GET queue avec tenant client → `422` ;
- réponses queue/décision conformes aux modèles partagés.

- [ ] **Step 2: Vérifier le rouge**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_review_v2.py tests/test_lot41_review_scope.py -q`

Expected: FAIL car le modèle local accepte encore `reason`/tenant optionnel et la queue accepte `tenant`.

- [ ] **Step 3: Remplacer les modèles locaux**

Importer les modèles review de `nexus_contracts`, supprimer `PendingQuery` et
`ReviewDecision`, utiliser `Annotated[ReviewQueuePayload, Query()]`, typer les
`response_model`, et fournir `tenant=None` à la résolution queue afin que seul
le tenant de l'identité soit autoritatif.

- [ ] **Step 4: Vérifier le vert et les invariants SQL**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_review_v2.py tests/test_lot41_review_scope.py tests/integration/test_lot40_hybrid_pgvector.py -q -m 'not integration'`

Expected: PASS sans accès DB pour les refus préalables.

- [ ] **Step 5: Vérifier qualité et commit**

Run: `cd services/rag-engine && .venv/bin/ruff check src/ingestor/review_v2_endpoint.py tests/test_review_v2.py tests/test_lot41_review_scope.py && .venv/bin/mypy src/ingestor/review_v2_endpoint.py`

Expected: PASS.

```bash
git add services/rag-engine/src/ingestor/review_v2_endpoint.py \
  services/rag-engine/tests/test_review_v2.py \
  services/rag-engine/tests/test_lot41_review_scope.py
git commit -m "rag-engine: appliquer le contrat partagé de review"
```

### Task 4: Étendre le client moteur BFF sans ouvrir de proxy générique

**Files:**
- Modify: `services/cockpit/src/app/api/_engine.ts`
- Modify: `services/cockpit/src/app/api/_engine.test.ts`

- [ ] **Step 1: Écrire les tests rouges**

Tester `/review/v2/queue` avec query encodée et `/review/v2/decide` avec corps,
en vérifiant les deux headers séparés, l'URL exacte, l'absence de token dans le
payload et le refus d'un endpoint non allowlisté au typecheck.

- [ ] **Step 2: Vérifier le rouge**

Run: `cd services/cockpit && npm test -- --run src/app/api/_engine.test.ts`

Expected: FAIL car les endpoints et paramètres query n'existent pas.

- [ ] **Step 3: Implémenter l'extension typée**

Ajouter seulement `'/review/v2/queue'|'/review/v2/decide'` à l'union et un type
fermé `EngineReviewQueueQuery` contenant uniquement `collection?`, `limit?` et
`offset?`. Le champ `query?: EngineReviewQueueQuery` n'est consommé que par la
queue. Construire l'URL avec `URL`/`searchParams`, jamais par concaténation de
donnée client dans le chemin.

- [ ] **Step 4: Vérifier et commit**

Run: `cd services/cockpit && npm test -- --run src/app/api/_engine.test.ts && npm run typecheck && npm run lint`

Expected: PASS.

```bash
git add services/cockpit/src/app/api/_engine.ts services/cockpit/src/app/api/_engine.test.ts
git commit -m "cockpit: borner les appels moteur de review"
```

### Task 5: Exposer la queue via le BFF authentifié

**Files:**
- Create: `services/cockpit/src/app/api/review/_auth.ts`
- Create: `services/cockpit/src/app/api/review/queue/route.ts`
- Create: `services/cockpit/src/app/api/review/queue/route.test.ts`

- [ ] **Step 1: Écrire les tests rouges de la queue**

Tester : session absente `401`, rôle student/teacher/ingest `403`, paramètres
inconnus ou dupliqués `400`, bornes invalides `400`, collection hors scope
`403`, transfert valide du token signé et des paramètres, réponse moteur invalide
`503`, indisponibilité `503`, et absence de credential/token dans la réponse.

- [ ] **Step 2: Vérifier le rouge**

Run: `cd services/cockpit && npm test -- --run src/app/api/review/queue/route.test.ts`

Expected: FAIL car la route n'existe pas.

- [ ] **Step 3: Implémenter l'autorisation commune et la queue**

`_auth.ts` appelle `requireBffAuth` et ne conserve que `admin|reviewer`. La route
valide un objet `ReviewQueuePayload` généré, refuse doublons/clés inconnues,
contrôle `allowedCollections`, appelle l'endpoint allowlisté et valide
`ReviewQueueResponse` avant publication.

Le mapping de statuts est fermé : seul `200` accompagné d'une réponse conforme
est publié ; tout `4xx`, `5xx`, timeout, payload non JSON ou réponse non conforme
devient `503 {error: 'review_unavailable'}`. Les détails moteur ne sont jamais
relayés.

- [ ] **Step 4: Vérifier et commit**

Run: `cd services/cockpit && npm test -- --run src/app/api/review/queue/route.test.ts src/server/bff-auth.test.ts && npm run typecheck && npm run lint`

Expected: PASS.

```bash
git add services/cockpit/src/app/api/review
git commit -m "cockpit: exposer la queue de review authentifiée"
```

### Task 6: Exposer les décisions via le BFF authentifié

**Files:**
- Create: `services/cockpit/src/app/api/review/decide/route.ts`
- Create: `services/cockpit/src/app/api/review/decide/route.test.ts`

- [ ] **Step 1: Écrire les tests rouges de décision**

Tester : `401`, rôles interdits `403`, JSON invalide `400`, `reason` refusé
`400`, tenant navigateur refusé `400`, collection hors scope `403`, tenant signé
ajouté au corps moteur, `404` moteur rendu générique sans identifiant, réponse
200 invalide `503`, panne `503` et aucun secret dans les réponses.

- [ ] **Step 2: Vérifier le rouge**

Run: `cd services/cockpit && npm test -- --run src/app/api/review/decide/route.test.ts`

Expected: FAIL car la route n'existe pas.

- [ ] **Step 3: Implémenter la décision minimale**

Valider `ReviewDecisionPayload`, construire un `ReviewDecisionRequest` avec
`tenant: authContext.identity.tenant`, revalider le modèle moteur, puis valider
`ReviewDecisionResponse`. Ne jamais journaliser le payload, le token ou la
cible. Mapper uniquement `404` vers une erreur générique ; les divergences
amont deviennent `503`. Plus précisément : `200` conforme est publié, `404`
devient `404 {error: 'review_target_unavailable'}`, et tout autre statut,
timeout, payload non JSON ou réponse invalide devient
`503 {error: 'review_unavailable'}`.

- [ ] **Step 4: Vérifier le vert du BFF complet et commit**

Run: `cd services/cockpit && npm test -- --run src/app/api/review src/app/api/_engine.test.ts src/server/bff-auth.test.ts && npm run typecheck && npm run lint`

Expected: PASS.

```bash
git add services/cockpit/src/app/api/review/decide
git commit -m "cockpit: exposer les décisions de review authentifiées"
```

## Chunk 3 — Reprise Redis, documentation et preuves

### Task 7: Rendre la connexion Redis récupérable sans fail-open

**Files:**
- Modify: `services/cockpit/src/server/revocation-store.ts`
- Modify: `services/cockpit/src/server/revocation-store.redis.test.ts`

- [ ] **Step 1: Écrire les tests rouges concurrents**

Avec des promesses différées de `connect()` :

1. lancer deux appels simultanés, rejeter la tentative partagée, vérifier deux
   rejets et un seul `createClient` ;
2. appeler de nouveau, résoudre la seconde tentative, vérifier la réussite et
   exactement deux clients ;
3. lancer une tentative A, appeler `resetSessionStoreForTests`, lancer/résoudre
   B, rejeter A tardivement, puis vérifier que l'appel suivant réutilise B et
   qu'aucun troisième client n'est créé.

- [ ] **Step 2: Vérifier le rouge**

Run: `cd services/cockpit && npm test -- --run src/server/revocation-store.redis.test.ts`

Expected: FAIL car la promesse rejetée reste cachée ou efface une tentative plus récente.

- [ ] **Step 3: Implémenter l'éviction conditionnelle**

Créer une promesse locale `attempt`, envelopper son rejet, et remettre
`storePromise` à `null` seulement si `storePromise` référence encore cette
promesse enveloppée. Propager l'erreur originale ; ne jamais basculer en mémoire.

- [ ] **Step 4: Vérifier le vert et commit**

Run: `cd services/cockpit && npm test -- --run src/server/revocation-store.redis.test.ts src/server/revocation-store.test.ts src/server/bff-auth.test.ts && npm run typecheck && npm run lint`

Expected: PASS.

```bash
git add services/cockpit/src/server/revocation-store.ts \
  services/cockpit/src/server/revocation-store.redis.test.ts
git commit -m "cockpit: réessayer Redis après une connexion rejetée"
```

### Task 8: Aligner runbook, checklist et rapport de lot

**Files:**
- Modify: `docs/runbooks/go_live.md`
- Modify: `docs/checklists/production_go_live_checklist.md`
- Create: `docs/reports/lot_41r_review_runtime_hardening.md`

- [ ] **Step 1: Corriger le parcours opérateur**

Remplacer les exemples de token reviewer direct par les routes Cockpit BFF avec
session Auth.js active. Conserver des contrôles négatifs prouvant que le moteur
direct refuse un token humain et que student/teacher ne peuvent décider.

- [ ] **Step 2: Écrire le rapport sans sur-promesse**

Consigner base, branche, PR encore non fusionnée, trois causes racines, cycles
rouge/vert, versions, commandes et résultats. Le verdict reste
`GO_LIVE: NO_GO`; LOT41R ne vaut ni revue réelle du corpus ni autorisation LOT41A.

- [ ] **Step 3: Vérifier documentation et commit**

Run: `git diff --check && bash scripts/check-governance-locks.sh && rg -n 'GO_LIVE: NO_GO|0.5.0|/api/review' docs/reports/lot_41r_review_runtime_hardening.md docs/runbooks/go_live.md docs/checklists/production_go_live_checklist.md`

Expected: PASS et 18 verrous inchangés.

```bash
git add docs/runbooks/go_live.md docs/checklists/production_go_live_checklist.md \
  docs/reports/lot_41r_review_runtime_hardening.md
git commit -m "docs: consigner les preuves du LOT41R"
```

### Task 9: Vérification finale, revue indépendante et publication PR

**Files:**
- Modify: `docs/reports/lot_41r_review_runtime_hardening.md` uniquement si les résultats frais diffèrent des résultats préparés

- [ ] **Step 1: Lancer les suites complètes des composants touchés**

Run: `PYTHONPATH=packages/contracts/src services/rag-engine/.venv/bin/python -m pytest packages/contracts/tests -q`

Run: `cd services/rag-engine && make lint && make typecheck && make test`

Run: `cd services/cockpit && npm run contracts:check && npm test -- --run && npm run lint && npm run typecheck && npm run build`

Expected: tous les processus exit 0, aucun test en échec.

- [ ] **Step 2: Lancer la preuve runtime et la CI racine**

Run: `cd services/rag-engine && PYTHONPATH=src .venv/bin/pytest tests/test_ingestor_flattened_runtime.py -q`

Run: `bash scripts/ci-local.sh`

Expected: runtime aplati PASS et 13 contrôles racine PASS. Toute indisponibilité externe doit être consignée factuellement, jamais transformée en PASS.

- [ ] **Step 3: Vérifier le diff, les secrets et les verrous**

Run: `git diff main...HEAD --check && bash scripts/check-governance-locks.sh && git status --short --branch`

Run: `gitleaks git . --log-opts="main..HEAD" --redact --no-banner`

Run: `git diff --stat main...HEAD && git log --oneline main..HEAD`

Expected: diff propre, aucun secret détecté, 18 verrous identiques, uniquement
le périmètre LOT41R.

- [ ] **Step 4: Obtenir une revue indépendante du diff complet**

Le reviewer doit contrôler corrections P1, conformité AGENTS/ADR/SemVer,
sécurité BFF, absence de PII/secrets, concurrence Redis, tests et rapport. Toute
issue P0–P2 bloque la publication ; corriger en TDD puis refaire la revue.

- [ ] **Step 5: Mettre à jour le rapport avec les SHA exacts et commit**

Run: `git rev-parse HEAD && git status --short`

Le rapport consigne le SHA d'implémentation vérifié, c'est-à-dire `HEAD` avant
son propre commit documentaire ; il ne prétend pas contenir son propre SHA.
Après mise à jour par `apply_patch`, relancer `git diff --check`, les contrôles
documentaires et committer :

```bash
git add docs/reports/lot_41r_review_runtime_hardening.md
git commit -m "docs: finaliser les preuves du LOT41R"
```

Run après commit: `git status --short --branch && git log -2 --oneline`

Expected: branche propre et commit documentaire immédiatement au-dessus du SHA
d'implémentation consigné.

- [ ] **Step 6: Push et PR**

Run: `git push -u origin lot-41r-review-runtime-hardening`

Créer une PR non brouillon vers `main`, résumer les trois P1, les preuves
rouge/vert, le contrat 0.5.0 et `GO_LIVE: NO_GO`. Ne pas résoudre ni répondre aux
anciens threads #83/#84 sans autorisation explicite.
