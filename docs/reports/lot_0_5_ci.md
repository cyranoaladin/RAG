# Rapport — Lot 0.5 : Assainissement de la CI locale (faux-vert lint/typecheck)

## Mécanisme du faux-vert

`run_pedago()` et `run_engine()` dans `ci-local.sh` exécutaient `make lint`, `make typecheck`, `make test` séquentiellement sans `set -e` ni capture de code de retour. Seul le dernier bloc (tests) déterminait PASS/FAIL. Les 116 erreurs ruff de `rag-pedago` n'ont jamais bloqué la CI.

## Correction du mécanisme

Chaque étape (lint, typecheck, test) est maintenant enveloppée dans un `if ! make <target>; then return 1; fi`. Seule la tolérance pour 1 échec de test préexistant est conservée (compteur).

## Diagnostic des codes ruff

| Code | Famille | Description | Nb avant |
|---|---|---|---|
| I001 | isort | Imports non triés | 41 |
| UP017 | pyupgrade | `timezone.utc` → `datetime.UTC` | 41 |
| F401 | pyflakes | Import inutilisé | 12 |
| UP042 | pyupgrade | `str, Enum` → `StrEnum` | 11 |
| B017 | bugbear | `pytest.raises` sans match | 7 |
| UP032 | pyupgrade | f-string sans placeholder | 2 |
| F811 | pyflakes | Redéfinition d'import | 1 |
| UP035 | pyupgrade | Import déprécié | 1 |

## Décompte avant/après

### rag-pedago
- **Avant** : 116 erreurs ruff
- **Auto-fixées** : 98 (I001, UP017, F401, UP032, UP035, F811)
- **Isolées** (per-file-ignores documentés) : 18 (11 UP042, 7 B017)
- **Après** : `ruff check .` → **All checks passed!**
- **Tests** : 989 passed, 1 failed (préexistant tracé)

### rag-engine
- **Avant** : 119 erreurs ruff
- **Auto-fixées** : 102 (I001, F541, UP015, UP006, B905, F841, F401)
- **Isolées** : 16 (`.windsurf/tmp/`, `tests/`)
- **Fix lot 1.1** : 1 B007 dans `pedagogical_chunker.py` (renommage `i` → `_i`)
- **Après** : `ruff check .` → **All checks passed!**

### contracts (lot 1.0/1.1)
- `ruff check src/` → **All checks passed!** (déjà propre)

## Test anti-faux-vert

Test `scripts/tests/test-ci-local-failsafe.sh` : injecte une cible factice qui échoue, vérifie que le résumé montre FAIL et que le script sort en erreur. **3/3 assertions PASS**, intégré à ci-local.sh.

## Démonstration lint bloquant

```
# Injection erreur temporaire dans rag-pedago :
$ echo "import nonexistent" >> schema/__init__.py
$ ci-local.sh → FAIL services/rag-pedago (lint failed)

# Retrait :
$ git checkout schema/__init__.py
$ ci-local.sh → PASS services/rag-pedago
```

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

## Aucune logique métier modifiée

Seuls des tri d'imports, alias `datetime.UTC`, suppression d'imports inutilisés, et isolation documentée. Le code de gouvernance n'a pas été réécrit.
