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
   le SHA-256 de chaque fichier du bundle (tous, pas seulement les
   Compose — §10 item 5) et le confronte à celui enregistré (§5,
   mutation « tampered-bundle ») avant toute commande. Sans `--execute` :
   retourne le plan (liste de commandes), n'invoque aucun sous-processus.
   Avec `--execute` : `pull` puis `up -d`, chacun contre une liste
   explicite de services (§10 item 7) et `-f <bundle>/<fichier>...
   --env-file <bundle>/.env` exclusivement — jamais `services/rag-engine/
   infra/*`, jamais un nettoyage des conteneurs orphelins (§10 item 1).
   Un `pull` en échec interrompt avant tout `up` (§5).

## 4. Limite acceptée au premier round — fermée au round 2 (§10 item 3)

Au premier round, `verify_readiness_manifest_if_supplied()` appelait
`require_manifest_matches_release(..., compose_digest=None)` — la
sémantique exacte de `compose_digest` pour un Compose multi-fichiers
résolu était encore activement en cours de définition dans un lot
parallèle (PR #100, Section 11 du signer), pas encore mergée sur `main`
au moment où ce lot a été écrit. Choisir unilatéralement une
interprétation ici aurait risqué de figer une sémantique concurrente à
celle que ce lot parallèle allait établir.

**Fermé au round 2** (§10 item 3) : `verify_release_image_provenance_
cli.canonical_resolved_compose_bytes` — la même convention de
canonicalisation que celle établie par PR #100 Section 11 — est
désormais la primitive partagée utilisée par ce wrapper pour calculer le
digest réel et le lier via `compose_digest=<digest réel>`.

Quand aucun manifeste n'est fourni du tout (mode plan-only, jamais
`--execute` — voir §10 item 2), ce wrapper ne prouve que la provenance
des images et le pinning Compose — jamais un feu vert de gouvernance
production complet.

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
- **`deploy_from_bundle()` ne détecte que l'incohérence interne du
  bundle, jamais une falsification externe cohérente.** Il recalcule le
  SHA-256 de chaque fichier Compose présent dans `bundle_dir` et le
  confronte à `bundle_manifest.json` — mais ce fichier de référence vit
  dans le même répertoire que les fichiers qu'il authentifie. Un
  attaquant disposant d'un accès en écriture à `bundle_dir` pourrait
  altérer un fichier Compose ET l'entrée correspondante de
  `bundle_manifest.json` de façon cohérente, sans qu'aucun contrôle ne
  le détecte : ce mécanisme protège contre la divergence accidentelle
  (corruption, écrasement partiel), pas contre falsification délibérée
  avec accès disque. Ceci correspond à la même frontière de confiance
  déjà explicitement acceptée par `verify_release_image_provenance_cli.
  py` (PR #105, section « Frontière de confiance acceptée ») : le
  système de fichiers local est la racine de confiance, jamais prouvé
  lui-même. Non exploitable via ce CLI aujourd'hui : `main()` enchaîne
  toujours matérialisation et déploiement dans un seul process, sans
  fenêtre externe entre les deux — mais `deploy_from_bundle()` reste
  appelable séparément par un futur appelant qui réutiliserait un bundle
  déjà matérialisé, sans que ce cas soit couvert par un test dédié.

## 10. Second round — neuf constats réels, revue par l'opérateur

Un second round de revue (l'opérateur lui-même, Codex/cubic étant à
quota épuisé ce mois-ci) sur la version poussée a trouvé neuf défauts
réels. Tous fermés :

1. **`--remove-orphans` retiré du chemin de mutation.** L'hôte cible
   (`korrigo`) exécute le projet Compose `infra` partagé avec une stack
   non-RAG — ce drapeau y aurait détruit des conteneurs étrangers. Un
   test statique (`TestNoRemoveOrphansAnywhereInTheModule`) confirme
   l'absence complète de la chaîne dans le module (docstring reformulée
   sans la citer littéralement, pour que le test reste un vrai
   grep-négatif et non un faux-positif sur sa propre documentation).
2. **`--execute` refuse désormais sans manifeste de readiness signé ET
   son ancre.** La seule preuve de provenance d'image ne suffit plus à
   autoriser une mutation réelle — vérifié avant tout travail (aucun
   appel réseau, aucune écriture de bundle) dans `main()`.
3. **`compose_digest=None` a disparu.** `verify_readiness_manifest_if_
   supplied` calcule désormais le digest du Compose RÉELLEMENT résolu
   (`verify_release_image_provenance_cli.canonical_resolved_compose_
   bytes` — nouvelle primitive partagée, extraite de ce que PR #100
   Section 11 avait défini pour le signer, puisque cette branche a été
   développée avant que PR #100 ne soit mergée sur `main` ; les deux
   outils partagent maintenant la même fonction plutôt que deux
   implémentations indépendantes qui auraient pu diverger) et le lie via
   `require_manifest_matches_release(..., compose_digest=<digest réel>)`.
4. **Résolution Compose une seule fois.** `verify_release_image_
   provenance_cli.verify_release_images()` (PR #105) retourne désormais
   un `VerifiedReleaseMaterialization` (Compose résolu, images épinglées,
   octets source Compose, octets `.env` — lus UNE SEULE fois puis
   figés dans un instantané avant résolution — et document de provenance
   d'image déjà vérifié). Ce wrapper matérialise son bundle
   exclusivement depuis cet objet : plus de second appel à
   `run_docker_compose_config`, plus de seconde lecture de `.env`.
   `deployment_image_inventory.verify_application_image_provenance` a
   été scindée en une fonction interne (`fetch_and_verify_image_
   provenance_document`, retourne le document brut déjà vérifié) et une
   enveloppe fine préservant le comportement/la signature existants pour
   ses appelants historiques (aucune régression sur
   `test_deployment_image_inventory.py`, 42/42 toujours verts, inchangés).
5. **`deploy_from_bundle()` vérifie désormais TOUS les fichiers du
   bundle**, pas seulement les trois Compose : `.env`,
   `resolved-compose.json`, `image-provenance-evidence.json`,
   `readiness-manifest.json` (si présent) — chacun rehaché et confronté
   à `bundle_manifest.json`. Un fichier supplémentaire non recensé dans
   le manifeste est également refusé (`unexpected file`). Le manifeste
   de bundle lui-même est validé structurellement (`protocol_version`,
   `repository`, `merge_sha` — refuse un bundle matérialisé pour un
   autre commit que celui en cours de déploiement) avant toute
   confrontation de fichier.
6. **La preuve de provenance d'image est désormais matérialisée dans le
   bundle**, pas seulement les digests qui en sont dérivés :
   `image-provenance-evidence.json` (le document d'inventaire brut, déjà
   structurellement vérifié) est copié et hashé comme tout autre fichier
   du bundle — auditable hors ligne, sans recontacter GitHub Actions.
7. **Liste de services explicite, jamais un `docker compose up` sans
   arguments.** `explicit_services` (dérivée directement des clés du
   Compose résolu VÉRIFIÉ — jamais une liste figée à la main qui
   pourrait diverger silencieusement) est enregistrée dans
   `bundle_manifest.json` et passée explicitement à `pull`/`up`.
8. **Vérification de labels avant toute mutation réelle.**
   `require_no_foreign_container_collision` (frontière `list_running_
   containers` injectée, jamais un vrai `docker ps` en test unitaire)
   refuse si un service ciblé est déjà géré par un conteneur dont le
   `working_dir` Compose diverge de celui de ce bundle — jamais un nom
   de projet seul (partagé avec une stack étrangère sur l'hôte cible).
   Ne supprime ni n'arrête jamais rien lui-même.
9. **Rehearsal Docker réel, isolé.** `TestRealDockerRehearsal` (skip si
   Docker absent) résout les trois vrais fichiers Compose commités avec
   de vraies valeurs `.env` factices dérivées dynamiquement (réutilise
   `test_verify_release_image_provenance_cli._dummy_compose_env`, jamais
   une liste recopiée à la main), matérialise un vrai bundle, prouve le
   dry-run et le refus sur falsification avec de vrais octets — jamais
   contre `docker compose pull`/`up` réels (`run_subprocess` reste un
   double y compris dans ce test, pour ne jamais risquer un registre
   réel depuis la suite).

**Un défaut de test trouvé et corrigé par le mutation-testing
lui-même** (item 2) : la première version de
`test_execute_without_readiness_manifest_is_refused_before_any_work`
n'affirmait que `"REFUSED" in stderr` — cette chaîne apparaît aussi bien
pour le refus précoce voulu que pour n'importe quel refus tardif
générique (git/réseau en échec), donc désactiver le garde-fou laissait
le test vert pour la mauvaise raison. Corrigé en affirmant le texte
précis du refus précoce.

```
$ .venv/bin/python -m pytest tests/test_deploy_verified_release_cli.py \
    tests/test_verify_release_image_provenance_cli.py \
    tests/test_deployment_image_inventory.py -q
139 passed

$ .venv/bin/python -m ruff check scripts/ \
    tests/test_deploy_verified_release_cli.py \
    tests/test_verify_release_image_provenance_cli.py \
    tests/test_deployment_image_inventory.py
All checks passed!

$ .venv/bin/python -m mypy scripts/deploy_verified_release_cli.py \
    scripts/verify_release_image_provenance_cli.py \
    scripts/deployment_image_inventory.py
Success: no issues found in 3 source files
```

Quatre mutations ciblées, chacune rouge pour la bonne raison puis
restaurée verte : garde `--execute` sans manifeste/ancre (§2), contrôle
de collision de labels (§8), liaison `merge_sha` du bundle, liaison
`compose_digest` du manifeste (§3).

**Limite non fermée dans ce round, documentée §8ter** :
`deploy_from_bundle()` reste self-consistency-only pour la détection de
falsification (voir §8bis existant) — un attaquant avec accès disque au
bundle pourrait toujours co-altérer un fichier et son entrée de
manifeste. Non aggravé ni corrigé par ce round.

## 8ter. Ce que ce round ne ferme pas

- La frontière de confiance disque (§8, déjà documentée) reste
  inchangée : self-consistency seulement.
- Aucun vrai `docker compose up`/`pull` n'a été exécuté par ce round —
  `run_subprocess` reste un double, y compris dans le rehearsal réel
  (item 9 ci-dessus).
- Aucun manifeste de readiness réel signé n'existe encore (dépend de
  PR #100, toujours `PRODUCTION_READINESS_SIGNING_TOOL_COMPLETE=false`).
- Le point d'entrée CLI n'est toujours pas branché à un runbook
  opérationnel.

## 9. Booléens finaux

```
ATOMIC_DEPLOYMENT_WRAPPER_BUILT=true
TOCTOU_GAP_CLOSED_BY_WRAPPER=true
RESIDUAL_TOCTOU_MICRO_WINDOW_CLOSED=true
REMOVE_ORPHANS_ABSENT=true
EXECUTE_REQUIRES_READINESS_MANIFEST=true
COMPOSE_DIGEST_BOUND_TO_READINESS_MANIFEST=true
ALL_BUNDLE_FILES_VERIFIED_BEFORE_MUTATION=true
IMAGE_PROVENANCE_EVIDENCE_MATERIALIZED=true
EXPLICIT_SERVICE_TARGETING=true
LABEL_SAFETY_CHECK_BEFORE_MUTATION=true
BUNDLE_TAMPER_DETECTION_TRUST_BOUNDARY=SELF_CONSISTENCY_ONLY   # §8, inchangé
WRAPPER_EXERCISED_AGAINST_REAL_DOCKER=true   # résolution/matérialisation seulement, §10 item 9 -- jamais pull/up réels
WRAPPER_EXERCISED_AGAINST_REAL_READINESS_MANIFEST=false
CONTRACTS_MODIFIED=false
GO_LIVE_READY=false
LIVE_MUTATIONS_ALLOWED=false
```
