# Rapport Codex — Lot 10.5 : official profiles fixtures

## Objectif

Élargir les fixtures et tests autour du référentiel officiel pour couvrir les
cas Nexus : troisième/DNB, seconde GT, première, terminale, candidat individuel,
AEFE scolarisé, double cursus, EAF, mathématiques anticipées, spécialités,
philosophie, Grand oral, options et EDS.

## Fichiers créés

- `data/fixtures/manifests/batch_official_profiles_clean/`
- `docs/OFFICIAL_PROFILES_FIXTURES.md`
- `tests/unit/test_official_profiles_fixtures.py`
- `data/reports/codex_lot_10_5_official_profiles_fixtures.md`

## Fichiers modifiés

- `rag_pedago/imports/quality.py`
- `rag_pedago/reference/loader.py`
- `data/reference/official_sources.yml`
- `data/reference/official_claims.yml`
- `data/reference/subjects/common_subjects.yml`
- `docs/OFFICIAL_REFERENCE_QUALITY.md`
- `docs/OFFICIAL_REFERENCE_MODEL.md`
- `docs/MANIFEST_GATE.md`
- `docs/CONTROLLED_IMPORT.md`

## Tests

- Ajout de tests unitaires pour les fixtures official profiles.
- Ajout de tests sur AEFE comme contexte vs statut candidat déprécié.
- Ajout de tests sur `official_claim_applies_to_mismatch`.
- Ajout de tests sur `official_source_applies_to_mismatch`.
- Ajout de tests sur contexte d'établissement inconnu.
- Vérification que `batch_clean_001` passe toujours.
- Vérification que `batch_001` reste bloqué.

## Résultats

Les tests ciblés `tests/unit/test_official_profiles_fixtures.py` passent.
La suite complète passe avec `203 passed`.

## Limites

- Aucun document source n'est lu.
- Aucun PDF n'est parsé.
- Aucune ingestion documentaire n'est réalisée.
- Aucune connexion externe n'est utilisée.
- Les fixtures ne remplacent pas une carte d'examen réelle.

## Prochaine étape recommandée

Utiliser ces fixtures pour valider les prochaines politiques avant tout lot
d'ingestion documentaire contrôlée.
