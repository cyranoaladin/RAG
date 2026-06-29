# Lot 19 - Derniere passe anti-angle mort PR #35

Date : 2026-06-29
PR : https://github.com/cyranoaladin/RAG/pull/35
Branche : `lot-19-audit-prod-collections`
Prod : `PROD_DEPLOYMENT=NOT_EXECUTED`

## Etat initial exact

Commandes executees :

```bash
git status --short
git branch --show-current
git log --oneline -8
git rev-parse HEAD
git fetch origin
git status --short --branch
gh pr view 35 --repo cyranoaladin/RAG --json number,state,isDraft,mergeable,reviewDecision,headRefName,headRefOid,baseRefName,statusCheckRollup,reviews,comments
```

Resultats avant corrections locales :

```text
git status --short: sortie vide
git branch --show-current: lot-19-audit-prod-collections
git rev-parse HEAD: 9a41736eea480ed4d75e5298f0a5ac515b639112
git status --short --branch: ## lot-19-audit-prod-collections...origin/lot-19-audit-prod-collections
```

Derniers commits :

```text
9a41736 docs: renforcer gate premerge lot 19
8d35dac rag-engine: fermer derniers retours premerge lot 19
82e7cf1 docs: finaliser suivi review lot 19
b068e82 rag-engine: fermer angles morts review lot 19
f71f64a ci: install contracts in rag-engine workflow
fe112bb rag-engine: cadrer collections et prod lot 19
8e3a611 rag-pedago: make real draft fixture portable
215c870 rag-pedago: run CLI tests with active interpreter
```

Etat PR lu par `gh pr view` au demarrage de cette passe :

```text
number=35
state=OPEN
isDraft=false
baseRefName=main
headRefName=lot-19-audit-prod-collections
headRefOid=9a41736eea480ed4d75e5298f0a5ac515b639112
mergeable=MERGEABLE
reviewDecision=null
top_level_comments=2
reviews=4
statusCheckRollup=SUCCESS sur packages/contracts, governance locks guard, services/rag-pedago, services/rag-engine, GitGuardian, cubic
run GitHub Actions: 28366191439
```

La PR n'avait pas bouge au moment de l'audit local. Les corrections ci-dessous produisent un nouveau HEAD apres commit/push ; la decision finale exige donc une nouvelle verification GitHub Actions sur ce nouveau HEAD.

## Retours Codex et cubic

| Source | Point | Gravite | Statut actuel | Preuve code/test/doc | Decision |
| --- | --- | ---: | --- | --- | --- |
| Codex Review initial | Config collection introuvable dans l'image ingestor | P1 | Traite | `collection_config.py` resout `RAG_COLLECTIONS_CONFIG`, `RAG_LEGACY_COLLECTION_MAPPING`, `RAG_ENGINE_CONFIG_DIR`, fallback repo et fallback prod plat ; tests `test_collection_config_loads_from_flat_prod_layout`, `test_repo_fallback_without_env`. | Vrai positif corrige. |
| Codex Review initial | Admin fail-open si `RAG_ENV` absent | P1 | Traite avant cette passe | Tests `test_admin_security.py`; README-PROD et plan prod exigent `RAG_ENV=production` et token. | Vrai positif corrige. |
| cubic initial | Grammaire gouverne/gouverne | P3 | Traite avant cette passe | Documentation Lot 19 corrigee. | Vrai positif corrige. |
| cubic initial | `curl -k` dans checks obligatoires | P2 | Traite avant cette passe | README-PROD et plan prod utilisent `curl -sS --fail`, sans `-k`. | Vrai positif corrige. |
| cubic initial | Rollback incomplet | P2 | Traite avant cette passe | `lot_19_prod_deployment_plan.md` sauvegarde/restaure `collection_config.py`, `retrieval_contract_adapter.py` et les YAML configs. | Vrai positif corrige. |
| cubic initial | Citation avec page non numerique | P2 | Traite avant cette passe | `retrieval_contract_adapter.py` ignore les pages invalides ; tests adapter dedies. | Vrai positif corrige. |
| cubic initial | Section inconnue routee vers default | P1 | Traite avant cette passe | `resolve_collection(section="hacked")` echoue ; tests search et config. | Vrai positif corrige. |
| cubic initial | Admin fail-open | P1 | Traite avant cette passe | Voir tests admin. | Vrai positif corrige. |
| cubic second passage | P0 : `./configs:/app/configs:ro` depuis `infra/docker-compose.prod.yml` pointe vers `infra/configs`, absent | P0 | Traite et renforce dans cette passe | Compose versionne utilise `${RAG_CONFIGS_HOST_DIR:-../configs}:/app/configs:ro`; `test_prod_compose_config_mount.py` verifie structurellement source, target et read-only. | Vrai positif corrige. |
| cubic second passage | P2 : overrides explicites de config doivent echouer fermes si absents | P2 | Traite et renforce dans cette passe | `CollectionConfigLoadError`; tests `test_explicit_collection_config_file_env_fails_closed_when_missing`, `test_explicit_legacy_mapping_file_env_fails_closed_when_missing`, `test_explicit_config_dir_env_fails_closed_when_files_are_missing`, `test_explicit_config_dir_env_missing_mapping_fails_closed`. | Vrai positif corrige. |
| cubic troisieme passage | P2 : validation du bind mount Compose trop faible avec `grep` independants | P2 | Traite dans cette passe | Plan prod remplace la validation faible par `docker compose config --format json` et verification Python d'un meme objet volume `ingestor` avec source, target et `read_only=true`. | Vrai positif corrige. |
| Revue locale anti-angle mort | Config serveur absente retournee en 400 | P1 | Traite dans cette passe | `CollectionRoutingError` -> 400 ; `CollectionConfigLoadError` -> 503 generique ; tests `test_search_config_file_missing_is_server_error`, `test_rag_query_config_dir_missing_mapping_is_server_error`. | Vrai positif corrige. |

## Cohérence des layouts configs

Layout repo versionne :

- compose depuis `services/rag-engine/infra` ;
- bind source attendu : `services/rag-engine/configs` ;
- syntaxe compose : `${RAG_CONFIGS_HOST_DIR:-../configs}:/app/configs:ro` ;
- defaut effectif : `../configs`, resolu depuis `infra/` vers `services/rag-engine/configs`.

Layout prod historique :

- compose depuis `/srv/nexusreussite/rag-ui/compose` ;
- bind source attendu : `/srv/nexusreussite/rag-ui/compose/configs` ;
- syntaxe attendue dans le compose prod historique via `.env` : `RAG_CONFIGS_HOST_DIR=./configs`, rendue comme `/srv/nexusreussite/rag-ui/compose/configs`.

Decision :

- Le fichier versionne `services/rag-engine/infra/docker-compose.prod.yml` peut rester utilisable depuis le repo sans variable supplementaire.
- Si ce fichier est copie tel quel dans `/srv/nexusreussite/rag-ui/compose`, il ne doit pas etre utilise sans `RAG_CONFIGS_HOST_DIR=./configs`.
- Le plan prod exige maintenant `RAG_CONFIGS_HOST_DIR=./configs` dans le layout historique plat et valide le rendu Compose JSON sur le service `ingestor`.

Preuves :

- `services/rag-engine/infra/docker-compose.prod.yml`
- `services/rag-engine/tests/test_prod_compose_config_mount.py`
- `docs/reports/lot_19_prod_deployment_plan.md`
- `services/rag-engine/README-PROD.md`

## Revue manuelle des routes et erreurs

Constats apres correction :

- `/search` refuse `collection=anything` avec 400.
- `/search` refuse `section=hacked` avec 400.
- `/rag/query` refuse `collection=anything` avec 400 avant acces Chroma.
- `/rag/query` refuse `rag_divers`/quarantine avec 400 avant acces Chroma.
- `/rag/query` accepte `rag_web3` via mapping legacy autorise.
- Mauvaise configuration serveur (`RAG_COLLECTIONS_CONFIG` absent ou `RAG_ENGINE_CONFIG_DIR` incomplet) retourne 503 generique, sans chemin prod dans la reponse HTTP publique.
- Les details de chemin restent uniquement dans les logs serveur.

## Review threads GitHub

Etat connu au demarrage de cette passe :

```text
reviewDecision=null
threads bloquants non obsoletes connus: 0
anciens threads Codex ouverts mais obsoletes: acceptes comme non bloquants
```

Une nouvelle verification GraphQL doit etre executee apres push du nouveau HEAD. Le statut `READY_TO_MERGE_CONFIRMED` est interdit tant qu'un thread non obsolete reste ouvert.

## Verifications locales

Tests rouges observes pendant cette passe avant correction :

```text
tests/test_prod_compose_config_mount.py:
- le compose versionne etait encore en source fixe `../configs`, alors que la strategie finale exige un override hote explicite possible.

tests/test_search_api.py:
- config file manquant par env explicite: 400 au lieu de 503.

tests/test_rag_query_api.py:
- config dir explicite incomplet: 400 au lieu de 503.
```

Tests cibles apres correction :

```bash
cd services/rag-engine
source .venv/bin/activate
python -m pytest tests/test_prod_compose_config_mount.py tests/test_rag_collections_config.py tests/test_search_api.py tests/test_rag_query_api.py -q
```

Resultat : `28 passed`.

Bloc obligatoire execute :

```bash
git diff --check

cd services/rag-engine
source .venv/bin/activate
make lint
make typecheck
make test
python -m pytest tests/test_rag_collections_config.py -q
python -m pytest tests/test_admin_security.py -q
python -m pytest tests/test_retrieval_contract_adapter.py -q
python -m pytest tests/test_search_api.py -q
python -m pytest tests/test_rag_query_api.py -q
python -m pytest tests/test_prod_compose_config_mount.py -q

cd ../rag-pedago
source .venv/bin/activate
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
- `services/rag-engine make lint` : OK.
- `services/rag-engine make typecheck` : OK.
- `services/rag-engine make test` : OK via le Makefile.
- `tests/test_rag_collections_config.py` : `16 passed`.
- `tests/test_admin_security.py` : `6 passed`.
- `tests/test_retrieval_contract_adapter.py` : `8 passed`.
- `tests/test_search_api.py` : `5 passed`.
- `tests/test_rag_query_api.py` : `6 passed`.
- `tests/test_prod_compose_config_mount.py` : `1 passed`.
- `services/rag-pedago make lint` : OK.
- `services/rag-pedago make typecheck` : OK.
- `services/rag-pedago make test` : `1086 passed`.
- `packages/contracts python -m pytest -q` : `32 passed`.
- `scripts/check-governance-locks.sh` : OK, 18 verrous verifies.
- `scripts/tests/test-governance-locks.sh` : OK, 16 assertions.
- `scripts/ci-local.sh` : OK, `7 passed, 0 failed`.

## GitHub Actions

Etat GitHub avant corrections locales :

```text
HEAD_SHA=9a41736eea480ed4d75e5298f0a5ac515b639112
RUN_ID=28366191439
GITHUB_ACTIONS=SUCCESS_ON_HEAD
jobs verts: packages/contracts, governance locks guard, services/rag-engine, services/rag-pedago
GitGuardian: SUCCESS
cubic: SUCCESS
```

Apres commit/push de cette passe, un nouveau HEAD doit etre verifie. Le rapport ne declare pas `READY_TO_MERGE_CONFIRMED` avant ce controle.

## Secrets, PII et prod

- Aucun `.env` actif, token, cle Google Drive, secret HMAC ou credential n'a ete affiche.
- Aucun deploiement production n'a ete execute.
- La documentation ne pretend pas qu'un deploiement prod a eu lieu.
- Les verrous de gouvernance n'ont pas ete modifies.

## Decision

Statut courant du rapport : `DO_NOT_MERGE`.

Raisons :

- les corrections locales de cette derniere passe doivent encore etre commitees et poussees ;
- GitHub Actions, GitGuardian, cubic et les review threads doivent etre reverifies sur le nouveau HEAD.

Conditions obligatoires avant merge :

```text
READY_TO_MERGE_CONFIRMED
HEAD_SHA=<nouveau headRefOid apres push>
GITHUB_ACTIONS=SUCCESS_ON_HEAD
REVIEW_THREADS=NO_BLOCKING_THREADS
PROD_DEPLOYMENT=NOT_EXECUTED
```
