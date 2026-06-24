# Rapport Codex — Lot 8 : import contrôlé de manifests

## Objectif

Créer une commande d'import contrôlé qui exécute obligatoirement le gate avant toute écriture dans le ledger.

## Fichiers créés

- `rag_pedago/imports/controlled_import.py`
- `rag_pedago/imports/controlled_import_cli.py`
- `tests/unit/test_controlled_import.py`
- `docs/CONTROLLED_IMPORT.md`
- `data/reports/codex_lot_8_controlled_manifest_import.md`

## Fichiers modifiés

- `Makefile`
- `.gitignore`

## Tests

- Tests ajoutés pour le blocage avant écriture ledger, l'import nominal du batch clean, les rapports Markdown/JSON, la CLI, l'absence de lecture source, l'absence de réseau et les run_ids existants.

## Résultats

- `python3 -m pytest tests/unit/test_controlled_import.py -q` : 8 passed.
- `make test` : 136 passed.
- Import contrôlé `batch_001` : `blocked_by_gate`, gate `blocked`, aucun ledger créé lorsque la base est absente.
- Import contrôlé `batch_clean_001` : `imported`, gate `ready_for_controlled_import`, 2 runs, 5 documents, 5 états, 0 document non récupérable.

## Limites

- Aucun document source n'est lu.
- Aucun PDF n'est parsé.
- Aucun OCR, scraping, téléchargement, Qdrant, PostgreSQL, LLM ou appel réseau n'est utilisé.

## Prochaine étape recommandée

Utiliser l'import contrôlé comme unique point d'entrée pour écrire des manifests validés dans le ledger avant de concevoir un futur lot de stockage local de documents sources.
