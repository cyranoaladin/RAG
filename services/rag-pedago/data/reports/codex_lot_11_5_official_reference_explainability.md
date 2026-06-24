# Rapport Codex — Lot 11.5 : official reference explainability

## Objectif

Rendre auditables les décisions du resolver officiel dans les issues qualité et
dans les rapports readiness, gate et controlled import.

## Fichiers créés

- `data/fixtures/manifests/batch_official_mismatch/`
- `tests/unit/test_official_reference_explainability.py`
- `docs/OFFICIAL_REFERENCE_EXPLAINABILITY.md`
- `data/reports/codex_lot_11_5_official_reference_explainability.md`

## Fichiers modifiés

- `rag_pedago/reference/resolver.py`
- `rag_pedago/imports/quality.py`
- `rag_pedago/imports/readiness.py`
- `rag_pedago/imports/gate.py`
- `rag_pedago/imports/controlled_import.py`
- `tests/unit/test_official_reference_resolver.py`
- `docs/OFFICIAL_REFERENCE_RESOLVER.md`
- `docs/OFFICIAL_REFERENCE_QUALITY.md`
- `docs/MANIFEST_GATE.md`
- `docs/CONTROLLED_IMPORT.md`

## Tests

- Explication source compatible `bac_general -> grand_oral`.
- Explication source incompatible `education_dnb` vers Grand oral.
- Explication claim compatible bac vers spécialité.
- Explication claim candidat individuel incompatible avec scolarisé.
- Propagation dans `QualityIssue`.
- Sections Markdown readiness/gate/controlled import.
- Détails JSON gate/controlled import.
- Absence de mismatch sur `batch_official_profiles_clean`.

## Résultats

La suite complète passe avec `227 passed`.

## Limites

- Aucun document source n'est lu.
- Aucun appel réseau n'est effectué.
- Les explications concernent les métadonnées et le graphe officiel, pas le
  contenu réel des documents.

## Prochaine étape recommandée

Utiliser ces explications dans les futures revues humaines de lots de manifests
avant ingestion documentaire contrôlée.
