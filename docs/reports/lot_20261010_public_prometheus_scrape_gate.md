# Lot 2026-10-10 — collecte API exigée avant acceptation du candidat public

## Périmètre et identité

Base fraîche `origin/main` : `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`, arbre `93e9f382fb12bd49ee3489056e0536f4d66c1976`. Code qualifié après TDD : `73d69c3847b8bbb293265af6148053446f4b891a`, arbre `066a17c2578b2e748326982e23ceda66451682a8`. Worktree et environnement virtuel propres à ce lot ; aucun package Nexus installé en éditable depuis un autre worktree.

Le `main` de base possède déjà la pile publique blue-green à cinq services, les images par digest, les matériaux hors checkout, le bundle signé, le déploiement sous GO explicite, le rollback de la couleur candidate et la sonde des quatre alertes Prometheus. La qualification de production en lecture seule du 10 octobre observe **0 alerte chargée dans le runtime historique** ; elle ne décrit pas la future couleur candidate.

## Défaut et correction

La sonde post-déploiement dans `deploy_verified_release_cli.py` acceptait `/-/ready` et les quatre règles `retrieval-v2` même lorsque la cible API `rag-engine-v2` était absente ou `down`. Le déploiement pouvait donc rendre `PUBLIC_CANDIDATE_DEPLOYED=true` sans collecte effective des métriques de recherche.

La sonde interroge maintenant l'API instantanée Prometheus pour `up{job="rag-engine-v2"}`. Elle exige une unique série de la cible API, avec valeur `1`. Une réponse absente, `0`, partiellement indisponible, mal formée ou non concluante laisse la sonde rouge ; le chemin existant retire alors uniquement la couleur candidate après vérification de son identité. La topologie, les budgets retrieval, les règles d'alerte et le contrat métier n'ont pas changé. Le wrapper continue à retourner `EDGE_SWITCHED=false`.

## Preuves locales

- TDD : les quatre nouveaux cas ont d'abord échoué sur le faux vert (cible absente, cible à `0`, séries mixtes ; absence d'appel à la requête Prometheus), puis ont réussi avec le correctif. Suite `test_public_atomic_deploy.py` : **35 réussis**. Suite élargie des cinq fichiers de déploiement public, Compose et préflight : **171 réussis**, exit 0. `ruff check` ciblé et `git diff --check` : exit 0.
- `promtool check config` dans l'image épinglée `prom/prometheus@sha256:f6639335d34a77d9d9db382b92eeb7fc00934be8eae81dbc03b31cfe90411a94` : configuration valide, **un fichier et quatre règles**. Ce contrôle prouve la syntaxe, pas le chargement sur la cible finale.
- Rehearsal Docker V2 **synthétique et local** rejoué sur le SHA de code ci-dessus le `2026-10-10T14:00:10Z`, Docker 29.1.3 / Compose 5.6.0 : `ATOMIC_DOCKER_V2_REHEARSAL_PASS=true`, `BAD_DIGEST_REFUSED=true`, `BAD_READINESS_REFUSED=true`, `ROLLBACK_REHEARSAL_PASS=true`, `FOREIGN_SERVICES_TOUCHED=0`, `REMOVE_ORPHANS_USED=false`, `PRODUCTION_PROJECT_NAME_USED=false`, `PROJECT_CONTAINERS_REMAINING=0`. [JSON](evidence/lot_20261010_public_prometheus_scrape_rehearsal/atomic_docker_v2_rehearsal_20260825.json), [transcript](evidence/lot_20261010_public_prometheus_scrape_rehearsal/atomic_docker_v2_rehearsal_20260825.transcript.txt) et [empreintes](evidence/lot_20261010_public_prometheus_scrape_rehearsal/atomic_docker_v2_rehearsal_20260825.sha256) ; SHA-256 du JSON `577cc6b2a1830bebb9814ed8358dd3a1e6722b244fc34cf1be982e7006898827`. `sha256sum -c` : quatre entrées valides. Le premier lancement, avec un umask trop permissif, a été refusé avant la création du bundle ; le lancement sous `umask 077` est celui archivé.

## Limites de portée

Les tests de la nouvelle requête Prometheus utilisent des réponses HTTP contrôlées ; le rehearsal Docker vérifie le protocole atomique synthétique, pas une vraie image API ni une collecte de la release finale. Au staging final, la sonde doit voir la cible API réellement `up` et les règles chargées sur le Prometheus de la couleur candidate. Les preuves de qualité, de charge C0, de backup/restore, de droits étudiants, de readiness signée, de routage TLS/Nginx et de cutover restent indépendantes. Aucun staging ou production n'a été modifié. `PRODUCTION_READY=false`, `GO_LIVE_READY=false`, `RAG_PRODUCTION_DEPLOYED=false`.
