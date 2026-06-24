# Rapport Codex — Lot 12.5 : review hardening

## Objectif

Durcir la revue humaine et l'approbation pour empêcher toute ambiguïté ou
modification silencieuse entre le package de revue, la décision humaine et
l'import contrôlé.

## Fichiers créés

- `tests/unit/test_review_hardening.py`
- `docs/MANIFEST_REVIEW_HARDENING.md`
- `data/reports/codex_lot_12_5_review_hardening.md`

## Fichiers modifiés

- `rag_pedago/imports/review.py`
- `rag_pedago/imports/controlled_import.py`
- `rag_pedago/imports/controlled_import_cli.py`
- `rag_pedago/imports/approve_review_cli.py`
- `tests/unit/test_reviewed_controlled_import.py`
- `.gitignore`
- `docs/MANIFEST_REVIEW.md`
- `docs/CONTROLLED_IMPORT.md`

## Tests

- Hash canonical JSON indépendant de l'ordre des clés.
- Vérification obligatoire du review package.
- Refus package modifié.
- Refus manifest modifié, ajouté ou supprimé.
- Refus taxonomie modifiée.
- Refus référentiel officiel modifié.
- Reviewer policy stricte.
- Registry append-only.
- Champs de vérification dans rapport controlled import.

## Résultats

La suite complète passe avec `254 passed`.

## Limites

- Aucun document source n'est lu.
- Aucune ingestion documentaire n'est réalisée.
- Aucun appel réseau n'est effectué.
- Les garanties portent sur les métadonnées, rapports et hashes.

## Prochaine étape recommandée

Conserver `--require-review --review-package --review-decision` comme chemin
obligatoire pour les futurs imports opérationnels de manifests réels.
