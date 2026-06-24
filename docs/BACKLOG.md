# Backlog des dettes techniques

## Tests préexistants en échec (rag-pedago)

| Test | Symptôme | Antériorité | Action |
|---|---|---|---|
| `test_real_draft_guard::test_valid_fixture_passes_and_invalid_fixtures_fail` | Assertion de statut (`ready_for_human_locked_metadata_validation` != `blocked`) | Prouvé sur commit `e16cbed` (avant Lot 0) | Lot dédié |
| `test_real_draft_unlock_gate` (tous) | INTERNALERROR pytest (monkeypatch `Path.exists` global) | Prouvé sur commit `e16cbed` | Lot dédié — scoper le monkeypatch |

## Garde-fou de gouvernance

| Point | Détail | Action |
|---|---|---|
| Test « exception ADR » non automatisé | Le cas 5 (verrou retiré + ADR référencé sur ligne ajoutée → exit 0) nécessite un dépôt git temporaire pour être testé automatiquement | P2 cubic — dette tracée, vérifié manuellement (lot-0.2) |

## Outillage monorepo

| Point | Détail | Action |
|---|---|---|
| Distribution `nexus-contracts` | Non publié sur PyPI ; installé en éditable via `make install`. `pip install -e ".[dev]"` seul échoue. | Industrialiser via `uv workspace` (Phase 6) |

## Process

| Point | Détail |
|---|---|
| Commit ROADMAP hors PR | Le commit `93f5ba8` a été poussé directement sur `main` — écart de process noté, historique non réécrit |
