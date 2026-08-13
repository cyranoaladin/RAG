# LOT H2-B — Provenance des images de production (ADR-0036 phase B)

## 1. Verdict du lot

Lot dépendant de PR #100, créé après un HUMAN GATE bloqué sur le constat
Codex « Bind the complete image inventory to the Compose file » (`--
application-image` de PR #100 restait une affirmation opérateur pour les
services `build:`). Ce lot construit l'infrastructure manquante :

- un workflow GitHub Actions qui construit et pousse les images
  applicatives de production vers GHCR, jamais sur l'hôte cible ;
- un artefact de provenance machine-readable strict
  (`NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1`) ;
- un module de vérification hors ligne, mutation-testé, que PR #100
  importera dans un commit séparé une fois ce lot mergé (§7) ;
- un fichier Compose de release qui retire réellement `build:` de la
  résolution de production — vérifié empiriquement contre les vrais
  fichiers du dépôt, jamais supposé.

**Ce lot ne construit et ne pousse aucune image réelle** (§8 —
volontairement différé après merge, per instruction humaine). **Aucune
mutation de production.** `GO_LIVE_READY` reste `false`.

Ce lot n'implémente pas ADR-0036 dans son intégralité (Environment GitHub
protégé, compte `nexus-deployer`, wrapper de déploiement complet, rotation
des clés) — seulement la tranche qui débloque
`APPLICATION_IMAGE_PROVENANCE_VERIFIED` pour PR #100. Le reste (§9) reste
explicitement hors périmètre.

## 2. Audit préalable — ce qui existe déjà

- **ADR-0036** (« chaîne de promotion gouvernée »), déjà mergé (PR #95,
  même commit que `production_readiness.py`), déjà cité par le runtime
  réel (`readiness_gate.py`, les CLI de worker, plusieurs suites de
  tests). Son statut textuel reste « Proposé » (même pattern qu'ADR-0035
  avant PR #101) mais son contenu gouverne déjà le code. Il désigne déjà
  GHCR comme cible (« phase B »), rejette explicitement OIDC cloud
  (« aucun fournisseur identifié, hôte unique »), et définit déjà les 26
  champs du manifeste de readiness que PR #100 signe.
- **Déploiement réel actuel** : `services/rag-engine/scripts/deploy-prod.sh`
  — script root manuel, `rsync` + `docker compose build` sur l'hôte,
  stack **legacy** (`docker-compose.prod.yml`, `chroma`/`ollama`/`n8n`),
  pas le stack v2/pgvector dont ce lot s'occupe. Reste la voie
  break-glass (ADR-0036 §1) ; non touché ici.
- **`.github/workflows/`** : `ci.yml` (lint/tests), `_produce-h2-evidence.yml`
  (gate H2, déjà authentifié en lecture seule sur GHCR via
  `github.token` — précédent direct pour l'auth de ce lot),
  `trusted-human-review.yml`. **Aucun workflow de build/push/promotion
  n'existait avant ce lot.**
- **Fichiers Compose réels** (`services/rag-engine/infra/docker-compose*.yml`)
  déjà audités en détail dans `lot_h2b_production_readiness_signing_tool.md`
  §6quater : `docker-compose.v2.yml` (service `ingestor`, `build:`),
  `docker-compose.production-workers.yml` (`multilevel-worker-a/b-
  production`, **même** `build:`/`context`/`dockerfile` que le production
  Compose, confirmant qu'un seul build sert les deux services).
- **`_produce-h2-evidence.yml`** utilise déjà `docker login ghcr.io -u
  ${{ github.actor }} --password-stdin` avec `${{ github.token }}`, en
  lecture seule (`permissions: packages: read`) — précédent direct
  prouvant que l'authentification GHCR native au dépôt fonctionne déjà
  ici, sans PAT.

## 3. Décision — registre et authentification

```
REGISTRY_SELECTED=ghcr.io/cyranoaladin
REGISTRY_AUTH_MODEL=GITHUB_TOKEN (packages:write scope au job, aucun PAT)
```

Pas un choix nouveau : ADR-0036 désigne déjà GHCR (« migration des images
vers GHCR... conçues... en phase B ») et rejette déjà explicitement
l'alternative OIDC cloud avec sa justification (aucun fournisseur cloud,
hôte unique). Le seul travail de ce lot est l'implémentation, pas la
décision.

`packages: write` est déclaré uniquement sur le nouveau workflow
(`.github/workflows/production-image-provenance.yml`), jamais globalement
— principe du moindre privilège, cohérent avec `permissions: packages:
read` déjà utilisé ailleurs dans ce dépôt pour un besoin plus restreint.

## 4. Inventaire des services de production

```
PRODUCTION_ACTIVE_SERVICES=pgvector,ingestor,prometheus,multilevel-worker-a-production,multilevel-worker-b-production
PRODUCTION_BUILD_SERVICES=ingestor,multilevel-worker-a-production,multilevel-worker-b-production
PRODUCTION_UPSTREAM_SERVICES=pgvector,prometheus
```

`multilevel-worker-a-production` et `multilevel-worker-b-production`
partagent exactement le même `context`/`dockerfile`
(`Dockerfile.multilevel-worker-production`) — vérifié en relisant les deux
définitions Compose, pas supposé. **Un seul build**, mais chaque service
reste une entrée **explicite et distincte** dans l'inventaire (même
digest, deux clés) — un inventaire qui n'en listerait qu'un ne doit
jamais couvrir implicitement l'autre (`test_worker_a_and_worker_b_
sharing_one_build_is_explicit_not_implicit`).

## 5. Fichier Compose de release — vérifié empiriquement, pas supposé

`services/rag-engine/infra/docker-compose.production-release.yml` (nouveau) :
retire `build:` de chacun des trois services `build:`-based et le
remplace par `image: ${...:?requis}`.

**Constat empirique important, avant d'écrire le fichier final :** fournir
seulement `image:` dans un overlay Compose **ne retire pas** `build:` —
Docker Compose fusionne les deux clés, et `docker compose up` peut encore
choisir de construire localement. Testé directement (Docker Compose
v5.4.0) :

```
$ docker compose -f base.yml -f override_image_only.yml config
services:
  ingestor:
    build: {...}       # <- toujours présent
    image: ghcr.io/...
```

Le tag `!reset null` de Docker Compose retire réellement la clé :

```
$ docker compose -f base.yml -f override_with_reset.yml config
services:
  ingestor:
    image: ghcr.io/...  # <- build: absent
```

**Vérifié ensuite contre les vrais fichiers du dépôt** (pas seulement une
fixture synthétique), en fournissant des valeurs factices pour toutes les
variables `:?requis` (secrets/DSN inclus, aucun n'a de rapport avec les
images) :

```
$ docker compose \
    -f docker-compose.v2.yml \
    -f docker-compose.production-workers.yml \
    -f docker-compose.production-release.yml \
    config
# (avec les 25 variables requises factices)
exit=0
ingestor -> build present: False | image: ghcr.io/cyranoaladin/rag-ingestor@sha256:1111...
multilevel-worker-a-production -> build present: False | image: ghcr.io/.../rag-multilevel-worker-production@sha256:2222...
multilevel-worker-b-production -> build present: False | image: ghcr.io/.../rag-multilevel-worker-production@sha256:2222...
```

`COMPOSE_PRODUCTION_RELEASE_VERIFIED_AGAINST_REAL_FILES=true`

## 6. Workflow `.github/workflows/production-image-provenance.yml`

```
PRODUCTION_IMAGE_WORKFLOW=.github/workflows/production-image-provenance.yml
IMAGE_PROVENANCE_PROTOCOL=NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1
```

- **Déclencheur** : `workflow_dispatch` uniquement — jamais automatique
  sur push/PR. `if: github.ref == 'refs/heads/main'` en double garde
  (condition de job + refus explicite en premier step) : ce workflow ne
  construit jamais depuis une PR non mergée.
- **Permissions** : `contents: read`, `packages: write` — rien de plus.
- **Actions tierces épinglées par SHA complet**, pas par tag — même
  discipline que `trusted-human-review.yml`/`_produce-h2-evidence.yml`
  (`actions/checkout`, `actions/upload-artifact` : mêmes SHA déjà utilisés
  ailleurs dans ce dépôt ; `docker/setup-buildx-action`,
  `docker/login-action`, `docker/build-push-action` : SHA résolus depuis
  les tags stables les plus récents via l'API GitHub réelle au moment de
  ce lot, jamais devinés).
- **BUILD/PUSH seulement.** Aucune étape de déploiement, aucun contact
  avec le serveur cible.
- Construit `ingestor` (`Dockerfile.ingestor-v2`) et
  `multilevel-worker-production` (`Dockerfile.multilevel-worker-production`,
  un seul build pour les deux services), plateforme `linux/amd64` (seule
  plateforme réelle du serveur cible — hôte unique, ADR-0036).
  `provenance: true`, `sbom: true` sur `docker/build-push-action` :
  attestations officielles de la build, pas une signature maison
  (instruction humaine §9 : « aucune cryptographie artisanale »).
- **Ne signe pas** `ProductionReadinessManifest` — la clé
  `prod-readiness-v1-2026-08-13` n'entre jamais dans ce workflow, ni dans
  GHCR, ni dans une image, ni dans un artefact. Ce workflow ne produit que
  des faits ; le signer offline (PR #100, séparé, hors ligne) les
  consomme plus tard.
- Assemble et publie `NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1` en artefact
  GitHub (`actions/upload-artifact`, rétention 90 jours) : `protocol_
  version`, `repository`, `source_commit_sha`/`source_tree_sha` (dérivés
  de `git rev-parse`, jamais affirmés), `platform`, `workflow_path`/
  `workflow_run_id`/`workflow_run_attempt`/`workflow_ref`, `built_at`, et
  par service : `source_kind`, `build_context`, `dockerfile`,
  `dockerfile_sha256`, `image_repository`, `image_digest` (sortie native
  `docker/build-push-action`, jamais recalculée à la main).

## 7. Module de vérification `deployment_image_inventory.py`

Nouveau, dans `services/rag-engine/scripts/` (même service que le signer
— aucun import cross-service). Fonction publique
`verify_application_image_provenance(...)` : dérive
`{service_name: "repo@sha256:..."}` depuis un run GitHub réel et vérifié,
**jamais** depuis une saisie opérateur libre.

Chaîne de vérification, chaque maillon confronté à sa source d'autorité :

1. Le run (`gh api repos/<repo>/actions/runs/<id>`) : chemin de workflow
   **canonique exact** (`trusted-human-review.yml` ne peut jamais servir
   de provenance d'image — refusé par construction, pas par convention) ;
   même repository ; déclenché par `workflow_dispatch` (pas `push`, pas
   un autre événement) ; `status=completed`/`conclusion=success` ; même
   `head_sha` que le commit signé.
2. L'artefact (`gh run download`, jamais un appel manuel à l'API
   zip/archive) : même protocole, même repository, même
   `source_commit_sha`/`source_tree_sha`, même `workflow_run_id`, même
   `workflow_path`, plateforme supportée.
3. Chaque service : `source_kind=build`, `image_repository` valide,
   `image_digest` strictement `sha256:<64hex>` (jamais un tag mutable,
   jamais absent), `dockerfile_sha256` présent.

Toute frontière réseau (`github_api_get`, `download_artifact`) est
**injectée par l'appelant** — deux implémentations par défaut fournies
(`gh_api_get`, `download_artifact_via_gh`, toutes deux `gh`, même
transport que le reste de cette mission), jamais exercées contre le
réseau réel dans les tests.

**Intégration à PR #100 : différée, pas faite ici.** Instruction humaine
explicite (§1) : ne pas toucher PR #100 pendant que ce lot avance. Le
câblage (`--application-image` remplacé par `--application-image-
provenance-run-id`, appel à `verify_application_image_provenance` dans
`assemble_and_sign`) est un commit séparé sur la branche PR #100, après
merge de ce lot — §28 de l'instruction humaine.

## 8. Tests — résultats exacts

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests/test_deployment_image_inventory.py -v
23 passed in 0.14s

$ .venv/bin/python -m ruff check scripts/deployment_image_inventory.py tests/test_deployment_image_inventory.py
All checks passed!

$ PYTHONPATH=src .venv/bin/python -m mypy scripts/deployment_image_inventory.py
Success: no issues found in 1 source file

$ python3 -c "import yaml; yaml.safe_load(open('.github/workflows/production-image-provenance.yml'))"
parsed OK

$ bash scripts/check-governance-locks.sh
Governance locks: baseline=18, config=18
OK: all governance locks match baseline (18 keys verified).

$ gitleaks detect --source .github/workflows/production-image-provenance.yml --no-git
no leaks found
$ gitleaks detect --source services/rag-engine/scripts/deployment_image_inventory.py --no-git
no leaks found
$ gitleaks detect --source services/rag-engine/tests/test_deployment_image_inventory.py --no-git
no leaks found
$ gitleaks detect --source services/rag-engine/infra/docker-compose.production-release.yml --no-git
no leaks found
```

Couverture adversariale (23 tests) : run/inventaire concordants →
digests dérivés corrects ; téléchargement du bon artefact pour le bon
run ; **chemin de workflow erroné → refusé** ; **repository erroné →
refusé** ; **déclenchement autre que `workflow_dispatch` → refusé** ;
**run échoué → refusé** ; **run en cours → refusé** ; **`head_sha` ≠
commit signé → refusé** ; **artefact absent → refusé** ;
**`protocol_version` erroné → refusé** ; **`repository`/
`source_commit_sha`/`source_tree_sha`/`workflow_run_id` de l'inventaire ≠
ceux attendus → refusés** ; **plateforme non supportée → refusée** ;
**JSON malformé → refusé** ; **aucun service déclaré → refusé** ;
**`source_kind=upstream` sur un service applicatif → refusé** ; **tag
mutable au lieu d'un digest → refusé** ; **digest absent → refusé** ;
**`dockerfile_sha256` absent → refusé** ; **nom de repository d'image
invalide → refusé** ; **Worker B absent de l'inventaire → n'apparaît pas
dans les digests dérivés** (la relation service→digest reste explicite,
jamais devinée).

Chaque refus critique prouvé par mutation (liaison `head_sha`, format du
digest) : régression injectée → test réagit pour la raison attendue ;
régression retirée → suite repassée verte (23/23).

## 9. Hors périmètre de ce lot — signalé, pas contourné

```
GITHUB_ENVIRONMENT_PROTECTION_CONFIGURED=false
NEXUS_DEPLOYER_ACCOUNT_PROVISIONED=false
DEPLOY_WRAPPER_IMAGE_VERIFICATION=false
KEY_ROTATION_POLICY_IMPLEMENTED=false
MANIFEST_TRANSPARENCY_LOG_IMPLEMENTED=false
LEGACY_DEPLOY_SCRIPT_DEPRECATED=false
IMAGES_ACTUALLY_BUILT_AND_PUSHED=false
```

ADR-0036 anticipe explicitement plusieurs de ces éléments comme des
travaux « phase B » séparés (rotation des clés, transparence des
manifestes, dépréciation du script legacy) — non traités ici, non
nécessaires pour débloquer `APPLICATION_IMAGE_PROVENANCE_VERIFIED` côté
PR #100. Le renforcement du wrapper de déploiement hôte (§15 de
l'instruction humaine — vérification du digest avant `compose up`,
jamais de `docker.sock` monté dans les workers) reste un lot distinct,
avec sa propre preuve contre le serveur réel — pas simulable depuis ce
dépôt seul sans y toucher, et `LIVE_MUTATIONS_ALLOWED=false` l'interdit
ici.

## 10. Booléens finaux

```
REGISTRY_SELECTED=ghcr.io/cyranoaladin
REGISTRY_AUTH_MODEL=GITHUB_TOKEN
PRODUCTION_BUILD_SERVICES=ingestor,multilevel-worker-a-production,multilevel-worker-b-production
PRODUCTION_UPSTREAM_SERVICES=pgvector,prometheus
PRODUCTION_IMAGE_WORKFLOW=.github/workflows/production-image-provenance.yml
IMAGE_PROVENANCE_PROTOCOL=NEXUS-DEPLOYMENT-IMAGE-INVENTORY-V1
APPLICATION_IMAGES_BUILT_FROM_EXACT_GIT_SHA=true   # mécanisme ; pas encore exécuté (§8/§11)
APPLICATION_IMAGES_IMMUTABLE_BY_DIGEST=true
COMPOSE_PRODUCTION_RELEASE_VERIFIED_AGAINST_REAL_FILES=true
REGISTRY_DIGEST_VERIFIED=false   # aucun push réel encore effectué
DEPLOY_WRAPPER_IMAGE_VERIFICATION=false
PRODUCTION_IMAGES_DEPLOYED=false
LIVE_MUTATIONS_ALLOWED=false
GO_LIVE_READY=false
```

## 11. Prochaines étapes (hors de ce lot, après merge)

1. Trusted-human review + merge de ce lot (HUMAN GATE, section suivante).
2. `gh workflow run production-image-provenance.yml --ref main` sur le SHA
   main réel post-merge → produit les vrais digests.
3. Commit séparé sur la branche PR #100 : câbler
   `verify_application_image_provenance` dans `assemble_and_sign`,
   remplacer `--application-image` par `--application-image-provenance-
   run-id`.
4. Revalidation complète PR #100, nouveau challenge, nouveau HUMAN GATE.
