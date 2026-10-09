# Lot 308 — provenance des quatre images du candidat public

## Résultat

Ce lot prépare, sans exécuter de build distant ni déploiement, une voie de
provenance **explicitement opt-in** pour le candidat public avec Cockpit. Le
workflow de provenance existant conserve par défaut
`NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1` et ses trois services exacts :
`ingestor`, `multilevel-worker-a-production` et
`multilevel-worker-b-production`. L'input booléen `public_candidate=true`
construit en plus l'image autonome du Cockpit depuis le même commit `main`,
avec `SOURCE_COMMIT_SHA` comme argument de build, puis publie un artefact
distinct `NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V2` contenant exactement quatre
services. Aucun digest de cette voie n'est encore produit ou présenté comme
preuve de release finale.

Le vérificateur V2 exige le dépôt `cyranoaladin/RAG`, le run GitHub Actions
réussi du workflow canonique sur le SHA exact, l'attempt courant, l'arbre et
l'artefact V2 distinct. Il refuse un service manquant ou supplémentaire, une
référence mutable, un contexte/Dockerfile/dépôt d'image différent, ou des
images worker A/B non identiques. Son entrée et son téléchargement V2 sont
séparés des fonctions publiques V1 ; les appelants historiques gardent le
protocole, l'artefact et les trois services V1 exacts. Le workflow ne signe
rien et ne déploie rien.

## Base et preuve locale

- Base `origin/main` : `4af36c7befa7e0118a2c15fcd33274e91f5c68e0`, arbre
  `23568c4067b67c9051248d582cb4a903ea9d0852`, worktree propre avant
  changement ; constat du 2026-10-09T16:35:27Z.
- TDD : les tests V2 ont d'abord échoué faute de
  `verify_public_candidate_image_provenance` ; après implémentation, **300/300**
  tests de provenance V1/V2, signataire, wrapper, préflight et plan signé
  réussissent dans un venv neuf avec paquets locaux installés sans mode
  éditable. Le contrôle a été rejoué le 2026-10-09T16:58:59Z sur le commit
  de code et de tests `3df9952c3781d4a9575d8596e7bb29278e1df2b5`, arbre
  `d4f5b216c84ece9ae5f244bf12473b5dfeac7d8f`, worktree propre. Commande
  depuis la racine, avec le Python du venv isolé :

  ```bash
  python -m pytest -o addopts='' services/rag-engine/tests/test_deployment_image_inventory.py services/rag-engine/tests/test_verify_release_image_provenance_cli.py services/rag-engine/tests/test_sign_production_readiness_manifest_cli.py services/rag-engine/tests/test_deploy_verified_release_cli.py services/rag-engine/tests/test_public_blue_green_preflight.py services/rag-engine/tests/test_signed_public_candidate_plan.py scripts/tests/test-production-image-provenance-workflow.py
  ```

  L'assembleur Python réel extrait du YAML a été
  exécuté en deux modes : V1 émet toujours exactement trois services et son
  document entier est comparé à un oracle figé hors horodatage ; V2 émet
  exactement les quatre services attendus avec Cockpit et son document entier
  est comparé à un autre oracle figé hors horodatage. Les deux dates sont
  contrôlées en ISO UTC. V2 utilise un fichier
  distinct. Les modes invalides et digests Cockpit absents, ainsi que les cas
  de run, SHA, arbre, protocole, source et digest divergents sont refusés.
- Ruff avec la configuration `rag-engine` : succès. `git diff --check` :
  succès.
- Build Docker **local** `linux/amd64` du Dockerfile Cockpit : succès avec
  `SOURCE_COMMIT_SHA=0000000000000000000000000000000000000000`, sentinelle
  synthétique uniquement. Conteneur éphémère : utilisateur `node`, zéro
  mount, `/` HTTP 200, `/api/health` HTTP 503 attendu sans moteur RAG. Image
  et conteneur locaux supprimés. L'ID local n'est ni un digest de registre ni
  une provenance du SHA final.

## Frontière du lot

Le Compose public actuel ne déclare pas encore le Cockpit et son préflight
reste volontairement limité à trois services. Le signataire et le wrapper
historiques consomment encore V1. Un lot suivant devra relier **le même
inventaire V2 vérifié** aux quatre références par digest du Compose public,
à la readiness V2 signée et au bundle atomique, puis démontrer le BFF sur le
seul `bff_net` de sa couleur, port hôte loopback, aucun accès DB/writer/ingest
ni bind mount du dépôt. Il devra également tester le refus si le digest du
Cockpit ou le SHA source diffère. Aucune preuve V1/V2 de répétition ne vaut
autorisation de promotion de la future release publique successeur.

```text
FINAL_COCKPIT_REGISTRY_DIGEST=absent
PUBLIC_COMPOSE_COCKPIT_BOUND=false
PUBLIC_SIGNED_READINESS_COCKPIT_BOUND=false
STAGING_FINAL_E2E_PASS=false
PRODUCTION_READY=false
GO_LIVE_READY=false
RAG_PRODUCTION_DEPLOYED=false
```
