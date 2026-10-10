# Répétition Docker atomique sur le `main` courant

**Observation :** 2026-10-10T13:46:47Z. **Code qualifié :** `origin/main` `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`, arbre `93e9f382fb12bd49ee3489056e0536f4d66c1976`. Le checkout était propre avant exécution ; le rapport et les trois fichiers de preuve sont les seuls ajouts de ce lot.

## Statut de la PR historique

La [PR #132](https://github.com/cyranoaladin/RAG/pull/132) est `CLOSED`, sans `mergedAt` ni merge commit (état GitHub relu le 2026-10-10). Son harnais `atomic_docker_v2_rehearsal.py` figure déjà dans `main`, introduit par le commit `eb0fb6a6` de la PR #206. Le wrapper public a ensuite été qualifié dans le [lot #311](lot_311_public_atomic_candidate_deployment_20261009.md). Il n'y a donc pas lieu de fusionner #132 ; sa preuve d'août ne sert pas de preuve fraîche.

## Exécution isolée

Le daemon visé était le Docker **local** du contexte `default` (`unix:///var/run/docker.sock`), version 29.1.3 ; Compose 5.6.0. L'image `alpine:3.20` était déjà présente sous `alpine@sha256:d9e853e87e55526f6b2917df91a2115c36dd7c696a35be12163d44e6e2a4b6bc`. Aucun build ni téléchargement d'image applicative n'a été nécessaire. Un venv neuf a reçu les paquets locaux par installation non éditable et les dépendances légères requises. Les projets Compose générés étaient exclusivement `nexus-go-live-rehearsal-v2-<identifiant>-(main|witness|collision)` ; le test complémentaire du wrapper public a utilisé `nexus-rag-rehearsal-<identifiant>`.

Depuis la racine du worktree, avec le Python de ce venv :

```bash
umask 077
python services/rag-engine/scripts/atomic_docker_v2_rehearsal.py \
  --repo-root . \
  --output-dir docs/reports/evidence/lot_20261010_atomic_docker_mainfc6 \
  --image-tag alpine:3.20
PYTHONPATH=services/rag-engine/scripts python -m pytest -q \
  services/rag-engine/tests/test_atomic_docker_v2_rehearsal.py
PYTHONPATH=services/rag-engine/scripts python -m pytest -q \
  services/rag-engine/tests/test_public_atomic_docker_rehearsal.py
sha256sum -c docs/reports/evidence/lot_20261010_atomic_docker_mainfc6/atomic_docker_v2_rehearsal_20260825.sha256
```

Le CLI Docker a rendu **exit 0**. La suite du harnais : **26 succès, 1 skip** (test Docker opt-in désactivé ; le CLI ci-dessus l'exerce réellement). Le test Docker du wrapper public : **1 succès**. L'inventaire Docker après ces deux exécutions ne contenait aucun conteneur, réseau ou volume résiduel dans leurs espaces de noms de répétition.

## Verdicts issus de la preuve fraîche

| Critère | Valeur observée |
| --- | --- |
| `ATOMIC_DOCKER_V2_REHEARSAL_PASS` | `true` |
| `BAD_DIGEST_REFUSED` | `true`, avant mutation |
| `BAD_READINESS_REFUSED` | `true`, avant mutation |
| `ROLLBACK_REHEARSAL_PASS` | `true` |
| `FOREIGN_SERVICES_TOUCHED` | `0` |
| `REMOVE_ORPHANS_USED` | `false` |
| `PRODUCTION_PROJECT_NAME_USED` | `false` |
| `PRODUCTION_PORTS_PUBLISHED` | `0` |
| `PROJECT_CONTAINERS_REMAINING` | `0` |

La preuve inclut aussi `BAD_AUTHORIZATION_SET_REFUSED=true`, `FOREIGN_COLLISION_REFUSED=true` et `ISOLATION_PREFLIGHT_PASS=true`. Le transcript atteste un rollback exit 0 et zéro résidu. Les quatre empreintes du fichier `.sha256` ont été vérifiées. SHA-256 du [JSON de preuve](evidence/lot_20261010_atomic_docker_mainfc6/atomic_docker_v2_rehearsal_20260825.json) : `5aeb2b516c8de7b24a020d067a90e019cda92e0b88bd164edc3362ea221f2017`. Voir également le [transcript](evidence/lot_20261010_atomic_docker_mainfc6/atomic_docker_v2_rehearsal_20260825.transcript.txt) et les [empreintes](evidence/lot_20261010_atomic_docker_mainfc6/atomic_docker_v2_rehearsal_20260825.sha256). Le nom de fichier historique `20260825` est émis par le harnais intact ; le timestamp et les SHA ci-dessus identifient cette exécution du 10 octobre.

## Portée

La fixture utilise des identités synthétiques, des clés éphémères et cinq services Alpine par digest. Le test du wrapper public remplace la vérification de signature et le préflight réel par des fixtures pour exercer `pull → up → rollback` contre Docker. Ces résultats prouvent le comportement atomique et les refus sur le `main` qualifié ; ils ne qualifient ni les images RAG/Cockpit finales, ni la readiness signée réelle, ni le staging, ni la production. Aucun hôte staging ou production n'a été modifié. Une répétition liée au SHA final restera nécessaire si le code de déploiement change avant le cutover.
