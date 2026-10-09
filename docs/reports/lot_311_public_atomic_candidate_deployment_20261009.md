# Lot 311 — Déploiement atomique local du candidat public

## Base et identité

- Fetch frais du 2026-10-09 : `origin/main` = `029f6c9987b718fb96142b6ae63836ccf2f922e4`, arbre `8d82d42347ec9545a68baaa7e5aa4a71ee4b9cff`. La PR #310 y est fusionnée. Worktree propre créé depuis ce main ; seuls les deux commits du lot 311 ont été transplantés, sans cherry-pick du lot 310.
- HEAD de code qualifié : `7e3afd488734dde9c65099ece4ca57ddc6bceb40`, arbre `997e43fe3e5ce709d1fb6fe39795013ddc9f1158`. La preuve Docker ci-dessous est épinglée à ce code, avant le commit documentaire.
- Venv Python 3.12 propre et non éditable, propre à ce worktree. Aucun staging, registre, serveur ou base de production muté ; aucune clé opérateur lue ou utilisée ; aucune image applicative construite ou poussée.

## Changement

Le wrapper existant conserve le bundle public V2 en mode plan par défaut. L'exécution requiert le GO explicite, la readiness V2 signée, le bundle et les images par digest vérifiés, le préflight public, et un nouveau `check_go_live_readiness.py --assert-ready` sur le checkout propre au SHA signé. Avant `pull`, le préflight refuse toute ressource préexistante du projet `nexus-rag-blue|green`. Le wrapper exécute `pull` puis `up -d --no-build --pull never --wait` sur les cinq services explicites. Il ne construit aucune image, ne change aucun vhost, n'emploie ni `--remove-orphans` ni le projet historique, et n'ajoute aucun writer ou endpoint d'ingestion.

Avant le premier inventaire, un verrou de couleur indépendant du répertoire d'état sérialise les invocations host-local de ce wrapper. Le garde vérifie que le CLI parle au Docker Unix local, directement ou via `docker.socket` de systemd, et partage l'espace réseau du daemon ; proxy, daemon distant ou namespace différent sont refusés. Le répertoire d'état privé et durable est obligatoire pour exécution et rollback publics. Après succès, un état 0600 lie digest et chemin du bundle, SHA source et IDs des cinq conteneurs. Le rollback explicite refuse un ancien bundle, des IDs changés ou des labels Compose ambigus. En cas d'échec de `up`, de la sonde ou de publication de l'état, `down` est limité aux conteneurs prouvés appartenir au bundle courant ; une identité ambiguë impose le refus de `down`. Après un `down` réussi, un état partiellement publié n'est retiré que s'il correspond exactement à la génération visée. Les volumes sont conservés.

`docker compose up --wait` accepte un service simplement `running` sans healthcheck. Prometheus est dans ce cas. Une sonde post-`up` exige donc `/-/ready` et les quatre alertes du groupe `retrieval-v2` réellement chargées via `/api/v1/rules`. Son échec déclenche le rollback sous le même verrou. La voie V1 reste inchangée.

## TDD et vérifications sur la base courante

- Red confirmé pour les deux racines d'état concurrentes, l'ancien bundle tentant le rollback d'une nouvelle génération, les labels ambigus, les règles Prometheus absentes et l'échec `fsync` après publication de l'état. Green après correction : 24 tests ciblés, dont le témoin Docker public réel à cinq Alpine.
- Suite élargie lancée depuis `services/rag-engine` avec `PYTHONPATH=src:src/ingestor` sur les treize fichiers ci-dessous : **670 collectés, 669 réussis, 1 skip**. Le premier essai depuis la racine avait 15 échecs d'import (`collection_config`, puis `prometheus_client`) dus au PYTHONPATH et au venv ciblé. Le paquet manquant a été installé à son pin `prometheus-client==0.20.0`, puis cette suite a passé. L'ancienne suite main59 de 467 cas n'est pas réutilisée comme preuve : sa commande exacte n'était pas conservée et celle-ci couvre explicitement davantage de fichiers pertinents.
- `ruff check` sur les trois fichiers Python modifiés et `git diff --check` : zéro erreur. Mypy ciblé sur wrapper et harnais V2 : 60 diagnostics dans le candidat et exactement les mêmes 60 diagnostics normalisés (fichier + message) sur un worktree détaché de main 029f6c99 avec le même venv. Aucune nouvelle erreur ; mypy n'est pas vert.
- Répétition Docker publique synthétique : cinq conteneurs Alpine par digest, projet `nexus-rag-blue`, témoin étranger inchangé, refus avant mutation du mauvais digest et de la mauvaise readiness, zéro ressource de cette couleur après rollback. La signature et le préflight y sont remplacés par une fixture ; ce témoin ne qualifie pas une vraie release RAG.

Commande de suite élargie, depuis `services/rag-engine` :

```bash
PYTHONPATH=src:src/ingestor ../../.venv/bin/python -m pytest -q \
  tests/test_deploy_verified_release_cli.py \
  tests/test_public_atomic_deploy.py \
  tests/test_public_atomic_docker_rehearsal.py \
  tests/test_public_blue_green_compose.py \
  tests/test_public_blue_green_preflight.py \
  tests/test_signed_public_candidate_plan.py \
  tests/test_atomic_docker_v2_rehearsal.py \
  tests/test_sign_production_readiness_manifest_cli.py \
  tests/test_verify_release_image_provenance_cli.py \
  tests/test_release_readiness.py \
  tests/test_deployment_image_inventory.py \
  tests/test_prod_compose_config_mount.py \
  tests/test_production_workers_compose.py
```

Le harnais Docker V2 historique a été rejoué séparément sur le HEAD de code ci-dessus, au `2026-10-09T19:45:20Z`. Il établit `ATOMIC_DOCKER_V2_REHEARSAL_PASS=true`, `BAD_DIGEST_REFUSED=true`, `BAD_READINESS_REFUSED=true`, `ROLLBACK_REHEARSAL_PASS=true`, `FOREIGN_SERVICES_TOUCHED=0`, `REMOVE_ORPHANS_USED=false`, `PRODUCTION_PROJECT_NAME_USED=false`, avec zéro conteneur, réseau ou volume résiduel. [JSON](evidence/lot_311_main029/atomic_docker_v2_rehearsal_20260825.json), [transcript](evidence/lot_311_main029/atomic_docker_v2_rehearsal_20260825.transcript.txt), [empreintes](evidence/lot_311_main029/atomic_docker_v2_rehearsal_20260825.sha256). SHA-256 du JSON : `0363fcd598781bb29984791995a5d075877e118aa1e388b91be2a96b2f4cfbd1`. Cette preuve reste synthétique et distincte du témoin du chemin public du lot.

## Limites pour le go-live

Ce lot ne signe aucune readiness opérateur et ne mute ni staging ni production. La release publique successeur gouvernée, les droits étudiants, les images finales, le staging final, la qualité des onze collections, C0, backup/restore, routage edge, qualification de la cible production et GO humain restent des preuves distinctes. Le verrou protège seulement les invocations host-local de ce wrapper ; un acteur Docker extérieur au protocole ne l'acquiert pas. `PRODUCTION_READY=false`, `GO_LIVE_READY=false` et `RAG_PRODUCTION_DEPLOYED=false` restent les verdicts de ce lot isolé.
