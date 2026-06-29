# Lot 19 - Derniere revue pre-merge PR #35

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
```

Resultats :

```text
git status --short: sortie vide
git branch --show-current: lot-19-audit-prod-collections
git rev-parse HEAD: 82e7cf103be1f0fdf5ec170d2aa20fafd615036f
git status --short --branch: ## lot-19-audit-prod-collections...origin/lot-19-audit-prod-collections
```

Derniers commits :

```text
82e7cf1 docs: finaliser suivi review lot 19
b068e82 rag-engine: fermer angles morts review lot 19
f71f64a ci: install contracts in rag-engine workflow
fe112bb rag-engine: cadrer collections et prod lot 19
8e3a611 rag-pedago: make real draft fixture portable
215c870 rag-pedago: run CLI tests with active interpreter
3691cce rag-pedago: satisfy lint on profile guard test
5fe2ffb rag-pedago: make lock Python 3.11 compatible
```

Etat PR initial lu par `gh pr view` :

```text
number=35
state=OPEN
isDraft=false
baseRefName=main
headRefName=lot-19-audit-prod-collections
headRefOid=82e7cf103be1f0fdf5ec170d2aa20fafd615036f
mergeable=MERGEABLE
reviewDecision=null
top_level_comments=0
reviews=3
inline_review_comments=10
statusCheckRollup=SUCCESS sur packages/contracts, governance locks guard, services/rag-pedago, services/rag-engine, GitGuardian, cubic
```

## Relance review et nouveaux retours

Le prompt demandait une relance `/review`. Aucun binaire ou endpoint CLI local `/review` n'est expose dans l'environnement Codex ; les retours disponibles ont donc ete recuperes depuis GitHub avec :

```bash
gh api repos/cyranoaladin/RAG/pulls/35/comments --paginate
gh pr view 35 --repo cyranoaladin/RAG --json reviews,comments,reviewDecision,statusCheckRollup
```

Un nouveau run cubic, identifie par cubic, etait present sur `b068e82479f892f430edf9e5c2ee32b7169e2abb` avec deux points non resolus/non obsoletes. Apres correction et push de `8d35dac028022e0b48ac5a99663ee5813a850a06`, cubic a signale un dernier P2 documentaire sur le plan de deploiement prod.

| Source | Fichier | Gravite | Commentaire | Verdict | Action |
| --- | --- | ---: | --- | --- | --- |
| cubic | `services/rag-engine/infra/docker-compose.prod.yml` | P0 | Le bind mount `./configs:/app/configs:ro` du compose versionne sous `infra/` pointe vers `infra/configs`, absent. | Vrai positif | Remplace par `../configs:/app/configs:ro`; test YAML Compose ajoute pour verifier que la source resolue est `services/rag-engine/configs`. |
| cubic | `services/rag-engine/src/ingestor/collection_config.py` | P2 | Les overrides explicites de config retombent sur les fallbacks si le chemin configure est absent. | Vrai positif | Fail-closed pour `RAG_COLLECTIONS_CONFIG`, `RAG_LEGACY_COLLECTION_MAPPING` et `RAG_ENGINE_CONFIG_DIR`; tests rouges puis verts ajoutes. |
| cubic | `docs/reports/lot_19_prod_deployment_plan.md` | P2 | Le plan prod validait source et cible du bind mount configs avec des `grep` independants. | Vrai positif | Remplace par une validation structuree de `docker compose config --format json` : service `ingestor`, source, target `/app/configs` et `read_only=true` verifies sur la meme entree de volume. |
| Revue locale | `services/rag-engine/README-PROD.md` | P2 | Des commandes de checks prod contenaient encore une option curl desactivant la validation TLS. | Vrai positif | Option retiree des checks Nginx/API/UI ; le plan prod restait deja sans cette option. |

Statut review apres correction locale du dernier P2 : `CHANGES_REQUIRED` jusqu'au push et a la verification GitHub Actions/cubic du nouveau HEAD.

## Review threads

Commande GraphQL executee selon la demande. Etat initial avant push des corrections :

```text
reviewDecision=null
totalThreads=10
blockingOpenThreads=2
openOutdatedThreads=2
```

Les 2 threads bloquants ouverts correspondent aux deux nouveaux points cubic ci-dessus. Les 2 threads ouverts mais obsoletes correspondent aux anciens commentaires Codex deja corriges par `b068e82`.

Etat apres push de `8d35dac028022e0b48ac5a99663ee5813a850a06` et avant correction du dernier P2 :

```text
reviewDecision=null
totalThreads=11
blockingOpenThreads=1
openOutdatedThreads=2
```

Le thread bloquant correspond au point cubic sur la validation structuree du bind mount Compose.

## Revue manuelle du diff final local

Surfaces inspectees :

- `services/rag-engine/src/ingestor/collection_config.py`
- `services/rag-engine/src/ingestor/admin_api.py`
- `services/rag-engine/src/ingestor/api.py`
- `services/rag-engine/src/ingestor/retrieval_contract_adapter.py`
- `services/rag-engine/src/ui/app_v2.py`
- `services/rag-engine/infra/docker-compose.prod.yml`
- `docs/reports/lot_19_review_followup.md`
- `docs/reports/lot_19_prod_deployment_plan.md`
- `services/rag-engine/README-PROD.md`

Constats :

- `RAG_COLLECTIONS_CONFIG`, `RAG_LEGACY_COLLECTION_MAPPING` et `RAG_ENGINE_CONFIG_DIR` fonctionnent et echouent fermes si le chemin explicite manque.
- Le fallback repo et le layout prod plat sont couverts par tests.
- Le plan prod copie les YAML vers `/srv/nexusreussite/rag-ui/compose/configs` et verifie le rendu Compose vers `/app/configs`.
- Le plan prod valide maintenant le volume configs dans le rendu Compose JSON sur le service `ingestor`, avec source, cible et lecture seule verifiees sur la meme entree.
- Admin fail-closed si token absent et `RAG_ENV` absent.
- Dev sans token autorise seulement avec `RAG_ENV=development` et `ALLOW_UNAUTHENTICATED_ADMIN_DEV=true`.
- `/search` et `/rag/query` refusent une collection arbitraire ; `/rag/query` refuse `rag_divers` avant appel Chroma et accepte `rag_web3` via mapping.
- `/stats/{collection}` passe par `resolve_collection_name`; une collection inconnue est refusee avant acces Chroma.
- Aucun deploiement prod n'est annonce comme execute ; le plan reste `Statut : plan seulement, non execute`.

## Verification locale

Tests rouges observes avant correction :

```text
tests/test_rag_collections_config.py:
- env file override absent: DID NOT RAISE
- legacy mapping override absent: DID NOT RAISE
- config dir absent: DID NOT RAISE
- compose mount attendu ../configs mais obtenu ./configs
```

Corrections appliquees puis test cible vert :

```bash
cd services/rag-engine
python -m pytest tests/test_rag_collections_config.py -q
```

Resultat : `15 passed`.

Commandes obligatoires executees :

```bash
git diff --check

cd services/rag-engine
make lint
make typecheck
make test
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

- Premiere execution des tests cibles `rag-engine` sans venv : echec d'environnement, `python` systeme sans `nexus_contracts` ni `chromadb`.
- Meme bloc relance avec `.venv` activee : OK.
- `services/rag-engine`: lint OK, mypy OK, `make test` OK, tests cibles OK.
- `services/rag-pedago`: lint OK, mypy OK, `1086 passed`.
- `packages/contracts`: `32 passed`.
- `check-governance-locks.sh`: OK, 18 verrous verifies.
- `test-governance-locks.sh`: OK, 16 assertions.
- `scripts/ci-local.sh`: OK, `7 passed, 0 failed`.

Apres correction du dernier P2 documentaire cubic :

- `git diff --check` : OK.
- scan secret diff : aucune occurrence evidente.
- scan de l'option TLS insecure dans les documents prod/review : aucune occurrence.
- bloc local obligatoire relance : OK.
- `services/rag-pedago`: `1086 passed`.
- `packages/contracts`: `32 passed`.
- `scripts/ci-local.sh`: OK, `7 passed, 0 failed`.

## Secrets, PII et prod

Verification diff :

```bash
git diff origin/main -- . ':(exclude)services/rag-engine/infra/.env*' | rg -n "(BEGIN [A-Z ]*PRIVATE KEY|password\\s*=|passwd\\s*=|api[_-]?key\\s*=|secret\\s*=|sk-[A-Za-z0-9]|AIza[0-9A-Za-z_-]{20,})" || true
```

Resultat : aucune occurrence de secret evidente dans le diff inspecte.

`PROD_DEPLOYMENT=NOT_EXECUTED`.

## GitHub Actions

Avant correction finale, le HEAD GitHub `82e7cf103be1f0fdf5ec170d2aa20fafd615036f` etait vert sur le run `28353176968`.

Apres corrections `8d35dac028022e0b48ac5a99663ee5813a850a06`, le run GitHub Actions `28364961660` etait vert sur le meme SHA :

- `packages/contracts`: SUCCESS.
- `governance locks guard`: SUCCESS.
- `services/rag-pedago`: SUCCESS.
- `services/rag-engine`: SUCCESS.
- `GitGuardian Security Checks`: SUCCESS.
- `cubic - AI code reviewer`: SUCCESS, avec le P2 documentaire consigne ci-dessus.

La correction du dernier P2 documentaire doit etre poussee puis revisee par GitHub Actions, GitGuardian, cubic et les review threads avant tout merge.

## Decision pre-merge

Statut courant : `DO_NOT_MERGE`.

Raisons :

- correction locale du dernier P2 cubic non encore poussee au moment de cette redaction ;
- GitHub Actions non encore relancees sur le futur HEAD ;
- le thread cubic restera visible comme ouvert/non obsolete tant que le nouveau HEAD n'est pas pousse.

Conditions attendues apres push :

```text
READY_TO_MERGE_CONFIRMED
HEAD_SHA=<a renseigner apres push>
GITHUB_ACTIONS=SUCCESS_ON_HEAD
REVIEW_THREADS=NO_BLOCKING_THREADS
PROD_DEPLOYMENT=NOT_EXECUTED
```
