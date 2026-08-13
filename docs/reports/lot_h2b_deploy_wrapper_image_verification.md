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

## 4bis. Revue Codex — trois findings réels, tous corrigés

Une revue fraîche sur le HEAD `ac1c29a` (premier push de ce lot) a
signalé trois findings, tous vérifiés avant correction.

**Finding 1 (P1) — `--repository` était une entrée opérateur non
fiable.** Le CLI acceptait `--repository` en argument libre et
l'utilisait comme ancre de confiance pour la vérification de
provenance. Un opérateur pouvait donc pointer vers un dépôt qu'il
contrôle, y lancer un workflow au bon chemin, et obtenir un verdict
positif pour une image jamais produite par le workflow Nexus de
confiance. Corrigé en retirant purement et simplement l'argument :
`_CANONICAL_REPOSITORY = "cyranoaladin/RAG"` est désormais une constante
du module, jamais une entrée. Prouvé statiquement
(`test_no_repository_cli_flag_exists` : le flag n'existe plus dans
`--help`).

**Finding 2 (P2) — le téléchargement d'artefact dépendait du CWD.**
`deployment_image_inventory.download_artifact_via_gh` (PR #102) appelle
`gh run download` sans `-R <repo>`, donc résout le dépôt depuis le
répertoire courant du process. Lancé hors du bon checkout, ou depuis un
checkout dont le remote nomme un autre dépôt, la commande peut échouer
ou (pire) cibler le mauvais dépôt. Corrigé par l'ajout de
`deployment_image_inventory.make_download_artifact_via_gh(repository=
...)`, une fabrique qui lie `-R` au dépôt déjà vérifié — sans changer la
signature ni le comportement de `download_artifact_via_gh` existante
(toujours utilisée telle quelle ailleurs). Ce lot appelle désormais la
fabrique avec `_CANONICAL_REPOSITORY`.

**Finding 3 (P1) — les fichiers Compose n'étaient jamais liés au commit
vérifié.** `--infra-dir` acceptait n'importe quel répertoire sur disque,
dont le contenu pouvait diverger du commit source vérifié sans que rien
ne le détecte : mêmes trois noms de service attendus + images pinnées
correctement suffisaient à passer `require_resolved_compose_images_
are_pinned`, même si un service supplémentaire à image mutable, ou un
volume/une commande modifiés, avaient été ajoutés à côté. Corrigé en
supprimant `--infra-dir` : les trois fichiers Compose canoniques sont
désormais lus directement depuis l'objet git `source_commit_sha:
services/rag-engine/infra/<fichier>` (nouvelle fonction `_git_show_
bytes`, jamais depuis le disque non vérifié), dans un `--repo-root` qui
est lui-même la racine de confiance de toute exécution hôte — limite
documentée explicitement dans le docstring du module.

```
$ cd services/rag-engine && .venv/bin/python -m pytest \
    tests/test_verify_release_image_provenance_cli.py \
    tests/test_deployment_image_inventory.py -q
61 passed

$ .venv/bin/python -m ruff check scripts/verify_release_image_provenance_cli.py \
    scripts/deployment_image_inventory.py tests/test_verify_release_image_provenance_cli.py
All checks passed!

$ .venv/bin/python -m mypy scripts/verify_release_image_provenance_cli.py \
    scripts/deployment_image_inventory.py
Success: no issues found in 2 source files
```

Les trois corrections sont mutation-testées : suppression du flag
`--repository` prouvée statiquement ; retrait de la lecture git (retour
au disque) dans `run_docker_compose_config_via_subprocess` → le test
d'intégration réel Docker+git passe au rouge pour la bonne raison
(erreur d'interpolation Compose au lieu d'un refus `git show failed`,
preuve que c'est bien la liaison git qui est exercée) ; retrait du `-R`
dans `make_download_artifact_via_gh` → test dédié rouge. Suite restaurée
verte après chacune.

## 4ter. Revue Codex round 2 — chargement de l'environnement de déploiement

Une revue fraîche sur le HEAD `0534ebb` a signalé un dernier finding
P1, vérifié contre le runbook réel avant correction.

**Finding 4 — le `.env` de déploiement n'était jamais chargé.** Vérifié
dans `docs/runbooks/go_live.md` §3 : la voie de production réelle copie
`.env.example` vers `.env` dans `services/rag-engine/infra/`, puis
résout Compose avec `docker compose -f docker-compose.v2.yml --env-file
.env config --quiet`. Ce CLI résolvait les fichiers Compose depuis un
répertoire scratch ne contenant que les trois fichiers eux-mêmes
(lus via `git show`, §4bis), sans jamais passer `--env-file` ni charger
aucun `.env` — sur un hôte normalement configuré, la résolution échouait
systématiquement faute des dizaines de `${VAR:?...}` requis, à moins que
l'opérateur n'exporte manuellement chaque valeur.

Corrigé par un nouveau paramètre `env_file` (CLI `--env-file`, défaut
`<repo-root>/services/rag-engine/infra/.env` — même emplacement que le
runbook), passé à `docker compose --env-file <fichier> ...`. Une
vérification explicite (`env_file.is_file()`) refuse fail-closed avec un
message clair avant tout appel process, plutôt que de laisser échouer
`docker compose` avec un mur d'erreurs d'interpolation peu lisible.

**Pourquoi `.env` n'est jamais vérifié contre git, contrairement aux
fichiers Compose (§4bis).** Il est intrinsèquement host-local — jamais
versionné (`.gitignore`, contient des secrets) — donc il n'existe aucun
objet git contre lequel le confronter, à la différence des trois
fichiers Compose qui, eux, sont bien commités et vérifiables.

```
$ cd services/rag-engine && .venv/bin/python -m pytest \
    tests/test_verify_release_image_provenance_cli.py \
    tests/test_deployment_image_inventory.py -q
63 passed

$ .venv/bin/python -m ruff check scripts/verify_release_image_provenance_cli.py \
    tests/test_verify_release_image_provenance_cli.py
All checks passed!

$ .venv/bin/python -m mypy scripts/verify_release_image_provenance_cli.py
Success: no issues found in 1 source file
```

Deux nouveaux tests d'intégration réelle (Docker+git) : fichier `.env`
absent → refusé avant tout appel process ; un `.env` réel portant
TOUTES les valeurs requises (sans aucune variable shell exportée) permet
une résolution complète — preuve que `--env-file` fournit réellement les
valeurs, pas seulement que son absence est masquée par des variables
shell. Le check d'existence et le câblage `--env-file` sont
mutation-testés individuellement.

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
22 passed

$ .venv/bin/python -m pytest \
    tests/test_deployment_image_inventory.py \
    tests/test_verify_release_image_provenance_cli.py -q
63 passed

$ .venv/bin/python -m ruff check scripts/verify_release_image_provenance_cli.py \
    scripts/deployment_image_inventory.py tests/test_verify_release_image_provenance_cli.py
All checks passed!

$ .venv/bin/python -m mypy scripts/verify_release_image_provenance_cli.py \
    scripts/deployment_image_inventory.py
Success: no issues found in 2 source files

$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ gitleaks detect --source <chaque fichier ajouté/modifié> --no-git   (×3)
no leaks found (×3)
```

Couverture adversariale (20 tests dédiés dans ce fichier, 61 au total
avec la non-régression PR #102) : digests concordants → accepté ; un
service avec un digest différent → refusé (message identifie le
service) ; ensembles de services différents → refusé ; un digest
correctement formé mais sans lien avec la provenance de ce commit →
refusé (preuve que le croisement, pas seulement chaque moitié
isolément, est exercé) ; tag mutable côté Compose résolu → refusé ;
`build:` résiduel → refusé ; run de provenance échoué → refusé ; appel
de `run_docker_compose_config` avec le commit, les trois fichiers
canoniques dans le bon ordre et le répertoire de travail, vérifié
explicitement ; **aucun flag `--repository` dans `--help`** (Finding 1) ;
`main()` : succès → code 0 + `RELEASE_IMAGE_PROVENANCE_VERIFIED=true` +
digests listés ; échec → code 1 + `REFUSED:` sur stderr + **jamais** la
ligne de succès sur stdout ; garantie statique qu'aucune sous-chaîne
`"up"`/`'up'` n'apparaît dans le module (jamais `docker compose up`
invoqué). Les deux branches de `require_pinned_images_match_verified_
provenance` et les trois corrections du round Codex (§4bis) sont toutes
mutation-testées directement (désactivation temporaire de chacune → les
tests concernés passent au rouge → suite restaurée verte).

Suite d'intégration réelle (2 tests, `skipif` sans Docker/git) : objet
git absent → refusé avant tout appel Docker ; les trois vrais fichiers
du dépôt, lus depuis le vrai `HEAD` via `git show` et résolus avec de
vraies valeurs factices, produisent une structure conforme à `require_
resolved_compose_images_are_pinned`. Suite dédiée (2 tests) pour
`make_download_artifact_via_gh`/`download_artifact_via_gh` : la
première passe bien `-R <repo>`, la seconde jamais (non-régression).

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
