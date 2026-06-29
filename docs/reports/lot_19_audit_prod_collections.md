# Lot 19 - Audit prod, collections et convergence RAG

## 1. Resume executif

Lot 19 consolide l'etat du depot avec la production historique `rag-ui.nexusreussite.academy`. Le resultat distingue explicitement :

- la prod historique ChromaDB/Ollama/Streamlit ;
- le chemin Nexus gouverne `rag-pedago -> pgvector -> retrieval HMAC` ;
- la future convergence contractuelle via `RetrievalRequest -> RetrievalResponse`.

Corrections code du lot :

- ajout de `configs/rag_collections.yml` ;
- ajout de `configs/legacy_collection_mapping.yml` ;
- refus des collections arbitraires cote serveur ;
- `rag_divers` mappe vers `rag_nexus_quarantine` non retrievable ;
- `_admin_guard()` refuse l'absence de token en production ;
- `/admin/reindex` appelle `_admin_guard()` ;
- ajout de l'adaptateur `retrieval_contract_adapter.py`.

## 2. Etat initial

### Etat initial verifie

Commandes executees avant modification :

```bash
git status --short
git branch --show-current
git log --oneline -20
git diff --stat
find . -maxdepth 4 -type f | sort | sed -n '1,260p'
```

Resultats :

```text
$ git status --short
(aucune ligne)

$ git branch --show-current
main

$ git log --oneline -20
8e3a611 rag-pedago: make real draft fixture portable
215c870 rag-pedago: run CLI tests with active interpreter
3691cce rag-pedago: satisfy lint on profile guard test
5fe2ffb rag-pedago: make lock Python 3.11 compatible
3dee375 repo: sync main source of truth
a265fd9 feat(lot-18): agents de requête branchés sur l'API filtrée (ADR-0012)
5422623 Lot 17 — API retrieval lecture seule, filtrage non contournable (ADR-0011) (#34)
43690f7 feat(lot-16): migrate retrieval to rag-engine + cross-service governance (ADR-0010) (#33)
f300ed1 Lot 15.x — Référentiel exhaustif (#32)
00ff01b fix(lot-15.1): EXHAUSTIVE referentiel (76 programmes) + honest status
216297a feat(lot-15): exhaustive referentiel (39 programmes) + curated channel
9482ca3 Lot 14.x — pgvector + retrieval filtré (#31)
14c5f2e fix(lot-14.3): extract is_admitted + mutation-proof tests
7c7bf87 fix(lot-14.2): lock+DSN+manifest tests+BACKLOG debt
2fb3c04 fix(lot-14.1): coexistence filters + real review manifest
bc5dbe1 feat(lot-14 refonte): REAL pgvector indexation + filtered retrieval
e6a47db feat(lot-14): pgvector indexation + filtered retrieval (ADR-0008)
4b05e36 Lot 13.x — Embeddings production (#30)
f1bb92b fix(lot-13.2): e5 passage: prefix + idempotence by (sha,model,dim)
671b451 fix(lot-13.1): production model multilingual-e5-large (1024d, FR)

$ git diff --stat
(aucune ligne)
```

La commande `find` a ete executee avant modification. Les 260 premieres lignes etaient dominees par l'arborescence `.git/`, car la commande demandee n'excluait pas `.git`. Resultat utile consigne : le depot de travail etait propre, sur `main`, sans diff local.

## 3. Etat README et documentation

Le README racine decrivait deja les lots 0 a 18, `rag_chunks_pilote`, `/search`, le cockpit placeholder et l'interdiction de generation. Lot 19 ajoute :

- mention de la prod publique historique ;
- collections cibles `rag_nexus_*` ;
- mapping legacy Chroma ;
- quarantine non retrievable ;
- distinction claire entre docs historiques et chemin Nexus.

Les docs internes `rag-engine` sont conservees mais marquees comme historiques/prod actuelle.

## 4. Etat `rag-pedago`

`rag-pedago` reste le plan de controle :

- taxonomies ;
- chunks ;
- embeddings 1024 ;
- review manifest ;
- agents de requete `context_only`.

Verrou observe : `answer_generation_allowed: false`. Aucun verrou n'a ete active par Lot 19.

## 5. Etat `rag-engine` historique

Composants :

- `src/ingestor/api.py` : ingestor FastAPI, Chroma, `/ingest`, `/search`, `/collections`, `/stats`, Google Drive ;
- `src/ingestor/admin_api.py` : admin CRUD/catalogue ;
- `src/ui/app_v2.py` : UI Streamlit ;
- ChromaDB + Ollama.

Dette fermee :

- collections inconnues refusees ;
- admin prod sans token refuse ;
- `/admin/reindex` protege.

## 6. Etat `rag-engine` Nexus pgvector

Composants :

- `scripts/index_pgvector.py` indexe dans `rag_chunks_pilote` apres review manifest ;
- `scripts/retrieval_api.py` expose `/search` read-only ;
- profil HMAC impose `niveau` et `audience`.

Lot 19 ne migre pas physiquement vers `rag_chunks`. La config cible declare `rag_chunks` comme table non pilote et `rag_chunks_pilote` comme legacy pilote.

## 7. Etat de la prod `rag-ui`

SSH live indisponible : `Host key verification failed`.

Probes publics :

- `https://rag-ui.nexusreussite.academy/` : HTTP 200 ;
- `https://rag-api.nexusreussite.academy/health` : `{"status":"healthy"}` ;
- `https://rag-api.nexusreussite.academy/collections` sans token : HTTP 401.

Inventaire detaille : `docs/reports/lot_19_prod_inventory.md`.

## 8. Arborescence actuelle des collections

Historique attendu :

- `rag_education` ;
- `rag_francais_premiere` ;
- `rag_maths_premiere` ;
- `rag_web3` ;
- `rag_divers`.

Ces noms restent physiques/legacy en prod. Ils ne sont pas source de verite metier.

## 9. Arborescence cible des collections

Source : `services/rag-engine/configs/rag_collections.yml`.

- `rag_nexus_education` ;
- `rag_nexus_official` ;
- `rag_nexus_exams` ;
- `rag_nexus_owned` ;
- `rag_nexus_web3` ;
- `rag_nexus_quarantine`.

Metadonnees obligatoires : `domain`, `audience`, `niveau`, `voie`, `matiere`, `statut_enseignement`, `type_doc`, `source_kind`, `rights`, `review_status`, `source_label`, `source_uri`, `doc_id`, `chunk_id`, `chunk_sha256`.

## 10. Mapping legacy vers Nexus

Source : `services/rag-engine/configs/legacy_collection_mapping.yml`.

| Legacy Chroma | Nexus cible |
|---|---|
| `rag_education` | `rag_nexus_education` |
| `rag_francais_premiere` | `rag_nexus_education` |
| `rag_maths_premiere` | `rag_nexus_education` |
| `rag_web3` | `rag_nexus_web3` |
| `rag_divers` | `rag_nexus_quarantine` |

## 11. Dettes fermees

- Collection arbitraire via `/search` refusee.
- Quarantine non retrievable testee.
- Legacy mapping versionne.
- Admin prod sans token retourne 503.
- `/admin/reindex` ne contourne plus l'auth.
- Adaptateur contractuel ajoute.
- Docs historiques balisees.
- `packages/contracts` est testable depuis son dossier avec `python -m pytest -q`.

## 12. Dettes restantes

- Audit SSH live a refaire avec host key valide.
- Diff prod/repo non execute faute SSH.
- Collections Chroma live non listees.
- Migration physique vers `rag_chunks` non realisee.
- `POST /retrieve` non expose : cadre documente, adaptateur pret.
- Cockpit Next.js toujours placeholder.

## 13. Tests executes

Avant implementation, les nouveaux tests etaient rouges car config/adaptateur absents. Une verification explicite a aussi revele que `cd packages/contracts && python -m pytest -q` ne resolvait pas `src/` sans installation editable ; `packages/contracts/pyproject.toml` ajoute maintenant `pythonpath = ["src"]`.

Apres implementation, resultats verifies :

```text
services/rag-engine/tests/test_rag_collections_config.py
services/rag-engine/tests/test_admin_security.py
services/rag-engine/tests/test_retrieval_contract_adapter.py
=> 16 passed

services/rag-engine make test
=> exit 0, suite non-integration a 100%, warnings uniquement

services/rag-pedago make test
=> 1086 passed in 248.85s

packages/contracts python -m pytest -q
=> 32 passed
```

Warnings observees : `passlib`/`crypt`, `requests` dependency warning et `datetime.utcnow()` dans `python-jose`. Aucune ne provient des changements Lot 19 et aucune ne fait echouer les tests.

## 14. Commandes de CI

Commandes obligatoires executees :

```bash
bash scripts/ci-local.sh
cd services/rag-engine && make lint
cd services/rag-engine && make typecheck
cd services/rag-engine && make test
cd services/rag-pedago && make lint && make typecheck && make test
cd packages/contracts && python -m pytest -q
bash scripts/check-governance-locks.sh
bash scripts/tests/test-governance-locks.sh
```

Resultats :

```text
bash scripts/ci-local.sh
  PASS packages/contracts
  PASS services/rag-pedago
  PASS services/rag-engine
  PASS governance-locks
  PASS taxonomy-validation
  PASS governance-guard-tests
  PASS ci-failsafe-tests
  Total: 7 passed, 0 failed

services/rag-engine make lint
  All checks passed

services/rag-engine make typecheck
  Success: no issues found in 34 source files

services/rag-engine make test
  exit 0

services/rag-pedago make lint && make typecheck && make test
  All checks passed
  Success: no issues found in 67 source files
  1086 passed

packages/contracts python -m pytest -q
  32 passed

scripts/check-governance-locks.sh
  OK: all governance locks match baseline (18 keys verified)

scripts/tests/test-governance-locks.sh
  16 passed, 0 failed
```

## 15. Plan de mise a jour prod

Voir `docs/reports/lot_19_prod_deployment_plan.md`.

Lot 19 ne deploie pas : acces SSH non valide, pas de backup live, pas de diff prod/repo.

## 16. Statut final

`READY_FOR_CODE_REVIEW`

Raisons :

- CI locale finale verte sur l'etat final du diff ;
- prod non deployee, car SSH live non valide et preconditions de backup/diff/rollback non satisfaites ;
- dettes restantes documentees sans bloquer la revue de code.

## Matrice de coherence

| Surface | Source de verite | Etat reel | Ecart | Risque | Correction |
|---|---|---|---|---|---|
| README racine | Code + ADR 0001-0012 | Decrit lots 0-18 et pilote Nexus | Prod historique peu explicite | Confusion auditeur | Ajout Lot 19 collections/prod |
| AGENTS | `AGENTS.md` | Regles strictes multi-service | Divergence tenant vs ADR-0003 | Mauvais routage | Signalee, non modifiee |
| ROADMAP | `docs/ROADMAP.md` | Plan historique | Certaines phases anciennes | Priorisation floue | Rapport Lot 19 |
| BACKLOG | `docs/BACKLOG.md` | Dettes connues | Certaines dettes fermees depuis | Dette obsolete | Rapport Lot 19 |
| rag-pedago | Code + configs | Plan controle gouverne | Aucun | Regression gouvernance | Non modifie |
| rag-engine historique | `src/ingestor`, `src/ui` | Chroma/Ollama/Streamlit | Collection arbitraire | Fuite cross-domain | Mapping + refus inconnues |
| rag-engine Nexus pgvector | scripts + ADR | Pilote `rag_chunks_pilote` | Pas branche UI | Double realite | Docs transition |
| Streamlit prod UI | Snapshot + probes | UI publique HTTP 200 | Pas d'audit SSH | Derive prod | Inventaire + plan |
| admin API | `admin_api.py` | Guard permissif avant Lot 19 | Token absent silencieux | Admin expose | 503 prod + reindex auth |
| Chroma collections | Snapshot/code | Legacy probables | Non liste live | Mauvais melange | Mapping versionne |
| pgvector pilote | `index_pgvector.py` | `rag_chunks_pilote` | Table cible non pilote absente | Migration floue | Config `rag_chunks` cible |
| cockpit | `services/cockpit` | Placeholder | Non livre | Surpromesse | README clarifie |
| contracts | `packages/contracts` | Source Pydantic | `/search` historique divergent | Convergence incomplete | Adaptateur + doc `/retrieve` |
| prod server tree | Snapshot 20260613 | Backups, pycache, creds signales | Live indisponible | Drift prod | Inventory + preflight |
