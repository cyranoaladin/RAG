# Liaison du préflight public au wrapper signé — 9 octobre 2026

## Portée et verdict

Base : `origin/main` `366c291ed96832c636c34c5c22878b468b345718`, arbre
`18d07cd40e7c740dc90b8c48d9e1fd735422b878`, après fetch frais et dans
un worktree/venv isolé. Aucun staging ni environnement de production n'a été
muté par ce lot.

`deploy_verified_release_cli.plan_signed_public_candidate` lie maintenant
trois preuves dans le wrapper existant :

1. la signature de readiness **V2** sous l'ancre fournie et l'ensemble exact
   de matériaux/revocations/autorisations V2, via le vérificateur existant ;
2. le digest du Compose public résolu, son SHA/arbre source et les digests des
   images applicative et amont exactement égaux au manifeste signé ;
3. le préflight du candidat blue-green de #303, avec une image API tirée du
   run canonique de provenance correspondant au run scellé dans la promotion.

Le résultat retourne systématiquement `mutation_allowed=false`,
`production_ready=false` et `go_live_ready=false`. Il ne construit pas
d'image, n'exécute aucune commande Docker mutante et n'est pas exposé comme
un nouveau `--execute` public dans le CLI. Les anciens parcours du wrapper
restent inchangés. Les tests synthétiques démontrent notamment le refus d'une
signature altérée, d'un Compose modifié après signature, d'une image API
divergente et d'un fichier de release modifié.

## Préconditions de cutover encore manquantes

Ce pont est un **plan local**, pas la preuve d'un candidat opérable. Le CLI
signer V2 et le bundle de déploiement courants résolvent encore les trois
Compose historiques en place ; ils ne matérialisent pas l'overlay public
depuis l'objet Git du SHA final. Les répertoires de modèles, corpus et
registre publics n'ont pas encore de snapshot durable consommé par une
commande `compose up` avec revalidation de leur identité immédiatement avant
mutation. Aucun chemin de mutation publique n'est ajouté par ce lot.

La release publique successeur, les droits de visibilité student, la qualité
retrieval, C0, l'image Cockpit/BFF par digest, son E2E, le proxy public, le
rollback de la couleur candidate, la signature opérateur finale et le GO
explicite restent à prouver. En particulier, le fait historique
`GET /ingest -> 401` au proxy ne démontre pas
`PUBLIC_INGEST_ENDPOINT=false` : le candidat final devra refuser la route au
reverse proxy/public edge et rester sans writer. Le résultat de la fonction
énumère les préconditions techniques non démontrées ; il ne calcule aucun
`BLOCKER_COUNT=0`.

## Vérifications

- `python -m pytest -q services/rag-engine/tests/test_signed_public_candidate_plan.py services/rag-engine/tests/test_public_blue_green_preflight.py services/rag-engine/tests/test_public_blue_green_compose.py services/rag-engine/tests/test_deploy_verified_release_cli.py` : 90 tests réussis.
- `ruff check` sur les deux fichiers Python du lot et `git diff --check` : verts.
- Cycle TDD : le premier test du plan a échoué sur l'absence de
  `plan_signed_public_candidate` avant l'implémentation.

Le test utilise des signatures Ed25519 et un ensemble V2 synthétiques ; il
ne se substitue à aucune signature opérateur ni à une vérification sur une
release publique finale.
