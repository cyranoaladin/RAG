# LOT B — Vérificateur hôte pré-déploiement : provenance + pinning d'images (ADR-0036, phase B)

## 1. Verdict du lot

Nouveau script `services/rag-engine/scripts/verify_release_image_
provenance_cli.py` : un vérificateur hors ligne, à lancer sur l'hôte
cible **avant** tout `docker compose up` d'une release de production,
qui refuse fail-closed toute release dont les images ne sont pas (a)
réellement épinglées par digest dans le Compose résolu, et (b) ce
digest précis n'est pas issu d'un run GitHub Actions vérifié pour
EXACTEMENT le commit source déclaré. **N'exécute jamais lui-même
`docker compose up`** (ni aucune autre commande de mutation) : un
verdict positif n'autorise que l'étape de déploiement suivante,
séparée, de l'opérateur humain. Ne construit ni ne pousse aucune image.
Ne recalcule aucun verdict de gouvernance pédagogique (ADR-0001).
`GO_LIVE_READY` reste `false`. Aucune mutation live.

## 2. Pourquoi maintenant

`docs/reports/lot_h2b_production_image_provenance.md` (§7) avait déjà
posé les deux primitives nécessaires — `require_resolved_compose_
images_are_pinned()` et `verify_application_image_provenance()` — mais
explicitement noté qu'aucun wrapper ne les appelait encore
(`DEPLOY_WRAPPER_IMAGE_VERIFICATION=false`, §9). Sans ce lot, un
opérateur pouvait câbler un digest correctement formé, réellement
épinglé, mais **sans lien avec la provenance vérifiée de ce commit**
(substitué, ou laissé d'un essai précédent) — chaque primitive
individuellement l'aurait accepté, faute d'être jamais confrontées
l'une à l'autre.

## 3. Ce que ce lot ajoute réellement — un seul fait nouveau

Les deux primitives existantes (PR #102) ne sont pas redéfinies. Ce lot
ajoute exactement une fonction, `require_pinned_images_match_verified_
provenance()`, qui confronte :

- `pinned_images` — sortie de `require_resolved_compose_images_are_
  pinned()`, contre un `docker compose ... config --format json` réel.
- `provenance_images` — sortie de `verify_application_image_
  provenance()`, contre un run GitHub Actions réel et vérifié.

et refuse tout service où les deux digests diffèrent, ou où les deux
ensembles de services nommés diffèrent. Le script (`verify_release_
images()`) orchestre les trois appels dans l'ordre : résoudre Compose →
vérifier le pinning → vérifier la provenance → confronter les deux.
Toute frontière réseau/processus (`github_api_get`, `download_
artifact`, `run_docker_compose_config`) est injectée par l'appelant —
jamais un vrai `gh`/`docker` dans les tests unitaires.

## 4. Vérification empirique du format `docker compose config`

Avant d'écrire le module, la combinaison réelle des trois fichiers
(`docker-compose.v2.yml` + `docker-compose.production-workers.yml` +
`docker-compose.production-release.yml`) a été résolue avec `docker
compose ... config --format json` (Docker Compose v5.4.0, valeurs
factices non vides pour les ~70 variables requises, dérivées
dynamiquement des fichiers réels — jamais une liste figée) :

```
$ docker compose -f docker-compose.v2.yml -f docker-compose.production-workers.yml \
    -f docker-compose.production-release.yml config --format json
# exit 0 ; les 3 services applicatifs : "build" absent, "image" = name@sha256:<64hex>
```

Confirme empiriquement que la structure attendue par `require_
resolved_compose_images_are_pinned()` (déjà vérifiée dans PR #102)
tient aussi en bout de chaîne réelle avec les trois fichiers combinés
dans cet ordre précis — pas seulement en isolation. Ce même scénario
est repassé en test d'intégration (`TestRunDockerComposeConfigVia
Subprocess`, gardé par `skipif(not shutil.which("docker"))`, même
convention que `tests/test_governance_docker_policy.py`).

## 5. Ce que ce lot ne fait pas

- N'intègre pas ce script dans `sign_production_readiness_manifest_
  cli.py` (PR #100) — portée disjointe : le signer produit un
  manifeste hors ligne signé, ce script est un gate d'exécution côté
  hôte, invoqué séparément avant `docker compose up`.
- N'exécute jamais `docker compose up`, ni aucune commande de mutation
  — vérifié statiquement (`test_main_never_invokes_docker_compose_up`)
  en plus du comportement.
- Ne construit ni ne pousse aucune image (§9 du lot #102 reste hors
  périmètre : compte `nexus-deployer`, environnement GitHub protégé,
  rotation des clés, dépréciation du script legacy).
- N'exécute aucune mutation contre le serveur réel (`korrigo`) —
  `LIVE_MUTATIONS_ALLOWED=false`. Ce lot ne peut donc pas encore
  prouver un run bout-en-bout contre de vraies images GHCR
  (`IMAGES_ACTUALLY_BUILT_AND_PUSHED=false`, hérité du lot #102) ; les
  tests d'intégration Docker exercent le vrai binaire `docker compose`
  contre les fichiers réels du dépôt, avec des digests factices —
  jamais un registre distant.

## 6. Tests — résultats exacts

```
$ cd services/rag-engine && .venv/bin/python -m pytest \
    tests/test_verify_release_image_provenance_cli.py -v
15 passed

$ .venv/bin/python -m pytest \
    tests/test_deployment_image_inventory.py \
    tests/test_verify_release_image_provenance_cli.py -q
58 passed

$ .venv/bin/python -m ruff check scripts/verify_release_image_provenance_cli.py \
    tests/test_verify_release_image_provenance_cli.py
All checks passed!

$ .venv/bin/python -m mypy scripts/verify_release_image_provenance_cli.py
Success: no issues found in 1 source file

$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ gitleaks detect --source <chaque fichier ajouté> --no-git   (×2)
no leaks found (×2)
```

Couverture adversariale (15 tests dédiés) : digests concordants →
accepté ; un service avec un digest différent → refusé (message
identifie le service) ; ensembles de services différents → refusé ;
un digest correctement formé mais sans lien avec la provenance de ce
commit → refusé (preuve que le croisement, pas seulement chaque moitié
isolément, est exercé) ; tag mutable côté Compose résolu → refusé ;
`build:` résiduel → refusé ; run de provenance échoué → refusé ; appel
de `run_docker_compose_config` avec les trois fichiers canoniques dans
le bon ordre, vérifié explicitement ; `main()` : succès → code 0 +
`RELEASE_IMAGE_PROVENANCE_VERIFIED=true` + digests listés ; échec →
code 1 + `REFUSED:` sur stderr + **jamais** la ligne de succès sur
stdout ; garantie statique qu'aucune sous-chaîne `"up"`/`'up'`
n'apparaît dans le module (jamais `docker compose up` invoqué). Les
deux nouvelles branches de `require_pinned_images_match_verified_
provenance` sont mutation-testées directement (désactivation
temporaire de chacune → les tests concernés passent au rouge → suite
restaurée verte).

Suite d'intégration réelle (2 tests, `skipif` sans Docker) : fichier
Compose absent → refusé avant tout appel process ; les trois vrais
fichiers du dépôt, résolus avec de vraies valeurs factices, produisent
une structure conforme à `require_resolved_compose_images_are_pinned`.

## 7. Booléens finaux

```
DEPLOY_WRAPPER_IMAGE_VERIFICATION=true   # mécanisme livré et testé ; jamais exécuté contre GHCR réel (§5)
DEPLOY_WRAPPER_NEVER_RUNS_COMPOSE_UP=true
COMPOSE_RESOLUTION_VERIFIED_AGAINST_REAL_FILES=true
PINNED_DIGEST_BOUND_TO_VERIFIED_PROVENANCE=true
RAG_ENGINE_TO_RAG_PEDAGO_IMPORT=false   # ADR-0001 respecté (aucun import ajouté)
IMAGES_ACTUALLY_BUILT_AND_PUSHED=false   # hérité du lot #102, toujours vrai
REGISTRY_DIGEST_VERIFIED=false   # aucun push réel encore effectué
GITHUB_ENVIRONMENT_PROTECTION_CONFIGURED=false
NEXUS_DEPLOYER_ACCOUNT_PROVISIONED=false
LEGACY_DEPLOY_SCRIPT_DEPRECATED=false
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```

## 8. Prochaines étapes (hors de ce lot)

1. Trusted-human review + merge de ce lot.
2. `gh workflow run production-image-provenance.yml --ref main` sur un
   SHA main réel post-merge → produit les vrais digests GHCR (hérité,
   lot #102 §11).
3. Une fois de vraies images poussées : premier run réel de ce script
   contre le serveur (`korrigo`), sous HUMAN GATE explicite —
   `LIVE_MUTATIONS_ALLOWED` reste `false` jusque-là.
4. Câblage éventuel dans un futur runbook de déploiement qui
   remplacerait `deploy-prod.sh` (§9 du lot #102, non traité ici).
