# Master Go-Live State — état observé après PR #130

Ce document met à jour l'instantané historique du 2026-08-15. Il décrit la
baseline `main` après PR #130 et le candidat de rafraîchissement des preuves
go-live ; il
n'est pas un pointeur live auto-référent vers la branche.

```text
STATE_GENERATED_AT=2026-08-24T23:21:37Z
STATE_OBSERVED_AT_MAIN_SHA=e6c476bf746ae840b3f0d7f8fc1a279f8bd4731e
PR127_MERGED=true
PR129_MERGED=true
PR130_MERGED=true
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
GROUNDED_DISTINCT_CANONICAL_RESOURCE_SCOPES=1
DISTINCT_CANONICAL_RESOURCE_SCOPES=UNKNOWN_PENDING_PROFILE_DECISIONS
PROFILE_MAPPED_COUNT=0
P24_RELEASE_REGISTRY_MAPPING_READY=false
PROFILE_DECISION_REQUIRED=true
FABRICATED_PROFILE_COUNT=0
```

Les cinq contenus P24 sont liés au profil de production philosophie Terminale
déjà approuvé et à son fingerprint `993b350071ffa961c2be47738aa138b95db56317f117d7b4086461dbfd0acefc`.
Ils ne sont pas encore mappés par le producteur canonique : la collection est
absente du release registry courant, qui refuse donc P24 fail-closed.
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
V2_MECHANISM_ON_MAIN=true
```

La décision choisit un `AuthorizationSetV1` canonique comme source globale et
des V2 explicites pour campaign, H2, promotion et readiness. Les autorisations
`ScopeAuthorizationArtifactV2` et review bindings individuels restent les
primitives de révocation et de revue. Les V1 ne changent ni de signification ni
d'octets. ADR-0043 reste
`UNREVIEWED_WIP/NON_AUTHORITATIVE/NOT_REUSED`.

Les mécanismes sont présents sur `main` depuis PR #129, mais aucune vraie
autorisation, campagne ou preuve H2 de production n'a encore été créée :

```text
REAL_AUTHORIZATIONS_CREATED=false
REAL_CAMPAIGN_EXECUTED=false
REAL_GOVERNED_REPUBLISH_EXECUTED=false
REAL_H2_GATE_PASS=false
```

## 5. Chantiers go-live parallèles — état réel

### Rehearsal Docker isolé

L'artefact versionné
`docs/reports/evidence/atomic_docker_rehearsal_20260824.json` (SHA-256
`58f55e7e499dfb3e9648387932af9a8edda35e8a51170afc3fd47ee52d70525c`)
conserve une observation synthétique V1 positive, mais aucun harnais ni
transcript reproductible. Elle ne prouve donc aucun verdict du protocole de
production V2 et reste explicitement `UNVERIFIED`.

```text
DOCKER_REHEARSAL_EVIDENCE_CLASS=SYNTHETIC_V1
DOCKER_REHEARSAL_VERIFICATION_STATUS=UNVERIFIED
ATOMIC_DOCKER_REHEARSAL_PASS=UNKNOWN
ROLLBACK_REHEARSAL_PASS=UNKNOWN
FOREIGN_SERVICES_TOUCHED=UNKNOWN
BAD_DIGEST_REFUSED=UNKNOWN
BAD_READINESS_REFUSED=UNKNOWN
```

### Audit DB production read-only

L'artefact versionné
`docs/reports/evidence/production_db_read_only_audit_20260824.json` (SHA-256
`524d9afcf49c64f4d832570da9faa01e4c567e5501b72b994ff095db171c5568`)
conserve le résumé opérateur détaillé, mais aucune commande ni transcript ne
prouve l'identité de la cible, la transaction read-only ou l'absence
d'écriture. Ces verdicts restent donc inconnus. La base locale de développement
n'est pas assimilée à la production.

```text
DB_AUDIT_EVIDENCE_STATUS=UNVERIFIED_SUMMARY_NO_TRANSCRIPT
PROD_DB_TARGET_VERIFIED=UNKNOWN
PROD_DB_MIGRATION_PLAN_READY=UNKNOWN
PROD_DB_WRITES=UNKNOWN
```

### GitHub Environment `production`

L'Environment est absent et non provisionné. Le geste admin exact est préparé
dans `docs/reports/plan_production_github_environment.md` : reviewer
`abenrhouma` (`user id 67140603`), branche `main` uniquement, prévention de
l'auto-revue, aucun bypass admin, wait timer 0, secrets 0.
La lecture API nettoyée du `2026-08-24T22:51:18Z` est versionnée dans
`docs/reports/github_environment_read_only_observation_20260824.json` : zéro
Environment et permission reviewer `write`, sans mutation, comme observation
ponctuelle uniquement. Digest :
`24ce5bf71ad40e5fa393e33d9d7fabfba7b2fcb4dfc982bf300606e9dec2181e`.

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

La prochaine barrière est la revue humaine du présent lot de rafraîchissement
des preuves go-live (PR #131). Les gates réels suivants restent, dans l'ordre :
décisions de profils, autorisations exactes, campagne/republish, H2, rehearsal
Docker V2 attesté, cible DB vérifiée, Environment provisionné,
provenance/promotion, signature offline, puis cutover.
