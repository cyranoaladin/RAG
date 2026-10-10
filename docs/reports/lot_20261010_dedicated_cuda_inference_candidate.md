# Lot — profil d'inférence CUDA dédié, sans promotion

Date de vérification : 2026-10-10T14:51:59Z. Base exacte : `origin/main=84c05e0041b17e59f2b0f99a69193352a8d9dab0`, tree `070bd8f8a5f875df16d2db487833538c3e505d98`. Travail réalisé dans un worktree propre avec un venv propre à ce worktree. Aucune écriture staging ou production.

## Fait déclencheur et périmètre

Le budget C0 versionné reste 8 clients, 240 requêtes, p50 ≤ 3 000 ms, p95 ≤ 6 000 ms, p99 ≤ 7 500 ms, zéro erreur/timeout et au plus 10 connexions DB. L'échec historique 232 HTTP 503 / 240 requêtes demeure un échec. Le Compose v2 de la base limite l'API à 2 CPU et 8 Gio ; elle lance un worker Uvicorn, et `inference_runtime.py` sérialise l'inférence sur un créneau. L'image canonique installe `torch==2.4.1+cpu`. Une réservation GPU seule ne peut donc pas la rendre accélérée.

Ce lot fournit une **variante candidate CUDA** de l'image API, sans changer l'image CPU canonique. Le manifeste des dépendances garde les mêmes versions applicatives et épingle seulement `torch==2.4.1+cu121` depuis l'index CUDA 12.1 de PyTorch. Cette roue et cet index sont documentés par [PyTorch 2.4.1](https://pytorch.org/get-started/previous-versions/). Le Dockerfile CUDA conserve l'allowlist de modules de lecture/revue, sans writer ni parseur supplémentaire. L'override Compose réserve exactement un GPU NVIDIA et exige que les quotas CPU/RAM soient fournis explicitement après qualification de la cible ; il garde un seul worker. Le préchargement refuse le démarrage lorsque `RAG_REQUIRE_CUDA=true` et que CUDA est indisponible ou qu'un poids/buffer de l'embedder ou du reranker reste sur CPU. Avec la version épinglée de `sentence-transformers`, le `CrossEncoder` ne déplace ses poids qu'au premier `predict` ; le garde les déplace explicitement au préchargement vers son `_target_device` CUDA puis contrôle tous les poids/buffers. Le profil CPU par défaut est inchangé.

## Vérifications effectuées

- TDD : 8 échecs attendus avant implémentation du profil ; l'auto-revue du `CrossEncoder` a ensuite produit deux tests de régression rouges avant le correctif du transfert des poids. Les 111 tests ciblés sont verts (`test_dedicated_cuda_inference_target`, `test_inference_runtime`, `test_retrieval_v2_endpoint`, `test_prod_compose_config_mount`). Le test d'intégration prouve que le préchargement refuse un repli CPU.
- Ruff sur les deux modules touchés et le nouveau test : vert. `git diff --check` : vert.
- `docker compose config --format json` avec l'override, des valeurs factices pour les secrets et des quotas **illustratifs non retenus** : rendu vert, un device `driver=nvidia, count=1, capabilities=[gpu]`, `RAG_REQUIRE_CUDA=true`, Dockerfile CUDA et commande Uvicorn à un worker. Le même rendu sans quota CPU explicite échoue. Cela vérifie la forme Compose ; cela ne prouve pas l'existence d'un GPU sur la future cible.
- L'ordre final `v2 → override CUDA → workers → production-release` rend une image par digest et aucun `build`, tout en conservant la réservation GPU et le refus CPU. L'image de base `python:3.11-slim@sha256:db3ff2e...` existe comme index OCI avec `linux/amd64` ; le wheel `torch-2.4.1+cu121` existe pour CPython 3.11/Linux x86_64 sur l'index officiel. Aucune image CUDA applicative n'est construite dans ce lot.
- Aucun test GPU réel, aucune image CUDA construite ou publiée, aucun digest final et aucune mesure C0 sur la cible. Les chiffres de performance GPU du document d'arbitrage restent des estimations, non des preuves de qualification.

## Liaison nécessaire avant le staging final

La cible d'inférence dédiée n'est pas encore identifiée ni qualifiée. Il faut relever en lecture seule son identité, son GPU/VRAM, son pilote, son runtime NVIDIA Docker, ses quotas CPU/RAM et la connectivité vers la base de qualification, puis choisir les quotas sur ces faits. Le workflow actuel `production-image-provenance.yml` construit l'image CPU canonique ; il doit produire et attester la **variante CUDA** au SHA final avant qu'un digest puisse remplacer l'image API dans la chaîne de release. L'image ne doit pas être construite sur l'hôte final, et la variante candidate ne peut pas être substituée silencieusement au digest CPU.

Après image et cible attestées : préchargement/health sur la vraie cible, qualité retrieval finale liée aux manifests, warmup vert puis C0 à budget inchangé. Les 503, latences et connexions doivent être observés réellement. Aucune ligne de ce rapport ne vaut `LOAD_PASS`, `STAGING_FINAL_PASS`, `PRODUCTION_READY` ou `GO_LIVE_READY`.

## Rejeu après fusion de #313 — 2026-10-10T15:39Z

La branche candidate a intégré sans conflit `origin/main=829bc9acec1eeb17dc9800389c92102b6f2c2297`. Dans un venv Python 3.11 propre au worktree, les 111 tests ciblés du profil, du runtime, de l'endpoint et du contrat Compose passent ; Ruff sur les modules touchés et le nouveau test passe également. Les paquets éditables `nexus-contracts` et `nexus-release-chain` pointent vers ce même worktree.

Un rendu local `docker compose config` dans l'ordre `v2 → CUDA → workers → production-release`, avec secrets et digests **factices** et quotas 4 CPU / 16 Gio **illustratifs**, confirme `build` absent, image par digest, réservation d'un GPU NVIDIA, `RAG_REQUIRE_CUDA=true`, un worker, runtime en lecture seule et refus lorsque le quota CPU est omis. Ces quotas ne sont pas une décision de dimensionnement.

L'hôte local de développement expose une GTX 1650 de 4 Gio avec pilote 580.178.04 et runtime Docker `nvidia`. Un conteneur CUDA 12.0 **déjà présent** a exécuté `nvidia-smi` avec `--gpus all`, sans téléchargement. Le PyTorch local est `2.12.1+cu130` : ce smoke matériel ne teste donc ni l'image candidate épinglée en `2.4.1+cu121`, ni les modèles, ni la cible d'inférence dédiée, ni C0. Le workflow de provenance reste limité à l'image API CPU ; aucun digest applicatif CUDA final n'existe. Aucune écriture staging ou production n'a été effectuée.
