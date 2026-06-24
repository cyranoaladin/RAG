# Rapport — Lot 0.2 : Finalisation des reviews + CI locale

## Points traités

### 1. Garde-fou de gouvernance renforcé

Le script `scripts/check-governance-locks.sh` compare désormais **clé par clé** contre `scripts/governance-locks.baseline` (17 entrées). L'ancien contrôle par compte agrégé est remplacé.

**Tests manuels :**

Cas nominal (aucun changement) :
```
Governance locks: baseline=17, current=17
OK: all governance locks intact (17 keys verified).
```

Cas un verrou passe à `true` :
```
Governance locks: baseline=17, current=16
FAIL: the following locks from baseline are missing or weakened:
chunking_allowed: false
No ADR reference found on added lines. Blocking.
Exit code: 1
```

Cas swap (un verrou passe à `true`, un autre ajouté — même compte) :
```
Governance locks: baseline=17, current=17
FAIL: the following locks from baseline are missing or weakened:
chunking_allowed: false
No ADR reference found on added lines. Blocking.
Exit code: 1
```

### 2. Docs rag-engine corrigées (FR + EN)

- `AGENTS.md` : pgvector = cible (Lot 1.2), ChromaDB = défaut courant. Aucune affirmation « ChromaDB déprécié ».
- `README.md` (FR) : diagramme et description alignés (ChromaDB défaut, pgvector cible).
- `README-EN.md` : idem en anglais.

### 3. Règle tests amendée dans AGENTS.md racine

Reformulée : « aucun test vert ne passe au rouge. Un lot peut être livré avec des échecs préexistants, à condition qu'ils soient tracés dans `docs/reports/*_dettes.md` avec antériorité prouvée. »

Ajout : CI locale (`scripts/ci-local.sh`) tient lieu de garde-fou tant que GitHub Actions est indisponible.

### 4. `wheel` retiré

`packages/contracts/pyproject.toml` : `requires = ["setuptools>=68.0"]` (sans `wheel`).

### 5. CI locale instaurée

`scripts/ci-local.sh` exécutable, reproduit les 4 jobs CI :

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

## Aucune logique métier modifiée
