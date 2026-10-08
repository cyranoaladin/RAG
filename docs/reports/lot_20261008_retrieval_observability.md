# Lot 2026-10-08 — observabilité du retrieval v2

Base de travail : `ee35544bce5af74d6186ea0ef61f6902a2258ffe`, arbre `e7f13396a17676ceba5550d039b50a6a2160838f`, checkout isolé depuis `origin/main`. Le lot ne modifie ni les filtres de portée, ni le classement, ni les limites de candidats, ni les seuils de retrieval.

Le runtime v2 expose désormais les compteurs `retrieval_requests_total`, `retrieval_errors_total{cause}`, `retrieval_empty_results_total`, `retrieval_scope_refusals_total`, `retrieval_http_503_total` et `retrieval_tie_overflow_total`, ainsi que les histogrammes de latence dense, lexical, reranker et recherche totale. Le compteur HTTP est posé une fois par `POST /search/v2`, y compris avant l'entrée dans la route. Les causes ont un vocabulaire fermé ; aucune requête, collection ou identité ne devient label. Le journal d'accès JSON distingue un résultat vide valide d'un refus, d'une panne de pool, d'un timeout, d'un overflow ANN et d'une erreur interne. L'exception externe demeure assainie.

Compose v2 monte le répertoire des règles Prometheus en lecture seule et charge quatre alertes retrieval (échec de collecte des métriques, 503, overflow ANN, P95 > 6 s). L'alerte critique `up == 0` qualifie la perte de collecte après deux minutes, sans prétendre à elle seule que l'API est indisponible ; l'absence de collecte rendrait également invisible un arrêt réel du service. Les noms des métriques retrieval sont volontairement stables et sans préfixe de namespace : les règles Prometheus et la demande d'exploitation emploient ces noms exacts ; le namespace configurable continue de s'appliquer aux autres métriques existantes. Le chemin du registre de release peut être choisi par `RAG_RELEASE_REGISTRY_PATH`, chemin **dans le conteneur** sous `/app/release`, avec le chemin historique par défaut. Le montage reste en lecture seule et `RAG_RELEASE_REGISTRY_SHA256` reste obligatoire ; la validation de digest du runtime demeure inchangée. Cela permet de sélectionner un registre scellé multi-release sans modifier ses octets ni l'image.

Vérifications effectuées le 8 octobre 2026 :

- Red→Green : tests d'instrumentation, de pré-route 503, de résultat vide, de diagnostic ANN et de montage Compose.
- Suite ciblée retrieval/runtime/Compose : **381 passed, 1 warning, exit 0** (`test_pg_pool.py`, `test_retrieval_operational_metrics.py`, `test_retrieval_hybrid_v2.py`, `test_retrieval_pg_v2.py`, `test_search_v2_metadata_and_observability.py`, `test_v2_runtime_surface.py`, test du registre Compose v2). Les tests distinguent l'expiration du budget et `QueryCanceled` d'une panne de pool, conservent le timeout d'inférence masqué dans la chaîne d'exceptions, rejettent une cause privée dans le journal, et vérifient un seul journal sur l'échec pré-route.
- `ruff check .` et `git diff --check` : verts.
- `docker compose -f infra/docker-compose.v2.yml config --no-interpolate --format json` : valide ; fichier de configuration et répertoire de règles montés en lecture seule.
- `promtool check config` dans `prom/prometheus:v2.54.1` : configuration valide, un fichier de règles chargé, quatre règles trouvées.
- Construction de `Dockerfile.ingestion-worker` puis import dans l'image réelle des deux entrypoints Worker B : `WORKER_ENTRYPOINTS_OK`. Le module hybride charge les métriques uniquement lorsqu'une recherche est exécutée ; le worker peut toujours importer sa constante de dimension sans dépendance à l'API.

Commande de la suite ciblée depuis `services/rag-engine` :

```sh
PYTHONPATH=src:../../packages/contracts/src:../../packages/release-chain/src:../../packages/pdf-page-policy/src python3 -m pytest -q -o addopts='' tests/test_pg_pool.py tests/test_retrieval_operational_metrics.py tests/test_retrieval_hybrid_v2.py tests/test_retrieval_pg_v2.py tests/test_search_v2_metadata_and_observability.py tests/test_v2_runtime_surface.py tests/test_prod_compose_config_mount.py
```

Limites : ce lot n'a pas été déployé en staging ni en production ; aucune métrique ou alerte de runtime final ne peut être déclarée effectivement active. La qualification staging, la charge C0 et la vérification de l'API Prometheus doivent utiliser l'image finale déployée. Les vérifications locales complètes bloquées par l'environnement et les erreurs préexistantes de typage figurent dans le [registre des dettes](lot_20261008_retrieval_observability_dettes.md).
