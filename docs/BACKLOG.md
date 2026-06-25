# Backlog des dettes techniques

## Tests préexistants en échec (rag-pedago)

| Test | Symptôme | Antériorité | Action |
|---|---|---|---|
| `test_real_draft_guard::test_valid_fixture_passes_and_invalid_fixtures_fail` | Assertion de statut (`ready_for_human_locked_metadata_validation` != `blocked`) | Prouvé sur commit `e16cbed` (avant Lot 0) | Lot dédié |
| `test_real_draft_unlock_gate` (tous) | ~~INTERNALERROR pytest~~ **Résolu** (lot-0.7.1). Cause : monkeypatch global de `Path.exists` interceptait pytest <9.x reporting. Fix : sous-classe `Path` injectée dans le module sous test (pas `pathlib.Path` global). Assertion `pathlib.Path("/").exists()` prouve le scope. 11/11 pass. | Prouvé sur commit `e16cbed` | Résolu — monkeypatch réellement scopé (lot-0.7.1) |

## Garde-fou de gouvernance

| Point | Détail | Action |
|---|---|---|
| Test « exception ADR » non automatisé | Le cas 5 (verrou retiré + ADR référencé sur ligne ajoutée → exit 0) nécessite un dépôt git temporaire pour être testé automatiquement | P2 cubic — dette tracée, vérifié manuellement (lot-0.2) |

## Outillage monorepo

| Point | Détail | Action |
|---|---|---|
| Distribution `nexus-contracts` | Non publié sur PyPI ; installé en éditable via `make install`. `pip install -e ".[dev]"` seul échoue. | Industrialiser via `uv workspace` (Phase 6) |
| Lockfiles sans hashes | `requirements.lock` de rag-pedago et rag-engine générés par `pip freeze` (pas `pip-compile --generate-hashes`) car nexus-contracts n'est pas sur PyPI. Contracts a des hashes (pip-compile). | Hashes possibles après passage à `uv workspace` |

## Audience / statuts hors-cible (Phase 5)

| Point | Détail | Action |
|---|---|---|
| Mapping `audience` incomplet | `status_detail == unknown` ou statuts hors-cible (système tunisien, double cursus, hors-AEFE) produit `aefe` par défaut sans warning | Affiner le mapping et émettre un warning pour les cas ambigus |

## Typecheck — inline `# type: ignore` ciblés (lot-0.7)

### rag-pedago (12 occurrences, plus d'overrides par module)
| Fichier | Ligne(s) | Code | Raison |
|---|---|---|---|
| `rag_pedago/project_doctor.py` | 105,121,124 | `assignment` | Variable reuse (str→Path, str→Pattern) |
| `rag_pedago/project_doctor.py` | 109,122,125 | `attr-defined` | Idem — .parts/.search sur str inféré |
| `rag_pedago/imports/real_draft_guard.py` | 105,150 | `union-attr` | yaml.safe_load returns Any/dict/None |
| `rag_pedago/imports/real_draft_unlock_gate.py` | 42,45 | `union-attr` | Idem |
| `rag_pedago/imports/pilot_manifest_template.py` | 170 | `union-attr` | Idem |
| `scrapers/discovery.py` | 263 | `union-attr` | enum .value on Optional |

## Divergence d'outils entre services

| Outil | rag-pedago | rag-engine | Risque |
|---|---|---|---|
| ruff | 0.15.19 | 0.6.4 | Règles différentes sur le contrat partagé |
| mypy | 2.1.0 | 1.11.2 | Idem |
| pytest | 9.1.1 | 8.3.3 | Comportement test subtil (cf. monkeypatch) |
| pydantic | 2.13.4 | 2.9.2 | Contrat compilé différemment selon le service |

**Plan** : unifier au prochain lot de maintenance. rag-engine a des contraintes runtime (py39 compat, dépendances transitives lourdes) qui rendent la montée non triviale.

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
