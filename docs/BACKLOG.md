# Backlog des dettes techniques

## Tests préexistants en échec (rag-pedago)

| Test | Symptôme | Antériorité | Action |
|---|---|---|---|
| `test_real_draft_guard::test_valid_fixture_passes_and_invalid_fixtures_fail` | Assertion de statut (`ready_for_human_locked_metadata_validation` != `blocked`) | Prouvé sur commit `e16cbed` (avant Lot 0) | Lot dédié |
| `test_real_draft_unlock_gate` (tous) | ~~INTERNALERROR pytest~~ **Résolu** (lot-0.5 cache cleanup + lot-0.6 élucidation). 11/11 pass. | Prouvé sur commit `e16cbed` | Résolu — monkeypatch global documenté comme acceptable |

## Garde-fou de gouvernance

| Point | Détail | Action |
|---|---|---|
| Test « exception ADR » non automatisé | Le cas 5 (verrou retiré + ADR référencé sur ligne ajoutée → exit 0) nécessite un dépôt git temporaire pour être testé automatiquement | P2 cubic — dette tracée, vérifié manuellement (lot-0.2) |

## Outillage monorepo

| Point | Détail | Action |
|---|---|---|
| Distribution `nexus-contracts` | Non publié sur PyPI ; installé en éditable via `make install`. `pip install -e ".[dev]"` seul échoue. | Industrialiser via `uv workspace` (Phase 6) |

## Audience / statuts hors-cible (Phase 5)

| Point | Détail | Action |
|---|---|---|
| Mapping `audience` incomplet | `status_detail == unknown` ou statuts hors-cible (système tunisien, double cursus, hors-AEFE) produit `aefe` par défaut sans warning | Affiner le mapping et émettre un warning pour les cas ambigus |

## Typecheck legacy isolé (mypy overrides)

### rag-pedago
| Module | Erreurs isolées | Raison |
|---|---|---|
| `rag_pedago.project_doctor` | assignment, attr-defined (6) | Variable reuse shadows types (str→Path, str→Pattern) |
| `rag_pedago.imports.real_draft_guard` | union-attr (2) | yaml.safe_load returns Any/dict/None |
| `rag_pedago.imports.real_draft_unlock_gate` | union-attr (2) | Idem |
| `rag_pedago.imports.pilot_manifest_template` | union-attr (1) | Idem |
| `scrapers.discovery` | union-attr (1) | enum .value on Optional |

## Lint legacy isolé (per-file-ignores)

### rag-pedago
| Règle | Fichiers | Raison de l'isolation |
|---|---|---|
| UP042 (str+Enum → StrEnum) | 9 fichiers governance/schema | Migration StrEnum sur code sensible, risque régression |
| B017 (bare pytest.raises) | 3 fichiers test ledger | Raffinement des assertions nécessaire |

### rag-engine
| Règle | Fichiers | Raison de l'isolation |
|---|---|---|
| F401/F841/B007 | `.windsurf/tmp/*`, `tests/*` | Scripts temporaires et fixtures de test legacy |

## Process

| Point | Détail |
|---|---|
| Commit ROADMAP hors PR | Le commit `93f5ba8` a été poussé directement sur `main` — écart de process noté, historique non réécrit |
