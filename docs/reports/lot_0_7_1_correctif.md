# Rapport — Lot 0.7.1 : Correctif reproductibilité

## Makefile install avant/après

### Avant (lot-0.7)
```makefile
install:
    $(PY) -m pip install -e ../../packages/contracts
    $(PY) -m pip install -e ".[dev]"
```
→ Résolution libre, lockfile ignoré.

### Après (lot-0.7.1)
```makefile
install:
    $(PY) -m pip install -r requirements.lock
    $(PY) -m pip install -e ../../packages/contracts --no-deps
    $(PY) -m pip install -e . --no-deps
```
→ Lock = source d'installation, editables sans re-résolution.

## Preuve de reproductibilité depuis le lock

```bash
$ rm -rf .venv && python3 -m venv .venv && source .venv/bin/activate
$ make install
$ pip freeze --exclude-editable | sort > /tmp/freeze_after.txt
$ sort requirements.lock > /tmp/lock_sorted.txt
$ diff /tmp/lock_sorted.txt /tmp/freeze_after.txt
# (diff vide — IDENTICAL)
```

Toute version (transitives incluses) provient du lock.

**Hashes** : `packages/contracts/requirements.lock` a des hashes (pip-compile). rag-pedago et rag-engine utilisent `pip freeze` (pas de hashes) car nexus-contracts n'est pas sur PyPI — dette tracée au BACKLOG.

## Monkeypatch réellement scopé

### Technique
```python
class _GuardedPath(_gate_mod.Path):
    def exists(self, *a, **k):
        raise AssertionError("source existence must not be checked")

monkeypatch.setattr(_gate_mod, "Path", _GuardedPath)
```
→ Remplace la **référence** `Path` dans le module, pas `pathlib.Path`.

### Preuve
```python
# Pendant le patch :
assert pathlib.Path("/").exists()  # True — global intact
```
→ Test inclus dans `test_gate_does_not_open_source_uri_calculate_hash_or_check_source_existence`.

### Explication corrigée
Le crash INTERNALERROR survenait parce que pytest <9.x appelle `pathlib.Path.exists()` dans son code de reporting de traceback. Le monkeypatch global interceptait cet appel. Le scoping par sous-classe élimine la dépendance à la version de pytest.

## Divergence d'outils

| Outil | rag-pedago | rag-engine |
|---|---|---|
| ruff | 0.15.19 | 0.6.4 |
| mypy | 2.1.0 | 1.11.2 |
| pytest | 9.1.1 | 8.3.3 |
| pydantic | 2.13.4 | 2.9.2 |

Tracée au BACKLOG avec plan d'unification à un lot de maintenance ultérieur.

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
