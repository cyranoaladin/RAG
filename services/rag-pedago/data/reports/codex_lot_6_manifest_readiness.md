# Rapport Codex — Lot 6 : readiness pré-ingestion

## Objectif

Créer un rapport de readiness Markdown/JSON pour décider humainement si un dossier de manifests JSONL locaux est prêt pour un futur import contrôlé.

## Fichiers créés

- `rag_pedago/imports/readiness.py`
- `rag_pedago/imports/readiness_report.py`
- `tests/unit/test_manifest_readiness.py`
- `docs/MANIFEST_READINESS.md`
- `data/reports/codex_lot_6_manifest_readiness.md`

## Fichiers modifiés

- `Makefile`
- `.gitignore`

## Tests

- Tests unitaires readiness ajoutés pour les statuts `blocked`, `ready_with_warnings`, `ready`, les rapports Markdown/JSON, les actions recommandées, la CLI et l'absence de ledger.

## Résultats

- `python3 -m pytest tests/unit/test_manifest_readiness.py -q` : 10 passed.
- `make test` : 103 passed.
- `python3 -m rag_pedago.imports.readiness_report data/fixtures/manifests/batch_001 --batch-id batch-001` : rapport généré, statut `blocked`, 6 issues bloquantes, 3 warnings.

## Limites

- Aucun document source n'est lu.
- Aucun PDF n'est parsé.
- Aucun OCR, scraping, téléchargement, Qdrant, PostgreSQL, LLM ou appel réseau n'est utilisé.

## Prochaine étape recommandée

Valider le readiness report sur les fixtures puis préparer un futur lot d'import contrôlé de sources locales, toujours sans parsing documentaire implicite.
