# Dettes identifiées — Lot 0

## Tests pré-existants en échec

### 1. `test_real_draft_guard::test_valid_fixture_passes_and_invalid_fixtures_fail`

- **Symptôme** : `AssertionError: assert 'ready_for_human_locked_metadata_validation' == 'blocked'`
- **Antériorité prouvée** : test exécuté sur le commit parent `e16cbed` (avant Lot 0), résultat identique : `FileNotFoundError` (fixture absente) puis assertion échouée.
- **Cause probable** : fixture `metadata_candidate.valid.jsonl` manquante ou logique de statut évoluée sans mise à jour du test.
- **Action** : dette pré-existante, à corriger dans un lot dédié.

### 2. `test_real_draft_unlock_gate` (INTERNALERROR pytest)

- **Symptôme** : monkey-patch de `Path.exists()` interfère avec le fonctionnement interne de pytest, provoquant un `INTERNALERROR`.
- **Antériorité prouvée** : test exécuté sur le commit parent `e16cbed`, même INTERNALERROR.
- **Cause** : le monkeypatch global de `Path.exists()` affecte les appels de pytest à `Path.exists()` pour la gestion du tmpdir et du traceback.
- **Action** : dette pré-existante, à corriger par scoping du monkeypatch.

## Résolution monorepo `nexus-contracts`

- `nexus-contracts` n'est pas publié sur PyPI ; il s'installe en éditable depuis `packages/contracts/`.
- La CI et `make install` gèrent l'installation dans l'ordre correct.
- **Amélioration future (Phase 6)** : industrialiser via `uv workspace` ou équivalent pour une résolution monorepo native.

## Commit ROADMAP poussé sur `main` hors PR

- Le commit `93f5ba8` (`docs: add project roadmap`) a été poussé directement sur `main`, en écart avec la règle « un lot = une branche = une PR ».
- Écart de process noté. L'historique n'est pas réécrit.
