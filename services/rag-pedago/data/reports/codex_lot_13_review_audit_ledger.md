# Rapport Codex — Lot 13 : review audit ledger

## Objectif

Ajouter une couche d'audit runtime dans le ledger SQLite pour tracer les review
packages, décisions humaines, tentatives d'import contrôlé et vérifications de
hash avant toute future ingestion documentaire.

## Fichiers créés

- `docs/REVIEW_AUDIT_LEDGER.md`
- `tests/unit/test_review_audit_ledger.py`

## Fichiers modifiés

- `Makefile`
- `docs/CONTROLLED_IMPORT.md`
- `docs/LEDGER_DESIGN.md`
- `docs/MANIFEST_REVIEW.md`
- `rag_pedago/imports/approve_review_cli.py`
- `rag_pedago/imports/controlled_import.py`
- `rag_pedago/imports/controlled_import_cli.py`
- `rag_pedago/imports/review.py`
- `rag_pedago/imports/review_package_cli.py`
- `rag_pedago/ledger/diagnostics.py`
- `rag_pedago/ledger/migrations.py`
- `rag_pedago/ledger/models.py`
- `rag_pedago/ledger/repository.py`
- `tests/unit/test_ledger_integrity.py`

## Tests

- `make doctor`
- `python3 -m pytest tests/unit/test_review_audit_ledger.py -q`
- `make test`
- `make ledger-init`
- `make ledger-doctor`
- `python -m rag_pedago.imports.review_package_cli ... --audit-ledger data/ledger/rag_pedago.sqlite`
- `python -m rag_pedago.imports.approve_review_cli ... --audit-ledger data/ledger/rag_pedago.sqlite`
- `python -m rag_pedago.imports.controlled_import_cli ... --require-review --review-package ... --review-decision ... --audit-ledger data/ledger/rag_pedago.sqlite`

## Résultats

- `make doctor` : OK.
- `make test` : 265 passed.
- `make ledger-doctor` : tables OK, `integrity_check: ok`,
  `foreign_key_check: OK`, migrations 2.
- Migration SQLite v2 ajoutée.
- Tables d'audit créées : `review_packages`, `review_decisions`,
  `controlled_import_attempts`, `controlled_import_verifications`.
- Repository étendu avec les méthodes d'écriture et de lecture d'audit.
- `--audit-ledger` ajouté aux CLI review package, approval et controlled import.
- Les tentatives bloquées par gate peuvent être auditées sans écrire de run ou
  document.
- Les tentatives importées peuvent lier review package, décision humaine,
  run_ids et vérifications.
- Scénario audité final : 1 package, 1 décision, 1 tentative, 10 vérifications,
  8 runs manifest-only et 11 documents metadata-only.

## Limites

- L'audit porte uniquement sur les métadonnées, rapports, hashes et décisions.
- Aucun document source n'est lu.
- Aucun parsing PDF, OCR, scraping, appel réseau, Qdrant, PostgreSQL ou LLM n'est
  utilisé.

## Prochaine étape recommandée

Préparer un lot de consultation/exports d'audit pour produire des vues humaines
sur l'historique des décisions et tentatives par batch.
