# LOT 1.2 — qualification des tests non exécutés de `rag-engine`

La suite `rag-engine` rapporte `3312 passed, 7 skipped`. Un skip n'est pas un
échec, mais il n'est pas non plus une preuve : ce document dit, pour chacun des
sept, s'il porte sur le comportement réellement servi en production et s'il doit
être exécuté avant le go-live.

## Sur quoi repose la colonne « pertinent en production »

Deux faits, lus dans les fichiers Compose du dépôt :

- les workers d'ingestion de production lancent
  `ingestor.ingestion_worker.multilevel_cli`
  (`services/rag-engine/infra/docker-compose.production-workers.yml:104`) ;
- le chemin Wave 0 (`ingestor.ingestion_worker.cli`) n'apparaît que dans
  `docker-compose.ingestion.yml`, dont l'en-tête déclare qu'il est
  « strictement opt-in », « jamais chargé seul » et « jamais implicitement par
  la commande normale du runtime v2 ».

Le plan de données multi-niveaux est donc le chemin de production ; Wave 0 est
un plan de contrôle antérieur, conservé et non servi.

## Les sept

| # | Test | Motif du skip | Ressource absente | Pertinent en production | À exécuter avant go-live |
|---|------|---------------|-------------------|-------------------------|--------------------------|
| 1 | `integration/test_h2c_governed_rehearsal.py:142` | « répétition réelle H2-C non demandée » | opt-in + entrées réelles | **oui** — répétition gouvernée du chemin servi | **oui** (E2E, §29 du mandat) |
| 2 | `integration/test_lot40_hybrid_pgvector.py:67` | DSN applicatif, admin, review et publisher requis | PostgreSQL éphémère + 4 rôles | **oui** — le retrieval hybride est la fonction servie | **oui** (C5/C6) |
| 3 | `integration/test_multilevel_real_ingestion.py:183` | « multilevel real ingestion not requested » | corpus réel + PostgreSQL | **oui** — multi-niveaux = worker de production | **oui** |
| 4 | `integration/test_multilevel_worker_cli_e2e.py:102` | « multilevel subprocess CLI acceptance not requested » | sous-processus + PostgreSQL | **oui** — c'est la commande que l'image lance | **oui** (C4) |
| 5 | `integration/test_real_model_ci_acceptance.py:52` | exige `RAG_EMBEDDING_MODEL_CACHE_DIR`, `RAG_EMBEDDING_MODEL_INVENTORY_SHA256`, `RAG_RERANKER_MODEL_CACHE_DIR`, `RAG_RERANKER_MODEL_INVENTORY_SHA256` | poids réels + empreintes d'inventaire | **oui** — ce sont les modèles servis | **oui** (§16 + C4) |
| 6 | `integration/test_wave0_french_pgvector.py:170` | « Wave 0 real inputs not requested » | PostgreSQL + entrées Wave 0 | non — chemin opt-in non servi | non |
| 7 | `integration/test_wave0_worker_cli_e2e.py:150` | « Wave 0 subprocess CLI acceptance not requested » | sous-processus + PostgreSQL | non — chemin opt-in non servi | non |

## Conséquence

Cinq de ces sept ne sont pas des skips légitimes à laisser en l'état : ce sont
des **gates ouverts**. Ils exigent une base PostgreSQL et les poids de modèles
réels, c'est-à-dire l'environnement éphémère isolé prévu pour C1–C6. Ils sont
donc rattachés à ces gates et non traités comme du bruit de suite.

Deux le sont : Wave 0 n'est pas le chemin servi, et rien dans la release
candidate n'en dépend. Ils restent exécutables à la demande.

Aucun de ces sept n'a été rendu vert en changeant sa condition de skip.


## Mise à jour après la CI distante de la PR #144 (2026-09-04)

Deux des cinq gates ouverts sont **fermés par la CI distante**, qui les exécute
avec une base PostgreSQL et les poids de modèles réels :

| # | Test local skippé | Couverture distante | Durée | Verdict |
|---|-------------------|---------------------|-------|---------|
| 2 | `test_lot40_hybrid_pgvector.py` | job `governance postgres` | 5m32 | **PASS** |
| 5 | `test_real_model_ci_acceptance.py` | job `real-model acceptance (E5 + reranker + pgvector)` | 4m30 | **PASS** |

Ils ne sont donc plus des gates à ouvrir dans un staging éphémère : ils sont
couverts, et le resteront tant que ces jobs existent en CI.

Trois gates restent ouverts, et relèvent de C1–C6 :

| # | Test | Ce qu'il exige |
|---|------|----------------|
| 1 | `test_h2c_governed_rehearsal.py` | répétition gouvernée réelle du chemin servi |
| 3 | `test_multilevel_real_ingestion.py` | ingestion multi-niveaux réelle, corpus + PostgreSQL |
| 4 | `test_multilevel_worker_cli_e2e.py` | acceptation du CLI que l'image lance, en sous-processus |

Les deux skips Wave 0 restent hors périmètre : ce chemin n'est pas servi.
