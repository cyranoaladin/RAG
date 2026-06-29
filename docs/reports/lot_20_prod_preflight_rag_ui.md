# Lot 20 - Preflight production controle `rag-ui`

Statut : preparation operationnelle seulement.

Production cible : `https://rag-ui.nexusreussite.academy` et `https://rag-api.nexusreussite.academy`.

## Etat initial

Commandes executees avant creation de la branche Lot 20 :

```bash
git status --short
git branch --show-current
git log --oneline -10
git rev-parse HEAD
git fetch origin
git status --short --branch
```

Resultats :

```text
git status --short: sortie vide
git branch --show-current: main
git rev-parse HEAD: b483c2cfbb9f765f76a92f1f964eba83987698b2
git status --short --branch: ## main...origin/main
```

Derniers commits lus :

```text
b483c2c Merge pull request #35 from cyranoaladin/lot-19-audit-prod-collections
677fd0a docs: consigner decision premerge lot 19
76a4b79 docs: corriger total tests premerge lot 19
2c18e03 docs: eviter persistance secrets compose lot 19
f0e4f7a rag-engine: fermer derniers angles morts prod lot 19
9a41736 docs: renforcer gate premerge lot 19
8d35dac rag-engine: fermer derniers retours premerge lot 19
82e7cf1 docs: finaliser suivi review lot 19
b068e82 rag-engine: fermer angles morts review lot 19
f71f64a ci: install contracts in rag-engine workflow
```

Branche creee depuis `main` :

```text
lot-20-prod-preflight-rag-ui
```

Le SHA de depart est le merge commit Lot 19 attendu :

```text
b483c2cfbb9f765f76a92f1f964eba83987698b2
```

## Resume Lot 19

Lot 19 a livre :

- architecture de collections Nexus versionnee ;
- mapping legacy Chroma vers collections Nexus ;
- durcissement admin fail-closed ;
- validation structurelle du mount `/app/configs` ;
- adaptateur de convergence `RetrievalRequest` ;
- documentation dual-engine ;
- plan de deploiement et rollback ;
- aucun deploiement production.

## Objectifs Lot 20

- Ajouter un preflight local ou serveur, non destructif, qui valide le layout prod sans afficher de secret.
- Ajouter un dry-run de deploiement qui imprime uniquement des commandes `rsync -nci`.
- Formaliser un rollback runbook executable seulement apres confirmation humaine.
- Verifier les endpoints publics sans token et sans `curl -k`.
- Ouvrir une PR dediee, sans merger directement.

## Limites

- `PROD_DEPLOYMENT=NOT_EXECUTED`.
- Aucun `rsync` reel vers la production.
- Aucune migration Chroma.
- Aucune modification de `catalog.sqlite`.
- Aucun affichage de `.env`, token, credentials Google Drive, secret HMAC ou PII.
- Aucun rendu `docker compose config` persistant.

## Audit du plan Lot 19

| Element | Etat Lot 19 | Risque prod | Verification requise | Action Lot 20 |
| --- | --- | --- | --- | --- |
| mount `/app/configs` | Compose versionne avec `${RAG_CONFIGS_HOST_DIR:-../configs}:/app/configs:ro`. | Mauvaise source hote si le compose est copie dans le layout historique sans `.env`. | Verifier un meme objet volume `ingestor`, `type=bind`, source attendue, target `/app/configs`, read-only. | `prod_preflight_check.py` valide le rendu Compose en memoire. |
| `RAG_CONFIGS_HOST_DIR` | Requis en prod historique avec `./configs`. | Defaut repo `../configs` incorrect si utilise depuis `/srv/.../compose`. | Cle presente dans `.env`, rendu Compose source conforme. | Preflight exige la cle et compare la source rendue. |
| `RAG_ENGINE_CONFIG_DIR` | Doit valoir `/app/configs`. | Configs introuvables dans le conteneur. | Cle presente et valeur publique attendue. | Preflight refuse toute autre valeur. |
| `RAG_ENV` | Production doit etre explicite. | Admin fail-open si environnement ambigu. | `RAG_ENV=production`. | Preflight refuse toute autre valeur. |
| `ALLOW_UNAUTHENTICATED_ADMIN_DEV` | Doit etre `false` en prod. | Admin sans token. | Cle presente et valeur `false`. | Preflight refuse `true` ou absence. |
| `INGESTOR_API_TOKEN` | Token requis, valeur non affichable. | `/admin/*` ou ingestion inutilisable, ou configuration insecure. | Presence de `INGESTOR_API_TOKEN` au format 64 caracteres hexadecimaux, sans afficher la valeur. | Preflight refuse l'alias legacy seul et valide le format. |
| `admin_api` | `_admin_guard()` fail-closed en production. | Exposition admin si token absent. | Tests Lot 19 + preflight env. | Tests existants conserves, preflight ajoute. |
| `/admin/reindex` | Protege par `_admin_guard()`. | Contournement auth. | Tests Lot 19. | Pas de changement fonctionnel Lot 20. |
| `/search` | Refuse collection arbitraire et quarantine. | Elargissement cross-domain. | Tests `test_search_api.py`. | CI Lot 20 relance les tests. |
| `/rag/query` | Refuse collection arbitraire avant Chroma. | Acces Chroma non autorise. | Tests `test_rag_query_api.py`. | CI Lot 20 relance les tests. |
| `/collections` | Protege sans token en prod publique. | Exposition inventaire. | Check public attendu : 401 sans token. | Probe public sans token consigne ci-dessous. |
| `rag_divers` | Mappe vers `rag_nexus_quarantine`. | Recherche dans corpus non admis. | Mapping `rag_divers -> rag_nexus_quarantine`, quarantine non retrievable. | Preflight valide les YAML. |
| rollback | Plan Lot 19 couvre fichiers et configs. | Restauration incomplete si deploiement echoue. | Runbook separe avec backup horodate. | `lot_20_prod_rollback_runbook.md`. |
| absence `curl -k` | Corrigee en Lot 19. | Bypass TLS en procedure. | Checks publics sans `-k`. | Commandes Lot 20 utilisent `curl -sS --fail`. |
| absence rendu Compose persistant | Corrigee en Lot 19. | Fuite de secrets interpoles. | `subprocess.run(..., stdout=subprocess.PIPE)`, pas de fichier `/tmp`. | Preflight parse en memoire et tests anti-regression. |

## Outils ajoutes

### `services/rag-engine/scripts/prod_preflight_check.py`

Controle non destructif :

```bash
python services/rag-engine/scripts/prod_preflight_check.py \
  --compose-dir /srv/nexusreussite/rag-ui/compose \
  --expected-config-source /srv/nexusreussite/rag-ui/compose/configs \
  --expected-config-target /app/configs
```

Garanties :

- ne lit que les cles `.env`, jamais les valeurs sensibles dans les sorties ;
- verifie la presence d'un token admin sans l'afficher ;
- exige `INGESTOR_API_TOKEN` au format 64 caracteres hexadecimaux ;
- ne lit pas le contenu des credentials Google Drive ;
- analyse `docker compose config --format json` en memoire via `stdout=subprocess.PIPE` ;
- n'ecrit pas de rendu Compose dans `/tmp` ;
- valide le mount configs sur le service `ingestor` ;
- refuse les bindings de ports publics pour `ingestor` et `ui` ;
- valide `rag_nexus_quarantine` non retrievable et `rag_divers` vers quarantine.

### `services/rag-engine/scripts/prod_deploy_dry_run.sh`

Plan de synchronisation en lecture seule :

```bash
PROD_TARGET=/srv/nexusreussite/rag-ui/compose \
  services/rag-engine/scripts/prod_deploy_dry_run.sh \
  --confirm-readonly \
  --expected-sha <sha-main-valide>
```

Garanties :

- refuse une branche autre que `main` ;
- refuse un workspace sale ;
- refuse un SHA non valide explicitement ;
- refuse l'absence de `PROD_TARGET` ;
- imprime uniquement des commandes `rsync -nci` ;
- n'utilise pas `--delete` ;
- n'inclut pas `.env`, credentials, Chroma ou `catalog.sqlite`.
- couvre les fichiers applicatifs, les configs et les fichiers Compose versionnes `docker-compose.prod.yml` et `docker-compose.override.prod.yml`.

## Retours Cubic PR #36

| Source | Point | Gravite | Verdict | Action |
| --- | --- | ---: | --- | --- |
| Cubic | `prod_preflight_check.py` acceptait `INGEST_AUTH_TOKEN` comme alias suffisant. | P1 | Vrai positif. | `INGESTOR_API_TOKEN` est maintenant obligatoire et valide comme 64 caracteres hexadecimaux ; tests dedies ajoutes. |
| Cubic | `prod_preflight_check.py` ne rejetait pas les ports host publics. | P1 | Vrai positif. | Le rendu Compose est inspecte en memoire et les ports `ingestor`/`ui` doivent etre loopback-only ; tests dedies ajoutes. |
| Cubic | Le rollback n'attendait pas la readiness avant les post-checks. | P2 | Vrai positif. | Le runbook ajoute des boucles d'attente bornees avant les checks finaux. |
| Cubic | Le dry-run n'incluait pas les fichiers Compose de production. | P2 | Vrai positif. | Le dry-run couvre `infra/docker-compose.prod.yml` et `infra/docker-compose.override.prod.yml`. |
| Cubic | Le dry-run devrait simuler `rsync --delete`. | P2 | Faux positif pour Lot 20. | Rejete car la consigne Lot 20 impose explicitement de refuser `--delete` et de ne jamais l'inclure dans les commandes generees ; le test de refus est conserve. |
| Cubic | Le controle des ports publics ne couvrait que `ingestor` et `ui`. | P1 | Vrai positif. | Le preflight inspecte maintenant tout service Compose qui declare des ports ; test dedie ajoute. |

## Checks publics

Commandes executees :

```bash
curl -sS --fail -I https://rag-ui.nexusreussite.academy/
curl -sS --fail https://rag-api.nexusreussite.academy/health
curl -sS -i https://rag-api.nexusreussite.academy/collections | sed -n '1,20p'
```

Resultats observes le 29 juin 2026 :

```text
UI HEAD: HTTP/2 200
API /health: {"status":"healthy"}
API /collections sans token: HTTP/2 401, {"detail":"Unauthorized"}
```

Aucun token n'a ete utilise. Aucun endpoint `/admin/*` n'a ete appele.

## Tests et CI locale

Commandes executees :

```bash
git diff --check

cd services/rag-engine
make lint
make typecheck
make test
source .venv/bin/activate
python -m pytest tests/test_prod_preflight_check.py -q
python -m pytest tests/test_prod_deploy_dry_run.py -q
python -m pytest tests/test_prod_compose_config_mount.py -q
python -m pytest tests/test_rag_collections_config.py -q
python -m pytest tests/test_admin_security.py -q
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

```text
git diff --check: OK
services/rag-engine make lint: OK
services/rag-engine make typecheck: OK
services/rag-engine make test: OK
tests/test_prod_preflight_check.py: 15 passed
tests/test_prod_deploy_dry_run.py: 7 passed
tests/test_prod_compose_config_mount.py: 2 passed
tests/test_rag_collections_config.py: 16 passed
tests/test_admin_security.py: 6 passed
tests/test_search_api.py: 5 passed
tests/test_rag_query_api.py: 6 passed
services/rag-pedago make lint: OK
services/rag-pedago make typecheck: OK
services/rag-pedago make test: 1086 passed
packages/contracts python -m pytest -q: 32 passed
scripts/check-governance-locks.sh: OK, 18 locks verified
scripts/tests/test-governance-locks.sh: 16 passed, 0 failed
scripts/ci-local.sh: Total: 7 passed, 0 failed
```

## Statut prod

```text
PROD_DEPLOYMENT=NOT_EXECUTED
NO_CHROMA_MUTATION
NO_RSYNC_EXECUTED
NO_SECRET_EXPOSED
```
