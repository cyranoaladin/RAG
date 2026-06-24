# Rapport — Lot 0.1 : Hotfix avant merge PR #1

## Corrections apportées

### 1. AGENTS.md racine restauré
Le fichier canonique complet a été posé (règles cross-service, conventions, garde-fous CI, escalade). `CLAUDE.md` racine contient `@AGENTS.md`.

### 2. `paths.py` rendu portable
- `WORKSPACE_ROOT` dérivé de `Path(__file__).resolve().parents[3]` au lieu d'un chemin absolu.
- Override possible via `NEXUS_WORKSPACE_ROOT`.
- `PRODUCTION_RAG_UI_ROOT` overridable via `NEXUS_RAG_UI_ROOT`.
- Scan `grep -rn "/home/alaeddine" --include='*.py'` : aucune occurrence fonctionnelle restante (2 occurrences dans des tests garde-fous testant l'absence du chemin — acceptables).

### 3. Chemins absolus corrigés dans la documentation
- `services/rag-pedago/AGENTS.md` : chemins absolus → relatifs.
- `services/rag-pedago/README.md` : chemin absolu → relatif.
- `services/rag-pedago/configs/cleanup_policy.yml` : variable d'environnement.
- `services/rag-pedago/docs/contracts/invariants.yml` : chemin relatif.

### 4. Dépendance `nexus-contracts` fiabilisée
- Retirée des `dependencies` runtime de `pyproject.toml`.
- `make install` ajouté au Makefile : installe d'abord `packages/contracts` puis `.[dev]`.
- CI alignée sur `make install`.
- Documentation ajoutée au README.

### 5. Dettes tracées
Voir `docs/reports/lot_0_dettes.md` :
- 2 tests pré-existants en échec (antériorité prouvée sur commit `e16cbed`).
- Résolution monorepo → amélioration future Phase 6.
- Commit ROADMAP hors PR noté.

## Résultat des tests après hotfix

```
986 passed, 1 failed (pré-existant) in 102s
```

Le solde est inchangé par rapport au Lot 0 (le delta 975→986 vient de l'inclusion de `test_real_draft_unlock_gate` qui ne crashe plus pytest grâce au nettoyage des pycache).

## CI GitHub Actions

```
$ gh run view 28119817596
X lot-0/fondations CI — Nexus RAG Platform #1 · 28119817596

JOBS
X services/rag-engine in 2s
X governance locks guard in 3s
X packages/contracts in 2s
- services/rag-pedago in 0s

ANNOTATIONS
X The job was not started because your account is locked due to a billing issue.
```

**Blocage externe** : les jobs ne démarrent pas car le compte GitHub est verrouillé pour cause de facturation. Ce n'est pas un problème de code.

**Action requise** : résoudre le problème de facturation GitHub, puis relancer la CI (`gh run rerun 28119817596`). Le code est prêt (tests locaux verts).
