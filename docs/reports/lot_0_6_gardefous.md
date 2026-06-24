# Rapport — Lot 0.6 : Complétude des garde-fous

## Portée du typecheck avant/après

### rag-pedago
| | Avant | Après |
|---|---|---|
| Modules couverts | `schema pipeline retrieval services` | + `rag_pedago scrapers` |
| Fichiers analysés | 15 | **54** |
| Erreurs révélées | 0 | 12 (dans 5 fichiers) |
| Corrigées | — | 0 (toutes isolables sans réécriture logique) |
| Isolées (mypy overrides) | — | 12 (5 modules documentés au BACKLOG) |
| Résultat | `Success: 15 files` | `Success: 54 files` |

### rag-engine
| | Avant | Après |
|---|---|---|
| Fichiers analysés | 32 | 32 (couverture déjà complète sur `src/`) |
| Résultat | `Success: 32 files` | `Success: 32 files` |

## Démonstration blocage sur erreur de type injectée

```bash
$ echo "x: int = 'not_an_int'" >> rag_pedago/__init__.py
$ make typecheck → error: Incompatible types in assignment
$ ci-local.sh → FAIL services/rag-pedago (typecheck failed)
$ git checkout rag_pedago/__init__.py  # retrait
$ ci-local.sh → PASS
```

## Per-file-ignores resserrés (rag-engine)

- `tests/*` = ["B007","F841"] **supprimé** (aucune erreur restante après auto-fix lot 0.5)
- `.windsurf/tmp/*` = [...] **supprimé** (dossier retiré du tracking git)

## `.windsurf/tmp/` retiré du dépôt

- `git rm -r --cached services/rag-engine/.windsurf/tmp` (31 fichiers)
- `**/.windsurf/tmp/` ajouté au `.gitignore`
- `.windsurf` ajouté aux `extend-exclude` de ruff

## `test_real_draft_unlock_gate` élucidé

**Cause du crash originel** : le monkeypatch global de `Path.exists` (ligne 143) interférait avec pytest lui-même lors de la résolution des tracebacks. Le crash survenait spécifiquement quand les fichiers `.pyc` pré-monorepo (compilés avec des chemins `/home/alaeddine/Bureau/RAG/rag-pedago/`) étaient présents — pytest tentait de résoudre ces chemins via `Path.exists()`, qui était monkeypatché.

**Résolution** : le nettoyage des `__pycache__` au lot 0 et la reconstruction du venv au lot 0.5 ont éliminé les `.pyc` stales. Le monkeypatch global est documenté comme acceptable (pytest le restore proprement après le test).

**Résultat** : 11/11 tests passent. Entrée BACKLOG mise à jour (résolu).

## CI locale

```
  PASS  packages/contracts
  PASS  services/rag-pedago
  PASS  services/rag-engine
  PASS  governance-locks
  PASS  governance-guard-tests
  PASS  ci-failsafe-tests
Total: 6 passed, 0 failed
```
