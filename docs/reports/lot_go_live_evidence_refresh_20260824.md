# Lot ops — rafraîchissement des preuves go-live du 24 août 2026

## Périmètre et provenance

Ce lot versionne exclusivement des preuves opératoires déjà produites et
réconcilie la documentation de migration. Il n'a modifié aucun code de service,
aucune base de données et aucun réglage GitHub. Les preuves portent sur le commit
`8aa65fb3fb5f077bcd6dfa427c8902bd6d5c28b0`, arbre
`184613ba98608fd358f41859061e0a99156e469d`.

Le résultat byte-identical du rehearsal Docker est archivé dans
`docs/reports/evidence/atomic_docker_rehearsal_20260824.json`. Son SHA-256 est
`0fe6d56453462dd76360ae45627a4d4549bd486cf039a163140bc28987b34865`.
Il utilise le projet isolé `nexus-go-live-rehearsal-2455258`, jamais le projet
de production, sans `--remove-orphans`, et ne laisse aucun conteneur de fixture.
Il s'agit d'un bundle de fixture synthétique signée V1, dont les fichiers sont
vérifiés byte-identical à l'intérieur du bundle, pas la future release de
production byte-identical. Le protocole reproductible nettoyé et sa limite de
preuve sont versionnés dans
`docs/reports/evidence/atomic_docker_rehearsal_protocol_20260824.md` ; le harnais
temporaire original n'est pas archivé parce qu'il contenait un chemin machine
absolu et une graine privée de test.

```text
ATOMIC_DOCKER_REHEARSAL_PASS=true
FOREIGN_SERVICES_TOUCHED=0
ROLLBACK_REHEARSAL_PASS=true
BAD_DIGEST_REFUSED=true
BAD_READINESS_REFUSED=true
```

## Audit DB production read-only

La preuve nettoyée est
`docs/reports/evidence/production_db_read_only_audit_20260824.json`. L'audit a
identifié la cible RAG dédiée `rag_pgvector`, distincte des autres PostgreSQL de
l'hôte, et s'est exécuté dans une transaction explicitement read-only.
Son SHA-256 est
`03c6b025d3b6a6eebd6fe8670a4e3c3f7d61e73b756fc64c59e25fdcc8a802b4`.

La cible tourne sous PostgreSQL 16.14 avec pgvector 0.8.2. Le schéma produit est
structurellement conforme au head `001`, mais ce head n'est pas enregistré ;
`002` à `004` sont donc pending. Le schéma `ingestion_control` est absent et ses
migrations `001` à `013` sont pending. `rag_chunks`, `rag_api_keys` et
`rag_eval_runs` contiennent exactement zéro ligne. `rag_chunks` possède sa clé
primaire et les sept index du head `001` ; `idx_rag_chunks_text_tsv` est absent,
conformément à l'absence de `002`. L'observation comptait une connexion totale,
active, qui était la session d'audit, et aucune lock n'attendait.

Le système de fichiers `/dev/md2` exposait 929G au total, 151G disponibles et
83 % utilisés ; le répertoire de données PostgreSQL occupait 47M. Le dernier
dump DB identifié date du 13 juillet 2026, soit 42 jours au moment de l'audit :
il est stale pour le cutover et un backup frais reste obligatoire avant toute
migration.

```text
PROD_DB_TARGET_VERIFIED=true
PROD_DB_MIGRATION_PLAN_READY=true
PROD_DB_WRITES=0
```

Le plan exact est : backup frais ; adoption contrôlée du head structurel `001` ;
application produit `002`, `003`, `004` ; application `ingestion_control`
`001` à `013` et provisioning des rôles ; validation des registres, schémas et
privilèges ; exercice restore/rollback avant cutover. Le runbook canonique a
été aligné sur le head `004_artifact_placements`.

## GitHub Environment

L'observation read-only existante reste
`docs/reports/github_environment_read_only_observation_20260824.json`, SHA-256
`8880808bf1b46032e69141793d34815f4db836692a2e3f44d8f280db9f020d8a`.
L'Environment `production` demeure absent ; ce lot n'a réalisé aucune mutation
repo-admin.

```text
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
