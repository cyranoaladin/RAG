# Qualification de la cible de production — lecture seule

**Observation :** 2026-10-10, 13:32–13:35 UTC. **Source Git du rapport :** `origin/main` `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`. Ce rapport décrit la cible accessible à cet instant ; il ne constitue ni un test de cutover ni une preuve de readiness du candidat public.

## Méthode et identité

Contrôles non mutants par l'alias SSH existant `nexus-prod` : `hostname`, `docker ps/inspect`, `docker compose ls`, `ss`, `systemctl`, lectures SQL `SELECT` dans le conteneur RAG, API Prometheus et métadonnées du backup. Contrôles extérieurs : résolution DNS, `curl` HTTPS et certificat TLS. Aucune valeur de secret n'a été affichée ni consignée ; aucune écriture staging ou production n'a été faite.

L'alias atteint **`korrigo`** (`88.99.254.59`). `rag-api.nexusreussite.academy` et `rag-ui.nexusreussite.academy` résolvent vers cette adresse. Le certificat TLS de l'API est vérifié par `curl` (`ssl_verify_result=0`), émis par Let's Encrypt, valable du 2026-09-13 au 2026-12-12. Nginx, Docker et PostgreSQL hôte sont actifs ; ce dernier **n'est pas** la base RAG examinée. Docker est en version 29.2.1, Compose en version 5.1.0. L'hôte dispose de 12 CPU, de 64 211 MiB de RAM (54 377 MiB disponibles) et de 295 Gio libres sur 929 Gio pour `/` (67 % utilisés).

## Runtime public effectivement routé

Nginx route `rag-api` vers `127.0.0.1:18002`, le conteneur `rag_ingestor` de la pile Compose `infra`. Les conteneurs `rag_ingestor`, `rag_worker` et `rag_pgvector` partagent son réseau ; le `pgvector` de `nexus-staging` est sur un réseau distinct. Les identités d'image Docker observées sont :

| Service | Image ID SHA-256 |
| --- | --- |
| `rag_ingestor` | `35019c62f310cca9ec1076903c4dc2cb7773c7b096f0e412a3b5cd928530e340` |
| `rag_worker` | `6c7417689bc508f6d61fd4fab850f7cf37932333eb4c6ef0e8f7f2a39a9fbc70` |
| `rag_pgvector` | `00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc` |

`/opt/rag-v2/current` pointe vers la release du 2026-07-15 `rag-v2-main-27a4558-lot27p3-20260715T133534Z`. Ce répertoire n'est pas un checkout Git vérifiable. Le conteneur API monte depuis cet arbre les configurations et les identifiants en lecture seule, ainsi que le répertoire d'uploads en écriture. La présence des variables de secrets requises a été contrôlée par **noms seulement**.

La base examinée est exclusivement `ragdb` via `docker exec rag_pgvector psql` : PostgreSQL 16.14, extension `vector` 0.8.2. Elle contient les seules tables `rag_api_keys`, `rag_chunks`, `rag_eval_runs`, **0 ligne dans `rag_chunks`**, et aucune table de migration ou de registre de release observée. Le rôle runtime `raguser` est `LOGIN`, `SUPERUSER`, `CREATEDB`, `CREATEROLE`. Cette pile ne contient donc pas la release publique successeur ni ses onze collections.

Depuis l'extérieur : `GET /health` API = 200 ; `GET /search/v2` = 405 (route POST, sans preuve de recherche fonctionnelle) ; `GET /ingest` = 401 sous Basic Auth Nginx ; `GET /metrics` = 403 ; l'accueil `rag-ui` = 401. Le contrat étudiant et les citations n'ont pas été exercés.

## Sauvegarde et observabilité

Le run de sauvegarde `20261010T122008Z-b290cba8` rapporte `backup_complete=true` à 12:20:30 UTC et un digest offsite vérifié. Son snapshot de **`rag_pgvector/ragdb`**, à 12:20:24 UTC, possède un dump dont le SHA-256 recalculé égale la valeur inscrite dans `SHA256.json` : `30e2563d0ffd1bcaefa4b132cca9322a205d0a9816157e869511a4cb0b84a830`. Le même run rapporte `restore_verified=false` et `source_restore_verified=false` : une répétition de restauration du candidat final n'est pas démontrée.

Le Prometheus public (`127.0.0.1:19091`) voit **2/5 cibles `up`** (`ingestor`, `prometheus`) et **3/5 `down`** (`chroma` : DNS, `ollama` : HTTP 404, `ui` : format de réponse). Son API `/api/v1/rules` rapporte **0 groupe, 0 règle et 0 alerte**. Les métriques de retrieval final attendues n'ont pas été observées dans le `/metrics` de ce runtime historique.

## Verdict borné

`PROD_HOST_IDENTITY_VERIFIED=true` ; `PROD_TARGET_QUALIFIED_FOR_FINAL_CUTOVER=false` ; `PRODUCTION_READY=false` ; `RAG_PRODUCTION_DEPLOYED=false`.

**`BLOCKER_COUNT=5` — minimum confirmé pour le go-live final :** (1) release et corpus final absents de la base publique ; (2) privilèges superuser du rôle applicatif ; (3) restauration du backup candidat non prouvée ; (4) observabilité dégradée et aucune alerte chargée ; (5) runtime public historique avec montages de l'arbre release, sans preuve de déploiement immuable du candidat final. Ce décompte ne transforme pas les vérifications non effectuées en succès. Student E2E, recherche avec citations, charge, rollback et cutover du candidat final demeurent **non testés** dans cette qualification en lecture seule.
