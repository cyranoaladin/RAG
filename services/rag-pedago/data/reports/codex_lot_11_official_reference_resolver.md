# Rapport Codex — Lot 11 : official reference resolver

## Objectif

Créer un resolver de compatibilité du référentiel officiel pour vérifier qu'une
source ou une claim s'applique à un document, y compris via des agrégateurs
comme `bac_general` ou `dnb`.

## Fichiers créés

- `rag_pedago/reference/resolver.py`
- `tests/unit/test_official_reference_resolver.py`
- `docs/OFFICIAL_REFERENCE_RESOLVER.md`
- `data/reports/codex_lot_11_official_reference_resolver.md`

## Fichiers modifiés

- `rag_pedago/imports/quality.py`
- `tests/unit/test_official_reference_quality.py`
- `docs/OFFICIAL_REFERENCE_QUALITY.md`
- `docs/OFFICIAL_REFERENCE_MODEL.md`
- `docs/OFFICIAL_REFERENCE_INTEGRITY.md`

## Tests

- Tests resolver : agrégateurs bac/DNB, niveaux vers examens, statut candidat,
  contexte AEFE, explications de compatibilité.
- Tests qualité : source bac compatible Grand oral, source DNB incompatible bac,
  claim DNB incompatible Grand oral, claim bac compatible spécialité.

## Résultats

La suite complète passe avec `217 passed`.

## Limites

- Aucun document source n'est lu.
- Aucun réseau n'est utilisé.
- Le resolver valide les métadonnées déclarées, pas le contenu réel des
  documents.

## Prochaine étape recommandée

Utiliser le resolver dans les prochains lots de pré-ingestion et conserver les
explications de compatibilité dans les rapports qualité si un besoin d'audit
plus détaillé apparaît.
