# Lot 19 - Revue contradictoire post-PR #35

Date : 2026-06-29
Branche : `lot-19-audit-prod-collections`
PR : `https://github.com/cyranoaladin/RAG/pull/35`

## Execution de la revue

Le prompt `/review` a ete traite via les commentaires de revue recuperes sur GitHub avec :

```bash
gh pr view 35 --repo cyranoaladin/RAG --json number,title,headRefName,headRefOid,mergeable,reviewDecision,statusCheckRollup,comments,reviews
gh api repos/cyranoaladin/RAG/pulls/35/comments --paginate
```

Revue initiale observee sur le SHA `f71f64a1f94bb6e80cebcef0eb85d8f65c963ec2` :

- Codex Review : 2 commentaires P1.
- cubic : 6 issues signalees sur 23 fichiers. Les points cubic ci-dessous sont attribues a cubic.
- Faux positifs : aucun identifie.

## Tableau des points

| Point | Fichier | Gravite | Verdict | Action |
| ----- | ------- | ------: | ------- | ------ |
| Codex Review - config collections non chargeable dans image ingestor / layout `/app` | `services/rag-engine/src/ingestor/collection_config.py` | P1 | Vrai positif | Resolution robuste par `RAG_COLLECTIONS_CONFIG`, `RAG_LEGACY_COLLECTION_MAPPING`, `RAG_ENGINE_CONFIG_DIR`, fallback repo et fallback prod plat `../configs`; test layout prod simule. |
| Codex Review - fail-open admin si `RAG_ENV` absent en prod | `services/rag-engine/src/ingestor/admin_api.py` | P1 | Vrai positif | Defaut fail-closed, admin sans token autorise uniquement avec `RAG_ENV=development` + `ALLOW_UNAUTHENTICATED_ADMIN_DEV=true`; compose/env prod mis a jour. |
| cubic - grammaire `gouverne` -> `gouverné` | `services/rag-engine/README.md` | P3 | Vrai positif | Correction README historique. |
| cubic - `curl -k` dans les checks prod | `docs/reports/lot_19_prod_deployment_plan.md` | P2 | Vrai positif | Remplacement par `curl -sS --fail`; TLS non desactive dans le plan prod. |
| cubic - rollback incomplet des nouveaux modules/configs | `docs/reports/lot_19_prod_deployment_plan.md` | P1 | Vrai positif | Backup et rollback de `collection_config.py`, `retrieval_contract_adapter.py`, `rag_collections.yml`, `legacy_collection_mapping.yml`; suppression au rollback si absents du backup. |
| cubic - conversion page citation non numerique | `services/rag-engine/src/ingestor/retrieval_contract_adapter.py` | P2 | Vrai positif | Page numerique conservee/convertie, page invalide ignoree sans crash, citation sans champs requis retourne `None`. |
| cubic - section inconnue routée vers default | `services/rag-engine/src/ingestor/collection_config.py` | P2 | Vrai positif | Suppression du fallback silencieux; seules `None`, `""`, `default` et sections declarees sont acceptees. |
| cubic - fail-open admin si `RAG_ENV` absent | `services/rag-engine/src/ingestor/admin_api.py` | P1 | Vrai positif, doublon du point Codex | Meme correction que le point Codex. |
| Verification A - layout prod plat `/srv/nexusreussite/rag-ui/compose` | `collection_config.py`, `docker-compose.prod.yml`, plan prod | P1 | Vrai positif | Test prod plat sous `/tmp/rag-ui/compose`; montage `./configs:/app/configs:ro`; `RAG_ENGINE_CONFIG_DIR=/app/configs`. |
| Verification B - `RAG_ENV` par defaut | `admin_api.py`, templates env, README-PROD | P1 | Vrai positif | Test `RAG_ENV` absent + token absent => 503; dev explicite seulement avec opt-in. |
| Verification C - section inconnue | `collection_config.py` | P2 | Vrai positif | Test `section="hacked"` sans collection => `CollectionConfigError`. |
| Verification D - citations page invalide | `retrieval_contract_adapter.py` | P2 | Vrai positif | Tests `page=3`, `page="4"`, `page="p.4"`, `page="4-5"`, champs manquants. |
| Verification E - route `/rag/query` | `api.py`, `tests/test_rag_query_api.py` | P1 | Vrai positif | Validation collection avant Chroma; tests `anything`/`rag_divers` => 400 sans appel Chroma, `rag_web3` mappe et passe. |

## Corrections appliquees

- `collection_config.py` ne depend plus de `Path(__file__).resolve().parents[2]`.
- Les configs sont resolues par variable fichier, variable dossier, fallback repo, puis fallback prod plat en remontant vers `configs/`.
- `/admin/*` echoue ferme sans token, sauf opt-in local explicite.
- `/rag/query` resout la collection avant tout appel Chroma.
- Les citations ignorent une page non numerique au lieu de lever `ValueError`.
- Le plan prod couvre configs, rollback et checks TLS sans `-k`.
- `docker-compose.prod.yml` monte les configs dans `/app/configs`.
- Les fichiers `services/rag-engine/infra/.env.*` sont ignores par `.gitignore` et ne sont pas suivis ; les variables prod obligatoires sont donc documentees dans `README-PROD.md`, `docker-compose.prod.yml` et le plan de deploiement, sans ajouter de fichier `.env` au depot.

## Tests ajoutes

- `services/rag-engine/tests/test_rag_collections_config.py`
  - layout prod plat ;
  - `RAG_ENGINE_CONFIG_DIR` ;
  - section inconnue refusee.
- `services/rag-engine/tests/test_admin_security.py`
  - `RAG_ENV` absent + token absent => 503 ;
  - dev sans opt-in => 503 ;
  - dev avec opt-in explicite => accepte.
- `services/rag-engine/tests/test_retrieval_contract_adapter.py`
  - pages numeriques et invalides ;
  - citation incomplete.
- `services/rag-engine/tests/test_rag_query_api.py`
  - collections arbitraires refusees avant Chroma ;
  - `rag_divers` refuse ;
  - `rag_web3` accepte via mapping.

## Verification TDD

Tests rouges observes avant correction avec :

```bash
cd services/rag-engine
.venv/bin/python -m pytest tests/test_rag_collections_config.py tests/test_admin_security.py tests/test_retrieval_contract_adapter.py tests/test_rag_query_api.py -q
```

Echecs attendus observes : config prod plat introuvable, section inconnue non rejetee, admin `RAG_ENV` absent permissif, pages `p.4`/`4-5` en `ValueError`, `/rag/query` appelant Chroma avant validation.

Tests verts apres correction :

```text
30 passed
```

## Commandes executees

```bash
git diff --check

cd services/rag-engine
make lint
make typecheck
make test
.venv/bin/python -m pytest tests/test_rag_collections_config.py tests/test_admin_security.py tests/test_retrieval_contract_adapter.py tests/test_rag_query_api.py -q
python -m pytest tests/test_rag_collections_config.py -q
python -m pytest tests/test_admin_security.py -q
python -m pytest tests/test_retrieval_contract_adapter.py -q
python -m pytest tests/test_search_api.py -q
python -m pytest tests/test_rag_query_api.py -q

cd ../rag-pedago
make lint
make typecheck
make test

cd ../../packages/contracts
python -m pytest -q

cd ../..
bash scripts/check-governance-locks.sh
bash scripts/tests/test-governance-locks.sh
bash scripts/ci-local.sh
```

Resultats :

- `git diff --check` : OK.
- `rag-engine` : `make lint`, `make typecheck`, `make test` OK.
- Tests cibles `rag-engine` : OK (`test_rag_collections_config.py`, `test_admin_security.py`, `test_retrieval_contract_adapter.py`, `test_search_api.py`, `test_rag_query_api.py`).
- `rag-pedago` : lint OK, mypy OK, `1086 passed`.
- `packages/contracts` : `32 passed`.
- `check-governance-locks.sh` : OK, 18 verrous verifies.
- `test-governance-locks.sh` : OK, 16 assertions.
- `scripts/ci-local.sh` : OK, `7 passed, 0 failed`.

## GitHub Actions

Avant correction follow-up, les checks GitHub Actions etaient verts sur `f71f64a1f94bb6e80cebcef0eb85d8f65c963ec2`.

Apres correction follow-up, le SHA code `b068e82479f892f430edf9e5c2ee32b7169e2abb` a ete pousse puis verifie par GitHub Actions :

- Run GitHub Actions : `28352887825`.
- Resultat : SUCCESS.
- Jobs verifies : `governance locks guard`, `packages/contracts`, `services/rag-engine`, `services/rag-pedago`.
- Annotation non bloquante observee : avertissements GitHub Actions sur la deprecation Node.js 20 de certaines actions.

Un eventuel commit documentaire final doit lui aussi rester vert sur le HEAD de PR avant merge. Aucun merge et aucun deploiement prod n'ont ete effectues pendant cette revue.

## Statut final

`READY_TO_MERGE` sous reserve stricte que GitHub Actions reste vert sur le HEAD final de la PR.
