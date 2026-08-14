# LOT — Correction du gate fail-open dans `production-image-provenance.yml`

## 1. Verdict du lot

`.github/workflows/production-image-provenance.yml` (PR #102, déjà mergé
sur `main`) portait un `if:` de job (`github.ref == 'refs/heads/main'`)
en plus de son refus par étape. Un `if:` de job qui évalue à faux produit
un statut `skipped`, jamais `failure` — un dispatch sur la mauvaise ref
aurait donc laissé le run entier apparaître **vert** (job « skipped »),
jamais rouge, l'étape de refus explicite n'ayant jamais l'occasion de
s'exécuter (le job entier étant sauté avant elle). Corrigé en retirant
le `if:` de job — seul le refus par étape (`exit 1` réel) porte
désormais la garantie fail-closed.

`GO_LIVE_READY=false`. Aucune mutation live, aucun build/push réel
déclenché par ce lot.

## 2. Pourquoi maintenant

Trouvé par ricochet en corrigeant le même défaut dans `promote.yml`
(PR #110) : ce workflow-là portait le même `if:` de job, et la
correction a motivé une recherche du même motif ailleurs dans
`.github/workflows/`. `production-image-provenance.yml` porte
exactement le même défaut, à la ligne 35, depuis son introduction
(PR #102, mergé le 2026-08-13).

## 3. Correction

Retrait du `if: github.ref == 'refs/heads/main'` au niveau du job
`build-and-push`. L'étape existante `Refuse anything but a real main
commit` (`if: github.ref != 'refs/heads/main'`, `exit 1`) porte seule
désormais la garantie — elle s'exécute maintenant systématiquement
(job non sauté), et échoue réellement si la ref est incorrecte.

Aucun autre changement de logique : les étapes de build/push/inventaire
restent identiques.

## 4. Garde-fou de non-régression

Nouveau fichier `scripts/tests/test-production-image-provenance-workflow.py`,
zéro accès réseau/Docker :

- YAML valide.
- Le job `build-and-push` ne porte aucun `if:` de job ; sa première
  étape porte exactement `if: github.ref != 'refs/heads/main'` et
  contient `exit 1`.
- `workflow_dispatch` uniquement (aucun `push`/`pull_request`).
- Aucun secret référencé autre que `secrets.GITHUB_TOKEN` (jeton éphémère
  standard nécessaire pour pousser vers GHCR — jamais une clé de
  signature ou un secret long-vécu) ; aucune référence à une clé privée
  ou à `sign_production_readiness_manifest`, même en commentaire.
- Les trois actions `uses:` restent épinglées par SHA de commit 40-hex.

```
$ python3 -c "import yaml; yaml.safe_load(open('.github/workflows/production-image-provenance.yml'))"
YAML OK

$ python3 -m pytest scripts/tests/test-production-image-provenance-workflow.py -v
5 passed, 7 subtests passed

$ python3 -m ruff check scripts/tests/test-production-image-provenance-workflow.py
All checks passed!
```

**Mutation-testing** : le `if:` de job a été temporairement réintroduit ;
`test_build_and_push_job_has_no_top_level_if_and_fails_closed_on_wrong_ref`
échoue pour la bonne raison (`'if' unexpectedly found in {...}`).
Restauré, suite reverifiée verte (5 passed, 7 subtests).

## 5. Ce que ce lot ne fait jamais

- Ne modifie aucune logique de build/push/inventaire — seul le gate de
  ref est touché.
- Ne déclenche aucun run réel de ce workflow (aucun accès réseau/GHCR/Docker
  dans ce lot).
- Ne modifie pas `packages/contracts`.

## 6. Booléens finaux

```
IMAGE_PROVENANCE_FAIL_OPEN_BUG_FIXED=true
IMAGE_PROVENANCE_REGRESSION_TEST_ADDED=true
IMAGE_PROVENANCE_MUTATION_TESTED=true
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
