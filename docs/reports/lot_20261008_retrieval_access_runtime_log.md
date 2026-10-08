# Lot 2026-10-08 — journal d'accès du retrieval en runtime

Producteur des vérifications : agent Codex, 8 octobre 2026. Base de la PR : `origin/main` `064bab346ebe7bcdd6e1943f3a4c83d9b2c0eda1`. Le code corrigé est au commit exact `38c81c5e6f187517f6175a395e4620dad223ec5b`, arbre `d439b42edbf10f032def752276eff0a659c6809d`, dans un worktree et un venv isolés. Les tests ont été rejoués sur le descendant documentaire, sans changement du code. Les preuves locales portent sur ce code, pas sur une image finale déployée.

**LIVE, instantané staging à 20:56 UTC, source :** requête HTTP `POST /search/v2` avec `{}` sur `http://127.0.0.1:18003` (réponse 401), `GET /metrics`, `docker logs --since 2m nexus-staging-ingestor-1`, `docker ps -a` et connexion à `http://127.0.0.1:19191/api/v1/rules` sur l'hôte `nexus-prod` dans le projet Compose `nexus-staging`. Le checkout staging était alors `4b62104d9887eb418b6c50b39cde9ddb6d55b884`, avant cette PR ; `docker inspect` a confirmé le même conteneur, créé à 20:51 UTC, image API `sha256:00398ba7773e95fddbed7b088b083759182af70d2836d60d6056b258eefd588c`. Les métriques observées après la requête : `retrieval_requests_total=7`, `retrieval_errors_total{cause="authentication"}=1`, `retrieval_empty_results_total=5`, `retrieval_scope_refusals_total=0`, `retrieval_http_503_total=0`. Les logs Uvicorn contenaient la requête HTTP, mais **zéro** événement `retrieval_access`. Aucun conteneur Prometheus staging ne tournait et le port 19191 refusait la connexion. Ces valeurs sont historiques ; elles ne prouvent pas l'état de staging au SHA final.

**STATIC, code du commit testé :** Uvicorn ne configure pas le logger racine à `INFO`, ce qui éliminait les événements du logger dédié. Le correctif donne à ce logger une sortie JSON sur stdout lorsque aucun handler racine ne collecte `INFO`. Il évite aussi une seconde émission si un handler racine la collecte déjà. Le contenu journalisé, le retrieval, ses filtres et son classement restent inchangés. Les familles `retrieval_*` et les quatre règles Prometheus préexistaient à ce correctif.

**LOCAL TEST, code `38c81c5e6f187517f6175a395e4620dad223ec5b`, 22:01 UTC :** le test sous configuration Uvicorn échouait avant le correctif avec zéro ligne pour deux requêtes. Le cas avec handler racine `INFO` échouait avant la seconde correction avec quatre lignes pour deux requêtes. Après Red→Green, commandes exactes depuis le worktree :

```sh
cd services/rag-engine
PYTHONPATH=src ../../.venv/bin/python -m pytest -q -o addopts='' tests/test_retrieval_access_runtime_logging.py tests/test_retrieval_operational_metrics.py tests/test_search_v2_metadata_and_observability.py tests/test_v2_runtime_surface.py
# 90 passed, 1 warning, exit 0
cd ../..
.venv/bin/python -m ruff check services/rag-engine/src/ingestor/retrieval_observability.py services/rag-engine/tests/test_retrieval_access_runtime_logging.py
# All checks passed!, exit 0
git diff --check origin/main...HEAD
# aucune sortie, exit 0
docker run --rm --read-only --entrypoint=/bin/promtool -v "$PWD/services/rag-engine/infra/prometheus/prometheus.v2.yml:/etc/prometheus/prometheus.yml:ro" -v "$PWD/services/rag-engine/infra/prometheus/rules:/etc/prometheus/rules:ro" prom/prometheus:v2.54.1@sha256:f6639335d34a77d9d9db382b92eeb7fc00934be8eae81dbc03b31cfe90411a94 check config /etc/prometheus/prometheus.yml
# configuration valide, un fichier de règles et quatre règles, exit 0
```

**RUNTIME FINAL, non vérifié :** après fusion, reconstruire l'image API au SHA courant, constater une seule ligne `retrieval_access` pour chaque requête et lancer Prometheus staging. Vérifier ensuite `/api/v1/rules` et `/api/v1/targets` avant `OBSERVABILITY_PASS=true`. Cette PR ne modifie ni staging ni production et ne constitue pas une preuve d'alertes effectivement chargées.
