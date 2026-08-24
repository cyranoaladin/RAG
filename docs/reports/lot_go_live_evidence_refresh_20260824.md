# Lot ops — rafraîchissement des preuves go-live du 24 août 2026

## Périmètre et provenance

Ce lot versionne exclusivement des preuves opératoires déjà produites et
réconcilie la documentation de migration. Il n'a modifié aucun code de service,
aucune base de données et aucun réglage GitHub. Les preuves portent sur le commit
`8aa65fb3fb5f077bcd6dfa427c8902bd6d5c28b0`, arbre
`184613ba98608fd358f41859061e0a99156e469d`.

L'évaluation du rehearsal Docker est archivée dans
`docs/reports/evidence/atomic_docker_rehearsal_20260824.json`, SHA-256
`58f55e7e499dfb3e9648387932af9a8edda35e8a51170afc3fd47ee52d70525c`.
Elle conserve sous `synthetic_v1_observation` le résultat source dont le
SHA-256 était
`0fe6d56453462dd76360ae45627a4d4549bd486cf039a163140bc28987b34865`.

Ce résultat porte sur un bundle de fixture synthétique signée V1, pas sur la
future release de production V2. Le harnais et le transcript ne sont pas
versionnés ; la description nettoyée
`docs/reports/evidence/atomic_docker_rehearsal_protocol_20260824.md` ne suffit
pas à rendre l'exécution reproductible. Les succès observés restent donc des
faits V1 historiques, jamais des booléens de readiness V2.

```text
DOCKER_REHEARSAL_EVIDENCE_CLASS=SYNTHETIC_V1
DOCKER_REHEARSAL_VERIFICATION_STATUS=UNVERIFIED
ATOMIC_DOCKER_REHEARSAL_PASS=UNKNOWN
FOREIGN_SERVICES_TOUCHED=UNKNOWN
ROLLBACK_REHEARSAL_PASS=UNKNOWN
BAD_DIGEST_REFUSED=UNKNOWN
BAD_READINESS_REFUSED=UNKNOWN
SYNTHETIC_V1_ATOMIC_OBSERVED=true
SYNTHETIC_V1_FOREIGN_SERVICES_OBSERVED=0
SYNTHETIC_V1_ROLLBACK_OBSERVED=true
```

## Audit DB production read-only

L'évaluation nettoyée est
`docs/reports/evidence/production_db_read_only_audit_20260824.json`, SHA-256
`524d9afcf49c64f4d832570da9faa01e4c567e5501b72b994ff095db171c5568`.
Le résumé opérateur rapporte une cible `rag_pgvector`, PostgreSQL 16.14,
pgvector 0.8.2, un head structurel 001 non enregistré, les migrations produit
002–004 et ingestion-control 001–013 pending, trois tables vides, zéro lock en
attente et un backup vieux de 42 jours. Aucun transcript ni commande versionnée
ne prouve toutefois l'identité de la cible, la transaction read-only ou
l'absence d'écriture. Ces valeurs restent uniquement sous
`unverified_operator_observation`.

```text
PROD_DB_AUDIT_VERIFICATION_STATUS=UNVERIFIED_SUMMARY_NO_TRANSCRIPT
PROD_DB_TARGET_VERIFIED=UNKNOWN
PROD_DB_MIGRATION_PLAN_READY=UNKNOWN
PROD_DB_WRITES=UNKNOWN
```

Le runbook documente désormais l'ordre candidat vers le head
`004_artifact_placements` et corrige la restauration des backups `pg_dump -Fc`
par `pg_restore` dans un projet isolé, via le seul client migrateur. Le plan ne
passera à `READY` qu'après un audit DB attesté et un exercice restore/rollback
réellement prouvé.

## GitHub Environment

L'observation read-only rafraîchie est
`docs/reports/github_environment_read_only_observation_20260824.json`, SHA-256
`24ce5bf71ad40e5fa393e33d9d7fabfba7b2fcb4dfc982bf300606e9dec2181e`.
Les deux lectures API ont été rejouées à `2026-08-24T22:51:18Z`. Elles montrent
à cet instant précis zéro Environment et la permission reviewer `write` ; elles
ne constituent pas une garantie sur un état futur. Ce lot n'a réalisé aucune
mutation repo-admin.

```text
PRODUCTION_ENVIRONMENT_OBSERVED_AT=2026-08-24T22:51:18Z
PRODUCTION_ENVIRONMENT_EXISTS=false
PRODUCTION_ENVIRONMENT_PROVISIONED=false
GITHUB_REPO_ADMIN_WRITES=0
```

## Sérialisation avec le lot profils

Le master go-live et son test sont volontairement exclus de ce lot, car le lot
profils les modifie en parallèle. Ils seront réconciliés après sérialisation,
depuis les artefacts canoniques ci-dessus, sans recopier une observation
intermédiaire.

```text
MASTER_RECONCILIATION_DEFERRED=true
```

## Validation TDD

Le premier test RED a produit 25 échecs et une erreur en exigeant les statuts
fail-closed absents. Un second RED ciblé a produit trois échecs avant
l'isolation complète du restore Compose. Après correction :

- `python scripts/tests/test-go-live-evidence-refresh.py` : 7 tests passés ;
- `bash scripts/tests/test-ci-local-topology.sh` : fixture canonique acceptée,
  22 mutations refusées, topologie acyclique ;
- suites ciblées schéma/migrations/Compose : 176 tests passés ;
- parsing read-only de la fixture restore : exactement `pgvector` et
  `restore-migrator` ;
- `ruff check scripts/tests/test-go-live-evidence-refresh.py` et
  `git diff --check` : passés.

La classe `test_governance_docker_policy.py` reste non exécutable dans cet
environnement minimal : ses sous-processus imposent `/usr/bin/python3`, où la
dépendance préexistante `chromadb` n'est pas installée. Son fichier est
byte-identical à `HEAD` et ce lot ne modifie ni cette politique ni ses imports.
