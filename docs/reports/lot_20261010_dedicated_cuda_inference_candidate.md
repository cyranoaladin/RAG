# Lot — profil d'inférence CUDA dédié, sans promotion

Date de vérification : 2026-10-10T14:51:59Z. Base exacte : `origin/main=84c05e0041b17e59f2b0f99a69193352a8d9dab0`, tree `070bd8f8a5f875df16d2db487833538c3e505d98`. Travail réalisé dans un worktree propre avec un venv propre à ce worktree. Aucune écriture staging ou production.

## Fait déclencheur et périmètre

Le budget C0 versionné reste 8 clients, 240 requêtes, p50 ≤ 3 000 ms, p95 ≤ 6 000 ms, p99 ≤ 7 500 ms, zéro erreur/timeout et au plus 10 connexions DB. L'échec historique 232 HTTP 503 / 240 requêtes demeure un échec. Le Compose v2 de la base limite l'API à 2 CPU et 8 Gio ; elle lance un worker Uvicorn, et `inference_runtime.py` sérialise l'inférence sur un créneau. L'image canonique installe `torch==2.4.1+cpu`. Une réservation GPU seule ne peut donc pas la rendre accélérée.

Ce lot fournit une **variante candidate CUDA** de l'image API, sans changer l'image CPU canonique. Le manifeste des dépendances garde les mêmes versions applicatives et épingle seulement `torch==2.4.1+cu121` depuis l'index CUDA 12.1 de PyTorch. Cette roue et cet index sont documentés par [PyTorch 2.4.1](https://pytorch.org/get-started/previous-versions/). Le Dockerfile CUDA conserve l'allowlist de modules de lecture/revue, sans writer ni parseur supplémentaire. L'override Compose réserve exactement un GPU NVIDIA et exige que les quotas CPU/RAM soient fournis explicitement après qualification de la cible ; il garde un seul worker. Le préchargement des deux modèles refuse le démarrage lorsque `RAG_REQUIRE_CUDA=true` et que CUDA est indisponible, ou que l'embedder ou le reranker reste sur CPU. Le profil CPU par défaut est inchangé.

## Vérifications effectuées

- TDD : 8 échecs attendus avant implémentation du profil et de son garde ; 109 tests ciblés verts après implémentation (`test_dedicated_cuda_inference_target`, `test_inference_runtime`, `test_retrieval_v2_endpoint`, `test_prod_compose_config_mount`). Le test additionnel d'intégration prouve que le préchargement refuse un repli CPU.
- Ruff sur les deux modules touchés et le nouveau test : vert. `git diff --check` : vert.
- `docker compose config --format json` avec l'override, des valeurs factices pour les secrets et des quotas **illustratifs non retenus** : rendu vert, un device `driver=nvidia, count=1, capabilities=[gpu]`, `RAG_REQUIRE_CUDA=true`, Dockerfile CUDA et commande Uvicorn à un worker. Le même rendu sans quota CPU explicite échoue. Cela vérifie la forme Compose ; cela ne prouve pas l'existence d'un GPU sur la future cible.
- Aucun test GPU réel, aucune image CUDA construite ou publiée, aucun digest final et aucune mesure C0 sur la cible. Les chiffres de performance GPU du document d'arbitrage restent des estimations, non des preuves de qualification.

## Liaison nécessaire avant le staging final

La cible d'inférence dédiée n'est pas encore identifiée ni qualifiée. Il faut relever en lecture seule son identité, son GPU/VRAM, son pilote, son runtime NVIDIA Docker, ses quotas CPU/RAM et la connectivité vers la base de qualification, puis choisir les quotas sur ces faits. Le workflow actuel `production-image-provenance.yml` construit l'image CPU canonique ; il doit produire et attester la **variante CUDA** au SHA final avant qu'un digest puisse remplacer l'image API dans la chaîne de release. L'image ne doit pas être construite sur l'hôte final, et la variante candidate ne peut pas être substituée silencieusement au digest CPU.

Après image et cible attestées : préchargement/health sur la vraie cible, qualité retrieval finale liée aux manifests, warmup vert puis C0 à budget inchangé. Les 503, latences et connexions doivent être observés réellement. Aucune ligne de ce rapport ne vaut `LOAD_PASS`, `STAGING_FINAL_PASS`, `PRODUCTION_READY` ou `GO_LIVE_READY`.
