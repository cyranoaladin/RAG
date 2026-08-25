# Master Go-Live State — candidats d’autorisation production

Ce document conserve le résultat du profile gate fusionné et décrit les
candidats d'autorisation construits depuis cette baseline `main` figée. Les
candidats ne deviennent pas des autorisations effectives avant la vraie revue
GitHub exact-head et les `ReviewBinding` signés.

```text
STATE_GENERATED_AT=2026-08-25T08:38:19Z
STATE_OBSERVED_AT_MAIN_SHA=3566cafb44138d6a7f00296dc0654257f9bf0ad6
STATE_OBSERVED_AT_MAIN_TREE_SHA=8c5081a52096d531f1bd027790e600eb83b05bd5
PR129_MERGED=true
PR130_MERGED=true
PR131_MERGED=true
PR133_PRODUCTION_PROFILES_MERGED=true
```

## 1. Set final après profile gate

Le set historique de 72 contenus est désormais nommé
`FINAL_PRE_PROFILE_ELIGIBLE`. Le producteur versionné
`services/rag-pedago/scripts/recompute_final_release_set.py` applique le set
canonique des profils de production et déplace fail-closed les 46 résiduels
vers `REVIEW_REQUIRED`.

```text
FINAL_PRE_PROFILE_ELIGIBLE_COUNT=72
FINAL_PRE_PROFILE_ELIGIBLE_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
FINAL_PRODUCTION_ELIGIBLE_COUNT=26
FINAL_PRODUCTION_ELIGIBLE_SET_SHA256=fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0
FINAL_PROFILE_REVIEW_REQUIRED_COUNT=46
FINAL_AUTHORITY_REQUIRED_COUNT=26
FINAL_AUTHORITY_REQUIRED_SET_SHA256=fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0
FINAL_RELEASE_ELIGIBLE_ARTIFACTS=26
FINAL_ELIGIBLE_SET_FROZEN=true
```

Le set final est
`docs/reports/final_production_eligible_set_20260825.txt`. La preuve
terminale est
`docs/reports/terminal_disposition_summary_20260825.json` (SHA-256
`41ed6ff6ef160b5fedd36b2316dd91bed1f1b8be223958eec8587b9f30e4571a`).

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

## 2. Profils et placements production

P01–P10 sont promus sans dérive sémantique. Le placement P24 existant est
conservé et rattaché au release registry. Sur les 56 contenus P11–P23, 10
sont exactement grounded et 46 restent hors release.

```text
P01_P10_CONTENT_COUNT=11
P01_P10_PRODUCTION_PROFILE_COUNT=10
P01_P10_SCOPE_DRIFT=0
P24_CONTENTS=5
P24_PROFILE_MATCH=5
P24_RELEASE_REGISTRY_ACCEPTED=true
P24_RELEASE_SCOPE_PLACEMENT_READY=true
P11_P23_INPUT_CONTENT_COUNT=56
P11_P23_EXACTLY_GROUNDED_COUNT=10
P11_P23_REVIEW_REQUIRED_COUNT=46
AMBIGUOUS_OR_UNRESOLVED_PROFILE_POLICY=MOVE_TO_REVIEW_REQUIRED_FOR_THIS_RELEASE
```

Les 26 contenus sont répartis dans 18 profils/scopes exacts. Le manifeste
sémantique a pour digest
`57d532ca0c80f0e70218e74902f1d47a4ca9f21d7e6bafa209f6f89426125b6c`.
Le placement est produit depuis le commit
`5c9e8f7f4fda53114c51aa638304a59e662b22a7`, tree
`fc225ae2ca0bb6d6d1f7c73e2616c5d57d58d152`, et son SHA-256 est
`b1a36aef251d05f0098bfe88d7eae45b36333452f1613741e15dc6a89de75315`.

```text
PRODUCTION_PROFILE_MANIFEST_VALID=true
PRODUCTION_PROFILE_COUNT=18
PROFILE_EXACT_MATCH_COUNT=26
PROFILE_NO_MATCH_COUNT=0
PROFILE_AMBIGUOUS_COUNT=0
PROFILE_MAPPED_COUNT=26
RELEASE_SCOPE_PLACEMENT_CONTENT_COUNT=26
RELEASE_SCOPE_PLACEMENT_GAP=0
RELEASE_SCOPE_PLACEMENT_EXTRA=0
RELEASE_SCOPE_PLACEMENT_AMBIGUOUS=0
```

## 3. Préparatifs go-live parallèles

### Docker V2

La PR technique #132 contient le harnais reproductible et la preuve réelle,
liés au HEAD `c98ad5e62b7e050feed0961cc6bef8651a7f08a9` et au tree
`4f265f3dee88079814e80469f313959e930314a4`. La preuve
`atomic_docker_v2_rehearsal_20260825.json` a pour SHA-256
`adf3d9b4dc975a294394accbf97c4f6b4e10981b232dd524960ddb9b788761a2`.
Elle est verte mais reste à merger après la vraie revue GitHub exact-head.

```text
ATOMIC_DOCKER_V2_REHEARSAL_PASS=true
BAD_DIGEST_REFUSED=true
BAD_READINESS_REFUSED=true
BAD_AUTHORIZATION_SET_REFUSED=true
FOREIGN_SERVICES_TOUCHED=0
ROLLBACK_REHEARSAL_PASS=true
PROJECT_CONTAINERS_REMAINING=0
DOCKER_V2_EVIDENCE_MERGED=false
```

### Base de données production

L'audit attesté a identifié `rag_pgvector/ragdb` sur le bind
`127.0.0.1:5436` et a exclu le PostgreSQL natif étranger sur
`127.0.0.1:5433`. Aucune écriture n'a été exécutée. Un backup `pg_dump -Fc`
a été vérifié puis restauré dans un projet isolé, jusqu'aux têtes produit 004
et ingestion_control 013.

```text
PROD_DB_TARGET_VERIFIED=true
PROD_DB_WRITES=0
PROD_DB_MIGRATION_PLAN_READY=true
FRESH_BACKUP_CREATED=true
BACKUP_CHECKSUM_VERIFIED=true
RESTORE_REHEARSAL_PASS=true
PRODUCTION_DB_MUTATED=false
```

Preuves : `docs/reports/evidence/production_db_read_only_audit_20260825.json`
et `docs/reports/evidence/production_db_migration_plan_20260825.json`.

### GitHub Environment `production`

L'Environment a été provisionné puis relu via l'API. Aucune valeur secrète n'a
été créée.

```text
PRODUCTION_ENVIRONMENT_EXISTS=true
PRODUCTION_ENVIRONMENT_PROVISIONED=true
REQUIRED_REVIEWER=abenrhouma
REQUIRED_REVIEWER_CONFIGURED=true
MAIN_ONLY=true
SELF_REVIEW_PREVENTED=true
ADMIN_BYPASS_DISABLED=true
WAIT_TIMER=0
ENVIRONMENT_SECRETS=0
ENVIRONMENT_PRODUCTION_READY=true
```

Preuve :
`docs/reports/evidence/github_production_environment_20260825.json`
(SHA-256
`55543e699dfaf5e5692ccac6b4567deffce605c6c37c487fa5b78c7ec63b31e4`).

## 4. Autorisations et exécution réelle

Les 18 candidats `ScopeAuthorizationArtifactV2` partitionnent exactement les
26 contenus. Ils ont été produits depuis le commit `main`
`3566cafb44138d6a7f00296dc0654257f9bf0ad6`, tree
`8c5081a52096d531f1bd027790e600eb83b05bd5`, puis matérialisés sous leurs
chemins gouvernés canoniques. La matrice d'audit est
`docs/reports/production_authorization_matrix_20260825.json` (SHA-256
`9ac6a4fb4959dac8449ea418d4d92151e18f823a523e5f85b80791176cacfa74`).

Les preuves droits/currentness/PII ne sont pas inventées comme champs V3 :
leurs paths et digests exacts sont inscrits par scope dans la matrice et le
HEAD intégral de la PR sera lié par la revue et chaque `ReviewBinding`.

```text
AUTHORIZATION_CANDIDATE_COUNT=18
AUTHORIZATION_CANDIDATE_CONTENT_UNION=26
AUTHORIZATION_CANDIDATE_OVERLAP=0
AUTHORIZATION_CANDIDATE_GAP=0
AUTHORIZATION_CANDIDATE_EXTRA=0
AUTHORIZATION_CANDIDATE_UNION_SHA256=fe97b3410791fa78d4734a8c495443296b3f2ec3e77627e12fc34f90e0b2b5f0
AUTHORIZATION_CANDIDATES_MATERIALIZED=true
AUTHORIZATION_CANDIDATE_REPLAY_CHECK=true
EFFECTIVE_AUTHORIZATION_COUNT=0
```

La PR d'autorité doit rester ouverte et son HEAD immuable pendant toute la
validité. Sans vraie review GitHub et sans les 18 signatures opérateur, les
compteurs effectifs restent strictement à zéro.

```text
REAL_AUTHORIZATIONS_CREATED=false
REAL_CAMPAIGN_EXECUTED=false
REAL_GOVERNED_REPUBLISH_EXECUTED=false
REAL_H2_GATE_PASS=false
AUTHORIZED_ELIGIBLE_ARTIFACTS=0
REPUBLISHED_ELIGIBLE_ARTIFACTS=0
H2_COVERED_ELIGIBLE_ARTIFACTS=0
INGESTED_ELIGIBLE_ARTIFACTS=0
API_DISCOVERABLE_ELIGIBLE_ARTIFACTS=0
```

PR #96 a été fermée comme superseded le 2026-08-25. PR #98 reste ouverte
comme preuve de référence uniquement ; elle sera fermée après création de la
nouvelle autorisation P24 liée au tree, profil et manifeste courants.

## 5. État et prochaine barrière

```text
PRODUCTION_READY=false
GO_LIVE_READY=false
RAG_PRODUCTION_DEPLOYED=false
DRIVE_MIRROR_COMPLETE=true
```

La prochaine barrière de cette branche est la vraie
`trusted-human-review/head-pinned` de la PR d'autorisations production. Cette
PR ne sera pas fusionnée : après sa review exacte, les 18 `ReviewBinding`
seront préparés ensemble pour la signature avec la clé privée détenue par
l'opérateur. L'AuthorizationSet, la campagne, le republish et H2 V2 réels
restent donc non exécutés ; la signature readiness offline et le cutover
restent des gates opérateur distincts.
