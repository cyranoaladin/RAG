# Rapport — Lot 0.7 : Reproductibilité (dernier lot d'infra)

## Versions figées

| Outil | contracts | rag-pedago | rag-engine |
|---|---|---|---|
| pydantic | 2.13.4 | 2.13.4 | 2.9.2 (via requirements) |
| PyYAML | — | 6.0.3 | (via requirements) |
| ruff | 0.15.19 | 0.15.19 | 0.6.4 |
| mypy | — | 2.1.0 | 1.11.2 |
| pytest | 9.1.1 | 9.1.1 | 8.3.3 |

Note : rag-engine conserve ses propres versions (requirements-dev.txt déjà pinné).

## Lockfiles

- `packages/contracts/requirements.lock` (11 packages)
- `services/rag-pedago/requirements.lock` (17 packages)
- `services/rag-engine/requirements.lock` (174 packages)

## Preuve de reproductibilité

Deux `make install` successifs depuis un venv vierge produisent un `pip freeze` **identique** (diff vide démontré).

## Overrides mypy → inline `# type: ignore`

Tous les `[[tool.mypy.overrides]] disable_error_code` ont été remplacés par 12 `# type: ignore[code]` ciblés ligne par ligne :

| Fichier | Lignes | Code |
|---|---|---|
| `project_doctor.py` | 105,109,121,122,124,125 | assignment, attr-defined |
| `real_draft_guard.py` | 105,150 | union-attr |
| `real_draft_unlock_gate.py` | 42,45 | union-attr |
| `pilot_manifest_template.py` | 170 | union-attr |
| `discovery.py` | 263 | union-attr |

`make typecheck` → 0 erreur sur 54 fichiers, aucun override par module.

## Monkeypatch scopé

Le monkeypatch global `Path.exists`/`write_text`/`write_bytes` dans `test_real_draft_unlock_gate.py` a été remplacé par un patch scopé au module sous test (`rag_pedago.imports.real_draft_unlock_gate.Path.exists`).

**Explication corrigée** : le crash INTERNALERROR survenait parce que pytest <9.x appelle `Path.exists()` dans son code de reporting de traceback. Le monkeypatch global interceptait cet appel interne. pytest 9.x a changé ce comportement (d'où la « réparation » coïncidente). Le scoping élimine la dépendance à la version de pytest.

11/11 tests passent.

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
