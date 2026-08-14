# LOT C — Wrapper de déploiement atomique (ferme la fenêtre TOCTOU, PR #105)

## 1. Verdict du lot

Nouveau script `services/rag-engine/scripts/deploy_verified_release_
cli.py` : un wrapper qui ferme la fenêtre de temps-de-vérification-au-
temps-d'utilisation (TOCTOU) explicitement documentée et acceptée comme
limite dans `verify_release_image_provenance_cli.py` (PR #105, section
« Limite connue et acceptée » de son docstring). Trois phases
strictement séquentielles dans un seul processus : **vérifier** (réutilise
`verify_release_images`, PR #105, et — si fourni — `verify_production_
readiness_manifest`/`require_manifest_matches_release`, PR #100),
**matérialiser une fois** dans un répertoire bundle immuable (fichiers
Compose, JSON résolu, `.env`, manifeste de readiness le cas échéant, plus
un `bundle_manifest.json` recensant le SHA-256 de chaque fichier et
l'identité du bundle), puis **déployer depuis le bundle uniquement**
(`docker compose pull`/`up`, jamais contre `services/rag-engine/infra/*`
de nouveau). `LIVE_MUTATIONS_ALLOWED=false` par défaut — sans `--execute`,
seul le plan est imprimé, aucune commande Docker mutante n'est lancée.
`GO_LIVE_READY` reste `false`. Aucune mutation live exercée dans ce lot.

## 2. Pourquoi maintenant

`verify_release_image_provenance_cli.py` documente lui-même,
explicitement, qu'il ne ferme pas cette fenêtre :

> « Rien n'empêche aujourd'hui que ces fichiers diffèrent de ceux
> vérifiés entre les deux étapes (checkout modifié, `.env` changé).
> Fermer entièrement cet écart demanderait [...] qu'un futur wrapper de
> déploiement consomme un bundle vérifié immuable produit ici — ce
> wrapper n'existe pas encore dans ce dépôt et reste un lot distinct »

Ce lot est ce wrapper. `require_resolved_compose_images_are_pinned()`
(PR #102) porte la même note : « c'est la primitive qu'un futur wrapper
de déploiement hôte doit appeler avant tout `docker compose up` — elle
ne s'appelle jamais elle-même : ce wrapper n'existe pas encore dans ce
dépôt ». Ce lot l'appelle, pour la première fois, depuis un point
d'entrée réel.

## 3. Ce que ce lot ajoute réellement — rien de redéfini

Aucune primitive existante n'est réimplémentée :

- `verify_release_image_provenance_cli.verify_release_images()` (PR
  #105) reste l'unique source de vérité pour « les images Compose
  résolues correspondent-elles à une provenance GitHub Actions
  vérifiée ». Réutilisée telle quelle.
- `nexus_contracts.production_readiness.verify_production_readiness_
  manifest()` / `require_manifest_matches_release()` (PR #100) restent
  l'unique source de vérité pour « ce manifeste de readiness signé est-il
  valide et lié à ce commit ». Réutilisées telles quelles.
- `deployment_image_inventory.gh_api_get`/`make_download_artifact_via_gh`
  (PR #102) restent l'unique frontière réseau par défaut. Réutilisées
  telles quelles.

Ce lot ajoute exactement trois fonctions nouvelles :

1. `verify_readiness_manifest_if_supplied()` — le manifeste de readiness
   est **optionnel** (`--readiness-manifest-file`). Omis, ce wrapper ne
   prouve que la provenance des images et le pinning Compose — jamais un
   feu vert de gouvernance production complet, documenté explicitement
   plutôt que silencieusement sous-entendu. Fourni sans `--trust-anchor-
   file`, refusé (`DeploymentWrapperError`, jamais un manifeste consommé
   sans son ancre).
2. `materialize_verified_bundle()` — orchestration : vérifie (phase 1)
   avant d'écrire quoi que ce soit sur disque (phase 2). Un bundle
   partiellement matérialisé pour une release refusée n'existe jamais
   (voir §5, mutation « bundle-already-exists »). Copie les trois
   fichiers Compose (déjà lus via `git show <merge_sha>:<chemin>`, jamais
   depuis le disque non vérifié — réutilise `vri._git_show_bytes`), le
   JSON résolu, le `.env` hôte, et le manifeste de readiness (si fourni)
   dans `bundle_dir`, puis écrit `bundle_manifest.json` (SHA-256 de
   chaque fichier + `bundle_digest` = SHA-256 du document lui-même,
   canonicalisé `sort_keys=True`).
3. `deploy_from_bundle()` — relit `bundle_manifest.json`, **recalcule**
   le SHA-256 de chaque fichier Compose présent dans `bundle_dir` et le
   confronte à celui enregistré (§5, mutation « tampered-bundle ») avant
   toute commande. Sans `--execute` : retourne le plan (liste de
   commandes), n'invoque aucun sous-processus. Avec `--execute` : `pull`
   puis `up -d --remove-orphans`, chacun contre `-f <bundle>/<fichier>...
   --env-file <bundle>/.env` exclusivement — jamais `services/rag-engine/
   infra/*`. Un `pull` en échec interrompt avant tout `up` (§5).

## 4. Limite acceptée, documentée plutôt que devinée

`verify_readiness_manifest_if_supplied()` vérifie la signature, l'ancre,
l'environnement, le verdict du manifeste et sa liaison à `--merge-sha`
(`require_manifest_matches_release(..., release_sha=merge_sha)`) — mais
appelle cette fonction avec `compose_digest=None`, donc **ne confronte
pas** le `compose_digest` signé dans le manifeste au Compose réellement
résolu par ce wrapper.

Raison : au moment où ce lot a été écrit, la sémantique exacte de
`compose_digest` pour un Compose multi-fichiers résolu (single-file
hashé aujourd'hui, en cours de refonte vers le Compose résolu dans un
lot parallèle — PR #100, Section 11 du signer) était activement en
cours de définition ailleurs. Choisir unilatéralement une interprétation
ici aurait risqué de figer une sémantique concurrente à celle que ce
lot parallèle allait établir. **Ceci n'est pas une omission silencieuse** :
c'est une limite documentée dans le docstring du module et ici, avec un
travail de suivi explicite (fermer ce dernier écart une fois la
sémantique de `compose_digest` stabilisée par PR #100 §11).

Quand aucun manifeste n'est fourni du tout, ce wrapper ne prouve que la
provenance des images et le pinning Compose — jamais un feu vert de
gouvernance production complet.

## 5. Mutation-testing des branches de refus

Chaque branche de refus nouvelle a été désactivée temporairement,
confirmée rouge pour la bonne raison, puis restaurée et reconfirmée
verte :

```
1. bundle_dir.exists() → raise  (remplacé par mkdir(exist_ok=True))
   test_existing_bundle_directory_is_never_silently_overwritten
   AVANT fix : "Failed: DID NOT RAISE DeploymentWrapperError"
   APRÈS fix : PASSED

2. digest de fichier bundle tamponné → raise
   test_tampered_bundle_file_is_refused_before_any_subprocess_runs
   AVANT fix : le double run_subprocess est appelé
     ("AssertionError: must never run a subprocess against a
     tampered bundle" — la mutation a laissé passer jusqu'au sous-
     processus, exactement le comportement interdit)
   APRÈS fix : PASSED

3. trust_anchor_raw is None → raise (remplacé par pass)
   test_manifest_without_trust_anchor_is_refused
   AVANT fix : AttributeError non gérée dans le contrat partagé
     ('NoneType' object has no attribute 'decode') — un manifeste
     aurait été présenté à parse_production_readiness_trust_anchor
     avec une ancre absente plutôt que refusé proprement
   APRÈS fix : PASSED

4. pull.returncode != 0 → raise (retrait du contrôle)
   test_pull_failure_aborts_before_up_is_ever_invoked
   AVANT fix : "assert 2 == 1" — la commande `up` est bien invoquée
     après un `pull` en échec, exactement le comportement interdit
   APRÈS fix : PASSED
```

## 6. Vérification empirique

```
$ cd services/rag-engine && .venv/bin/python -m pytest \
    tests/test_deploy_verified_release_cli.py -q
....................                                                     [100%]
20 passed

$ .venv/bin/python -m pytest \
    tests/test_deploy_verified_release_cli.py \
    tests/test_verify_release_image_provenance_cli.py \
    tests/test_deployment_image_inventory.py -q
............................................................................
84 passed

$ .venv/bin/python -m ruff check scripts/deploy_verified_release_cli.py \
    tests/test_deploy_verified_release_cli.py
All checks passed!

$ .venv/bin/python -m mypy scripts/deploy_verified_release_cli.py
Success: no issues found in 1 source file
```

## 7. Ce que ce lot ne fait jamais

- Ne construit ni ne pousse aucune image.
- Ne lance aucune commande mutante sans `--execute` explicite ; les
  tests n'exercent jamais le vrai binaire `docker` ni un vrai `git show`
  contre un dépôt réel — toutes les frontières (`github_api_get`/
  `download_artifact`/`run_docker_compose_config`/`run_subprocess`) sont
  des doubles injectés.
- Ne modifie pas `packages/contracts` (aucune nouvelle forme de contrat
  requise — les fonctions existantes de `production_readiness.py`
  suffisent).
- Ne recalcule aucun verdict de gouvernance pédagogique (ADR-0001).
- N'a été exécuté contre aucun hôte, registre ou base de données réels —
  `LIVE_MUTATIONS_ALLOWED=false` de bout en bout dans ce lot.

## 8. Limitations restantes

- `compose_digest` du manifeste de readiness non recoupé — voir §4,
  dépend de la stabilisation de PR #100 §11.
- Aucun manifeste de readiness réel signé n'existe encore dans ce dépôt
  (dépend de PR #100, dont `PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE`
  reste `false` — voir `docs/reports/lot_h2b_production_readiness_
  signing_tool.md`) : ce wrapper n'a donc jamais été exercé contre un
  manifeste réel, seulement contre des manifestes de test signés avec
  une graine triviale.
- N'a jamais été exécuté contre un vrai `docker compose config`/`pull`/
  `up` — toutes les frontières processus sont des doubles en test. Une
  exécution réelle nécessite un hôte avec Docker, un `.env` de production
  réel, et une autorisation de cutover qui n'existe pas encore.
- Reste un point d'entrée CLI construit mais non encore branché à un
  runbook opérationnel (`docs/runbooks/go_live.md`) — cela reste un
  travail de suivi.

## 9. Booléens finaux

```
ATOMIC_DEPLOYMENT_WRAPPER_BUILT=true
TOCTOU_GAP_CLOSED_BY_WRAPPER=true
WRAPPER_EXERCISED_AGAINST_REAL_DOCKER=false
WRAPPER_EXERCISED_AGAINST_REAL_READINESS_MANIFEST=false
COMPOSE_DIGEST_CROSS_CHECK_WITH_READINESS_MANIFEST=false   # §4, dépend de PR #100 §11
CONTRACTS_MODIFIED=false
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
