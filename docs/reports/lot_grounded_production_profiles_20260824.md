# Lot — ancrage du profil de production Philosophie Terminale

Date : 2026-08-24

```text
BASE_SHA=8aa65fb3fb5f077bcd6dfa427c8902bd6d5c28b0
PRODUCTION_PROFILE_EXACT_MATCH_COUNT=5
PROFILE_NO_MATCH_COUNT=67
PROFILE_AMBIGUOUS_COUNT=0
DECISION_REQUIRED_PARTITION_COUNT=13
DECISION_REQUIRED_CONTENT_COUNT=56
STAGING_NON_PRODUCTION_PARTITION_COUNT=10
STAGING_NON_PRODUCTION_CONTENT_COUNT=11
P01-P10_NOT_PROMOTED=true
P24_RELEASE_REGISTRY_MAPPING_READY=false
PROFILE_MAPPED_COUNT=0
GROUNDED_DISTINCT_CANONICAL_RESOURCE_SCOPES=1
DISTINCT_CANONICAL_RESOURCE_SCOPES=UNKNOWN_PENDING_PROFILE_DECISIONS
PRODUCTION_READY=false
GO_LIVE_READY=false
RAG_PRODUCTION_DEPLOYED=false
CI_GREEN=false
```

## Périmètre

Ce lot corrige uniquement le faux `PROFILE_DECISION_REQUIRED` de P24. Il ne
crée aucun profil et ne transforme pas les profils P01–P10 de staging en
profils de production. Les autres vérités de production restent inchangées.

La matrice n'a pas de producteur autonome versionné. Sa cohérence est donc
recalculée par les tests à partir des artefacts sources, et non validée par des
compteurs recopiés isolément.

## Preuve P24

Les cinq SHA de P24 sont exactement les clés `approved_artifacts` de :

- `services/rag-engine/configs/h2_initial_placement_policy.yml`.

La policy lie chacun des cinq contenus à `rag_nexus_philo_terminale_tc`. Le
profil `services/rag-engine/configs/ingestion_profiles/philosophie_terminale_tc_h2c_v1.yml`
fournit les dix dimensions du `ResourceScope` et le manifest
`services/rag-engine/configs/ingestion_manifest.yml` approuve son identité
exacte :

```text
PROFILE_ID=rag_nexus_philo_terminale_tc
PROFILE_VERSION=h2c-v1
PROFILE_FINGERPRINT=993b350071ffa961c2be47738aa138b95db56317f117d7b4086461dbfd0acefc
```

Le test recalcule le fingerprint depuis le YAML du profil, compare le résultat
au manifest et exige l'égalité exacte entre les cinq SHA P24 et les cinq clés
de la policy.

Ce match de profil ne constitue pas encore un placement release exécutable :
la collection `rag_nexus_philo_terminale_tc` est absente du release registry
`prerentree_2026_2027`. Un test P24-only exerce le producteur canonique et exige
son refus `UNACCEPTED_COLLECTION`. Le présent lot ne fabrique donc ni release
registry entry ni placement accepté ; `PROFILE_MAPPED_COUNT` reste à zéro.

## Séparation staging / production

P01–P10 représentent 10 partitions et 11 contenus. Leurs sources de profil
sont toutes sous `services/rag-engine/configs/ingestion_profiles/staging/`.
Ils restent donc groundés pour préparer une décision, mais ne comptent pas
dans `PRODUCTION_PROFILE_EXACT_MATCH_COUNT`.

Le calcul de couverture production est :

```text
FINAL_AUTHORITY_REQUIRED_COUNT=72
PRODUCTION_PROFILE_EXACT_MATCH_COUNT=5
PROFILE_NO_MATCH_COUNT=72-5=67
DECISION_REQUIRED_CONTENT_COUNT=56
STAGING_NON_PRODUCTION_CONTENT_COUNT=11
56+11=67
```

P24 apporte un unique `ResourceScope` canonique de production actuellement
groundé. Le total final `M` reste inconnu tant que les 56 contenus non décidés
n'ont pas chacun un scope exact. Les 13 partitions P11–P23 restent fail-closed.

## TDD

RED observé avant modification de la matrice et du master :

```text
3 failed
P24 partition_kind: PLACEMENT_ONLY_UNRESOLVED
master: PROFILE_EXACT_MATCH_COUNT=0
producer: PROFILE_DECISION_REQUIRED: 14 partitions / 61 contents
```

Le GREEN ciblé exige :

```text
P24 partition_kind=EXACT_VERSIONED_RELEASE_PROFILE
P24 profile_decision_required=false
producer refusal=PROFILE_DECISION_REQUIRED: 13 partitions / 56 contents
```

Vérification locale fraîche :

```text
TARGETED_PROFILE_AND_H2C_TESTS=248 passed
RUFF_TARGETED=PASS
JSON_PARSE=PASS
GOVERNANCE_LOCKS=PASS
GIT_DIFF_CHECK=PASS
```

La CI distante n'est pas exécutée dans ce lot local ; `CI_GREEN` reste donc
`false` jusqu'aux checks de la PR.
