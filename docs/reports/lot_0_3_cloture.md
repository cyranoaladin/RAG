# Rapport — Lot 0.3 : Clôture du Lot 0

## Corrections apportées

### 1. P0 — `workspace_root` résolu correctement

**Problème** : `cleanup_policy.yml` contenait `workspace_root: ${NEXUS_WORKSPACE_ROOT:-.}` — syntaxe shell non interprétée par `yaml.safe_load`, produisant un `Path("${NEXUS_WORKSPACE_ROOT:-.}")` littéral.

**Correction** :
- `cleanup_policy.yml` : `workspace_root: null` (valeur sentinelle).
- `scripts/cleanup_dry_run.py` : si `workspace_root` est `null`/absent, utilise `rag_pedago.paths.WORKSPACE_ROOT` (déjà portable, override via `NEXUS_WORKSPACE_ROOT`).
- Test ajouté (`test_workspace_root_resolves_to_real_path`) : vérifie que le `Path` résolu est réel, pas une chaîne `${...}`.

```
test_workspace_root_resolves_to_real_path PASSED
```

### 2. P2 — `nexus-contracts` redéclaré dans pyproject.toml

**Problème** : le hotfix 0.1 avait retiré `nexus-contracts` des dependencies, rendant `pip install -e ".[dev]"` silencieusement cassé.

**Correction** :
- `nexus-contracts` remis dans `[project.dependencies]` (nom simple, pas de `file://`).
- `make install` installe d'abord le contrat, puis le service — c'est le point d'entrée supporté.
- README mis à jour : « `pip install -e ".[dev]"` seul échouera ».

**Démonstration** :

```
$ make install   → OK (contrat puis service)
$ pip install -e ".[dev]"   → ERROR: No matching distribution found for nexus-contracts
```

### 3. P2 — `make install` sur rag-engine + AGENTS.md exact

**Correction** :
- Cible `install` ajoutée au Makefile de `rag-engine` : installe `nexus-contracts` via le venv, puis appelle `install-dev`. `install-dev` conservé comme alias.
- Section Commandes de l'AGENTS.md racine corrigée : `make install` documenté comme homogène sur les deux services, CI locale mentionnée.
- `scripts/ci-local.sh` aligné sur `make install` pour rag-engine.

## CI locale

```
==============================
  CI LOCAL — SUMMARY
==============================
  PASS  packages/contracts
  PASS  services/rag-pedago
  PASS  services/rag-engine
  PASS  governance-locks

Total: 4 passed, 0 failed
```

## Verdict bots

À consigner après re-trigger sur la PR.

## Aucune logique métier modifiée
