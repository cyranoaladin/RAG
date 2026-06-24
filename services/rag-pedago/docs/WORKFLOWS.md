# Workflows

## Diagnostic local

```bash
make doctor
make test
make project-doctor
make ledger-init
make ledger-doctor
```

Résultat attendu : tests verts, ledger initialisé, migrations appliquées,
`integrity_check: ok`, `foreign_key_check: OK`.

## Batch problématique

```bash
python -m rag_pedago.imports.readiness_report data/fixtures/manifests/batch_001 --batch-id batch-001
python -m rag_pedago.imports.coverage_report data/fixtures/manifests/batch_001 --batch-id batch-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml
python -m rag_pedago.imports.gate_report data/fixtures/manifests/batch_001 --batch-id batch-001 --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml
```

Résultat attendu : le gate est `blocked`. Ce batch contient volontairement des
problèmes qualité.

## Batch clean

```bash
python -m rag_pedago.imports.readiness_report data/fixtures/manifests/batch_official_profiles_clean --batch-id batch-official-profiles-clean
python -m rag_pedago.imports.coverage_report data/fixtures/manifests/batch_official_profiles_clean --batch-id batch-official-profiles-clean --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml
python -m rag_pedago.imports.gate_report data/fixtures/manifests/batch_official_profiles_clean --batch-id batch-official-profiles-clean --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml
python -m rag_pedago.imports.review_package_cli data/fixtures/manifests/batch_official_profiles_clean --batch-id batch-official-profiles-clean --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml
python -m rag_pedago.imports.approve_review_cli data/reports/review_package_batch-official-profiles-clean.json --reviewer "Nexus Direction" --decision approved
python -m rag_pedago.imports.controlled_import_cli data/fixtures/manifests/batch_official_profiles_clean --batch-id batch-official-profiles-clean --taxonomy taxonomy/maths/terminale_specialite.yml --taxonomy taxonomy/nsi/terminale.yml --require-review --review-package data/reports/review_package_batch-official-profiles-clean.json --review-decision data/reviews/review_<id>.json
```

Résultat attendu : review package `ready_for_review`, décision approuvée, import
contrôlé `imported`.

## Audit ledger

```bash
python -m rag_pedago.imports.review_package_cli ... --audit-ledger data/ledger/rag_pedago.sqlite
python -m rag_pedago.imports.approve_review_cli ... --audit-ledger data/ledger/rag_pedago.sqlite
python -m rag_pedago.imports.controlled_import_cli ... --audit-ledger data/ledger/rag_pedago.sqlite
```

Requêtes utiles :

```sql
SELECT * FROM review_packages ORDER BY created_at DESC;
SELECT * FROM review_decisions ORDER BY reviewed_at DESC;
SELECT * FROM controlled_import_attempts ORDER BY created_at DESC;
SELECT check_name, passed FROM controlled_import_verifications WHERE attempt_id = :attempt_id;
```

## Workflow interdit

Les actions suivantes sont interdites dans l'état actuel du projet :

- parser un PDF ;
- ouvrir un `source_uri` ;
- faire un appel réseau ;
- lancer une vectorisation ;
- connecter Qdrant ;
- connecter PostgreSQL ;
- appeler un LLM runtime.
