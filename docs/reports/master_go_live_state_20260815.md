# Master Go-Live State — état observé après PR #127

Ce document met à jour l'instantané historique du 2026-08-15. Il décrit la
baseline `main` après PR #127 et le candidat contractuel multi-autorisation ;
il n'est pas un pointeur live auto-référent vers la branche.

```text
STATE_GENERATED_AT=2026-08-24T06:55:17Z
STATE_OBSERVED_AT_MAIN_SHA=3548bf300c99685ff6ede0dce2e5bfe8c044d213
PR127_MERGED=true
```

## 1. Release corpus finalisée

Le script versionné
`services/rag-pedago/scripts/recompute_final_release_set.py` recompose le
catalogue et les gates PII, droits, routing, currentness, manifest et golden,
sans autorité. Le lot détaillé consigne la commande, les huit digests d'entrée
et la comparaison octet par octet du résultat.

```text
FINAL_BASE_INGEST_CANDIDATES=73
FINAL_NON_AUTHORITY_BLOCKED_COUNT=1
FINAL_AUTHORITY_REQUIRED_COUNT=72
FINAL_AUTHORITY_REQUIRED_SET_SHA256=3705935f306a52cde0f398db20f685dce82d0bb9acd7909c8e6955d6356643e0
FINAL_RELEASE_ELIGIBLE_ARTIFACTS=72
FINAL_ELIGIBLE_SET_FROZEN=true
```

Le fichier `docs/reports/final_authority_required_set_20260823.txt` contient
exactement 72 SHA-256 minuscules, uniques, triés, un par ligne avec LF final.
Le rejeu non-skippé est consigné dans
`docs/reports/final_release_recomputation_evidence_20260824.json`, avec les
huit digests d'entrée, le digest du `summary.json` produit, le digest des
dispositions et la comparaison octet par octet du set commité. Digest de cette
preuve : `f68f5c525c7bd9280e03a1bbc5fd4a434de1b1d64e8a0a4eff8e32a3caa4f47d`.
La valeur historique `CURRENT_RELEASE_ELIGIBLE_ARTIFACTS=63` est conservée
uniquement comme fait d'un ancien snapshot ; elle est remplacée par ce calcul,
jamais par une substitution manuelle.

## 2. Comptabilité terminale exhaustive

```text
UNIQUE_CONTENTS=2582
INGEST_CANDIDATE=72
REVIEW_REQUIRED=2399
QUARANTINE=2
ARCHIVE_ONLY=19
EXCLUDE=53
UNSUPPORTED=37
UNACCOUNTED_CONTENTS=0
TERMINAL_DISPOSITION_COVERAGE=100%
```

La couverture terminale signifie que 100 % des contenus ont une décision pour
cette release, pas qu'ils doivent tous être ingérés. Les 138 contenus dont la
source officielle reste inaccessible derrière Cloudflare demeurent
`A_VERIFIER` / `REVIEW_REQUIRED`, avec la preuve réseau de PR #127.

```text
CLOUDFLARE_OPERATOR_DECISION=ACCEPT_REVIEW_REQUIRED_FOR_THIS_RELEASE
NETWORK_WORK_CLOSED_FOR_RELEASE=true
CLOUDFLARE_BLOCKS_GO_LIVE=false
```

## 3. Profils de production

La matrice proposée versionnée contient 24 partitions et couvre les 72
contenus. L'engagement opérateur reste une borne `>=22`, pas un exact 22 : la
matrice porte 23 couples bruts `(niveau, matière)`, dont 21 sans valeur nulle.
Son SHA-256 est
`b1fb997b56f080101493ac1efb151fc228109e110a9d8d86ce74f730eff544fe`.

```text
DISTINCT_LEVEL_SUBJECT_PAIRS_MINIMUM=22
MATRIX_RAW_DISTINCT_LEVEL_SUBJECT_PAIRS=23
MATRIX_FULLY_SPECIFIED_LEVEL_SUBJECT_PAIRS=21
GROUNDED_PARTITION_COUNT=11
GROUNDED_CONTENT_COUNT=16
STAGING_NON_PRODUCTION_PARTITION_COUNT=10
STAGING_NON_PRODUCTION_CONTENT_COUNT=11
DECISION_REQUIRED_PARTITION_COUNT=13
DECISION_REQUIRED_CONTENT_COUNT=56
PROFILE_EXACT_MATCH_COUNT=5
PROFILE_NO_MATCH_COUNT=67
PROFILE_AMBIGUOUS_COUNT=0
DISTINCT_CANONICAL_RESOURCE_SCOPES=1
PROFILE_DECISION_REQUIRED=true
FABRICATED_PROFILE_COUNT=0
```

Les cinq contenus P24 sont liés au profil de production philosophie Terminale
déjà approuvé et à son fingerprint `993b350071ffa961c2be47738aa138b95db56317f117d7b4086461dbfd0acefc`.
Les 11 contenus P01–P10 restent liés à des profils `staging` et ne sont pas
comptés comme matches de production. Les 56 autres contenus restent une vraie
décision produit. Aucun profil n'a été inventé pour atteindre artificiellement
72 matches.

## 4. Architecture multi-autorisation

L'ancien constat « seul `ProductionReadinessManifestV1.authorization_digest`
est bloquant » est historiquement conservé mais explicitement **superseded**.
L'audit adversarial recense 45 surfaces exécutables/contractuelles et confirme
les singularités H2, campaign, report/republish, workflow, signer, readiness,
deploy et runtime.

```text
MULTIAUTH_CONTRACT_SURFACE_AUDIT_REQUIRED=true
CONTRACT_CHANGE_REQUIRED=true
ADR=ADR-0044
CONTRACT_VERSION=0.13.0
AUTHORIZATION_SET_PROTOCOL=NEXUS-AUTHORIZATION-SET-V1
V1_LEGACY_READABLE_AND_UNCHANGED=true
V2_MECHANISM_IMPLEMENTED_ON_BRANCH=true
```

La décision choisit un `AuthorizationSetV1` canonique comme source globale et
des V2 explicites pour campaign, H2, promotion et readiness. Les autorisations
`ScopeAuthorizationArtifactV2` et review bindings individuels restent les
primitives de révocation et de revue. Les V1 ne changent ni de signification ni
d'octets. ADR-0043 reste
`UNREVIEWED_WIP/NON_AUTHORITATIVE/NOT_REUSED`.

Les mécanismes sont présents sur la branche contractuelle, mais aucune vraie
autorisation, campagne ou preuve H2 de production n'a encore été créée :

```text
REAL_AUTHORIZATIONS_CREATED=false
REAL_CAMPAIGN_EXECUTED=false
REAL_GOVERNED_REPUBLISH_EXECUTED=false
REAL_H2_GATE_PASS=false
```

## 5. Chantiers go-live parallèles — état réel

### Rehearsal Docker isolé

Le transcript du rehearsal initial n'est ni récupérable ni versionné. Les
valeurs résumées précédemment (`atomic=false`, `rollback=false`, services
étrangers touchés `0`, mauvais digest/readiness refusés) restent une
observation opérateur **historique non vérifiée**, jamais une preuve du lot.
Le blocker technique exact ne peut pas être reconstruit honnêtement.

```text
DOCKER_REHEARSAL_EVIDENCE_STATUS=UNVERIFIED_TRANSCRIPT_NOT_VERSIONED
ATOMIC_DOCKER_REHEARSAL_PASS=UNKNOWN
ROLLBACK_REHEARSAL_PASS=UNKNOWN
FOREIGN_SERVICES_TOUCHED=UNKNOWN
BAD_DIGEST_REFUSED=UNKNOWN
BAD_READINESS_REFUSED=UNKNOWN
EXACT_TECHNICAL_BLOCKER=UNKNOWN_TRANSCRIPT_UNAVAILABLE
```

### Audit DB production read-only

Le résumé opérateur indiquait une tentative SSH arrêtée sur une clé d'hôte
inconnue et zéro écriture, mais aucun transcript versionné ne le démontre. Ces
valeurs sont donc conservées uniquement comme observation historique non
vérifiée. La base locale de développement n'est pas assimilée à la production.

```text
DB_AUDIT_EVIDENCE_STATUS=UNVERIFIED_TRANSCRIPT_NOT_VERSIONED
PROD_DB_TARGET_VERIFIED=UNKNOWN
PROD_DB_MIGRATION_PLAN_READY=UNKNOWN
PROD_DB_WRITES=UNKNOWN
```

### GitHub Environment `production`

L'Environment est absent et non provisionné. Le geste admin exact est préparé
dans `docs/reports/plan_production_github_environment.md` : reviewer
`abenrhouma` (`user id 67140603`), branche `main` uniquement, prévention de
l'auto-revue, aucun bypass admin, wait timer 0, secrets 0.
La lecture API nettoyée du 2026-08-24 est versionnée dans
`docs/reports/github_environment_read_only_observation_20260824.json` : zéro
Environment et permission reviewer `write`, sans mutation. Digest :
`8880808bf1b46032e69141793d34815f4db836692a2e3f44d8f280db9f020d8a`.

```text
PRODUCTION_ENVIRONMENT_PROVISIONED=false
HUMAN_ADMIN_ACTION_REQUIRED=true
```

## 6. Drive, PR historiques et état de release

`DRIVE_MIRROR_COMPLETE=true` reste fondé sur le snapshot précédent ; le Drive
n'a pas été rescanné dans ce lot. PR #96 reste legacy/inactive et ne doit pas
être approuvée. PR #98 reste un candidat V2 partiel de cinq contenus ; sa
réutilisation sera décidée après construction du vrai set.

```text
PRODUCTION_READY=false
GO_LIVE_READY=false
RAG_PRODUCTION_DEPLOYED=false
DRIVE_MIRROR_COMPLETE=true
AUTHORIZED_ELIGIBLE_ARTIFACTS=0
INGESTED_ELIGIBLE_ARTIFACTS=0
API_DISCOVERABLE_ELIGIBLE_ARTIFACTS=0
```

La prochaine barrière est la PR contractuelle multi-autorisation elle-même.
Les gates réels suivants restent, dans l'ordre : décisions de profils,
autorisations exactes, campagne/republish, H2, rehearsal Docker corrigé, cible
DB vérifiée, Environment provisionné, provenance/promotion, signature offline,
puis cutover.
