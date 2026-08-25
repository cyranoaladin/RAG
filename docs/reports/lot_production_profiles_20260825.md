# Lot — profils de production et set final 2026-2027

## Périmètre

Baseline :

```text
CURRENT_MAIN_SHA=3f0317e91c9ac8eff8ff1089d100a25f7c875793
CURRENT_MAIN_TREE_SHA=5bc5234ea395486810638d553c3c9bc2e7d57d75
```

Ce lot matérialise exclusivement les décisions P01–P24, les profils et
placements production, le set final après profile gate et les preuves
opératoires parallèles. Il ne crée aucune autorisation réelle et n'écrit pas
dans la base de production.

## Résultat du profile gate

```text
FINAL_PRE_PROFILE_ELIGIBLE_COUNT=72
FINAL_PRE_PROFILE_ELIGIBLE_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
P01_P10_CONTENT_COUNT=11
P01_P10_PRODUCTION_PROFILE_COUNT=10
P01_P10_SCOPE_DRIFT=0
P24_CONTENTS=5
P24_PROFILE_MATCH=5
P11_P23_INPUT_CONTENT_COUNT=56
P11_P23_EXACTLY_GROUNDED_COUNT=10
FINAL_PROFILE_REVIEW_REQUIRED_COUNT=46
FINAL_PRODUCTION_ELIGIBLE_COUNT=26
FINAL_PRODUCTION_ELIGIBLE_SET_SHA256=fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0
FINAL_AUTHORITY_REQUIRED_COUNT=26
FINAL_AUTHORITY_REQUIRED_SET_SHA256=fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0
```

Les 46 résiduels ont la disposition finale
`MOVE_TO_REVIEW_REQUIRED_FOR_THIS_RELEASE`. Le recalcul déterministe depuis le
ledger versionné donne :

```text
UNIQUE_CONTENTS=2582
INGEST_CANDIDATE=26
REVIEW_REQUIRED=2445
QUARANTINE=2
ARCHIVE_ONLY=19
EXCLUDE=53
UNSUPPORTED=37
UNACCOUNTED_CONTENTS=0
TERMINAL_DISPOSITION_COVERAGE=100%
```

La preuve est
`docs/reports/terminal_disposition_summary_20260825.json` (SHA-256
`41ed6ff6ef160b5fedd36b2316dd91bed1f1b8be223958eec8587b9f30e4571a`).

## Profils, release registry et placements

- les 10 profils staging P01–P10 ont été promus avec dimensions et versions
  sémantiques inchangées ;
- le profil P24 existant reste l'unique profil philosophie Terminale et son
  placement est désormais consommable par le release registry ;
- 10 contenus P11–P23 ont été grounded sur preuve primaire ;
- 18 profils/scopes production couvrent exactement les 26 SHA finaux ;
- la matière philosophie conserve `BOEN_special_8_2019-07-25`, cohérent avec
  le profil et la preuve source.

```text
PRODUCTION_PROFILE_MANIFEST_VALID=true
PROFILE_EXACT_MATCH_COUNT=26
PROFILE_NO_MATCH_COUNT=0
PROFILE_AMBIGUOUS_COUNT=0
RELEASE_SCOPE_PLACEMENT_CONTENT_COUNT=26
RELEASE_SCOPE_PLACEMENT_GAP=0
RELEASE_SCOPE_PLACEMENT_EXTRA=0
RELEASE_SCOPE_PLACEMENT_AMBIGUOUS=0
```

Identités :

```text
PROFILE_SOURCE_MANIFEST_SHA256=0ff9f6ff2676273c1a21e32d82851a8033f45313b3009d2a3506f35d25e8379e
PROFILE_MANIFEST_DIGEST=57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c
FINAL_PROFILE_MATRIX_SHA256=10316991c8a2b0fa65aae6c725f77a3ac38abd985f9a80666e30d2c1b78e9b87
RELEASE_SCOPE_PLACEMENT_SHA256=b1a36aef251d05f0098bfe88d7eae45b36333452f1613741e15dc6a89de75315
PLACEMENT_SOURCE_COMMIT=21a0e7efe01deb8aff14386220f8c976d81cd856
PLACEMENT_SOURCE_TREE=d2d7b81d4d80bd61cc7a1c6b0efac66282805b3c
PRODUCTION_RELEASE_SHA256=7ce2cfcdae1ba92d51ef17bc8b8edfccac4bd8f1fea5ad0efa9abe4edd8aec73
```

Le runtime refuse les clés JSON dupliquées, les collisions inter-sujets, les
digests registry/agrégat incohérents et toute résolution qui ne trouve pas
exactement un scope `(collection, content_sha256)`.

## Préparatifs parallèles

### Docker V2

La PR technique #132 porte le harnais séparé et la preuve réelle au HEAD
`c98ad5e62b7e050feed0961cc6bef8651a7f08a9`, tree
`4f265f3dee88079814e80469f313959e930314a4`. Tous les verdicts imposés sont
verts ou à zéro. Deux revues contradictoires ont conclu `APPROVE`. Le merge
reste bloqué sur la vraie review GitHub exact-head.

### Audit, backup et restore DB

```text
PROD_DB_TARGET_VERIFIED=true
PROD_DB_WRITES=0
PROD_DB_MIGRATION_PLAN_READY=true
FRESH_BACKUP_CREATED=true
BACKUP_CHECKSUM_VERIFIED=true
RESTORE_REHEARSAL_PASS=true
PRODUCTION_DB_MUTATED=false
```

La cible est `rag_pgvector/ragdb` sur `127.0.0.1:5436`. Le PostgreSQL natif
étranger sur `127.0.0.1:5433` n'a été ni interrogé ni muté. Le dump a pour
SHA-256
`e9efc0c5b4e85a680eb8ed0497ccaeaaa987e0e40a6498b23e12122b47821d8f`.
Le transcript nettoyé et versionné a pour SHA-256
`ac1b171d9cd907c4b86ee1db344f2a1b54381302ea0777619da3f76e880ca81a`.

### Environment GitHub

```text
PRODUCTION_ENVIRONMENT_EXISTS=true
REQUIRED_REVIEWER_CONFIGURED=true
MAIN_ONLY=true
SELF_REVIEW_PREVENTED=true
ADMIN_BYPASS_DISABLED=true
WAIT_TIMER=0
ENVIRONMENT_SECRETS=0
```

La configuration a été appliquée puis relue en direct ; preuve SHA-256
`55543e699dfaf5e5692ccac6b4567deffce605c6c37c487fa5b78c7ec63b31e4`.

PR #96 a été fermée comme superseded. PR #98 reste uniquement une référence
de preuve et ne sera fermée qu'après création de la nouvelle autorisation P24.

## Incident de confidentialité à traiter avant cutover

Pendant l'identification de la cible DB, une première commande d'inventaire
trop large a rendu dans la sortie locale des arguments de démarrage contenant
des identifiants Redis d'un service étranger. Aucune valeur n'a été copiée
dans Git, les preuves ou ce rapport. Les identifiants concernés doivent être
rotatés par l'opérateur avant le cutover ; aucune tentative de réutilisation
n'a été faite.

## Vérifications

```text
PROFILE_RELEASE_TARGETED_TESTS=PASS
PROFILE_PLACEMENT_EXACT_TREE_TESTS=PASS
CONTRACT_TARGETED_TESTS=PASS
RUNTIME_PROFILE_AND_RELEASE_TESTS=PASS
PROFILE_MUTATION_AND_ADVERSARIAL_TESTS=PASS
CONTRACTS_FULL_TESTS=467 passed
RAG_PEDAGO_FULL_TESTS=2802 passed, 2 skipped
RAG_ENGINE_FULL_NON_INTEGRATION_TESTS=PASS
COCKPIT_TESTS=179 passed
RUFF_CONTRACTS=PASS
RUFF_RAG_PEDAGO=PASS
RUFF_RAG_ENGINE=PASS
GOVERNANCE_LOCKS=PASS (18/18)
GOVERNANCE_GUARD_MUTATIONS=PASS (16/16)
REPOSITORY_CONTROLS=PASS
CI_TOPOLOGY_MUTATIONS=PASS (22/22)
GITLEAKS_DIFFERENTIAL=PASS (8.21.2, 16 commits, 0 leak)
FRESH_CONTRADICTORY_PROFILE_REVIEWS=PENDING
GITHUB_CI=PENDING
```

Les commandes mypy canoniques restent rouges sur la baseline : 10 erreurs
dans `scrapers/fetch.py`, 3 dans le runtime engine et 1 dans
`review_binding.py`. Les blob IDs de ces cinq fichiers sont identiques entre
`origin/main` et ce lot ; aucun fichier modifié par cette branche n'apparaît
dans les erreurs. Un contrôle supplémentaire incluant les scripts historiques
de `rag-pedago` retrouve 43 erreurs dans 11 autres fichiers également
inchangés.

Le script agrégé `scripts/ci-local.sh` n'a pas pu être mené à terme dans le
venv éphémère : la résolution des dépendances sur le réseau local plafonnait à
environ 50 kB/s. Il n'est donc pas déclaré vert. Les suites et garde-fous
ci-dessus ont été exécutés directement ; la preuve clean-room finale reste le
run GitHub du HEAD exact de la PR.

## Gates non franchis par ce lot

```text
REAL_AUTHORIZATIONS_CREATED=false
REAL_CAMPAIGN_EXECUTED=false
REAL_GOVERNED_REPUBLISH_EXECUTED=false
REAL_H2_GATE_PASS=false
AUTHORIZED=0
REPUBLISHED=0
H2_COVERED=0
INGESTED=0
API_DISCOVERABLE=0
PRODUCTION_READY=false
GO_LIVE_READY=false
RAG_PRODUCTION_DEPLOYED=false
```

Le prochain gate est la vraie `trusted-human-review/head-pinned` de la PR
profils production. Aucune identité GitHub humaine n'est simulée.
