# Rapport de LOT 32 — Go-Live & Production Readiness

- **Branche proposée** : `lot-31-dettes-techniques` (mise à jour Go-Live)
- **Date** : 2026-07-29
- **Statut** : ⚠️ **NON PRÊT POUR LA PRODUCTION — dettes cockpit à traiter**
- **Verrous levés** : Aucun (tous les 18 verrous de gouvernance restent scellés).

---

## 1. Périmètre de Validation

| Service / Brique | Statut | Résultat des vérifications |
|---|---|---|
| **`packages/contracts`** | ✅ PASS | Import DTO `RetrievalRequest`, `StudentProfile`, `Document`, `Chunk` validé. |
| **`services/rag-pedago`** | ✅ PASS | Lint Ruff : 100% OK. Typecheck Mypy : 73 fichiers typés sans erreur. Tests pytest : 100% verts. |
| **`services/rag-engine`** | ✅ PASS | Indexation `pgvector`, retrieval hybride et test d'intégration `test_retrieval_script.py` validés. |
| **`services/cockpit`** | ⚠️ BLOCKED | `npm run build` validé en 3.52s, mais `npm run lint` échoue avec 8 erreurs préexistantes et `npm audit --omit=dev` signale 2 vulnérabilités élevées. |
| **Gouvernance & Verrous** | ✅ PASS | 18/18 verrous vérifiés sans dérive contre `scripts/governance-locks.baseline`. |
| **Validations Pédagogiques** | ✅ PASS | `validate_taxonomy.py` et `export_source_validation_evidence.py` 100% valides. |

---

## 2. Décisions & Configurations Prod

1. **Sources Éduscol (`ADR-0020`)** :
   - Les 11 sources qualifiées (PC, SVT, HGGSP, HG, LLCE, ES, Cycle 4 3e, STMG, Grand Oral) sont basculées en `status: verified` dans `services/rag-pedago/configs/eduscol_sources.yml`.
2. **Support Python & Monorepo** :
   - Exécution standardisée sur Python 3.11+ / 3.12 avec détection automatique dans `scripts/ci-local.sh` et les Makefiles de tous les services.

---

## 3. Matrice de Preuves

```
  PASS  packages/contracts
  PASS  services/rag-pedago
  PASS  services/rag-engine
  PASS  services/cockpit (npm run build)
  FAIL  services/cockpit (npm run lint: 8 erreurs)
  FAIL  services/cockpit (npm audit --omit=dev: 2 vulnérabilités élevées)
  PASS  governance-locks (18 keys verified)
  PASS  taxonomy-validation
  PASS  source-evidence-check
  PASS  governance-guard-tests
  PASS  ci-failsafe-tests
```

## 4. Dettes bloquantes constatées

1. **Lint cockpit** : 8 erreurs dans les composants UI, dont 7 violations
   `react-refresh/only-export-components` et 1 violation `react-hooks/purity`.
   Les versions d'ESLint et des plugins concernés sont identiques dans le lockfile
   parent et le lockfile courant ; ces erreurs ne sont donc pas introduites par ce lot.
2. **Audit de production cockpit** : 2 vulnérabilités de sévérité élevée affectent
   `lodash` et `react-router`. Leur correction nécessite une mise à jour de dépendances
   dédiée, hors du périmètre de ce lot.
3. **Audit complet cockpit** : `npm ci` signale au total 12 vulnérabilités
   (1 faible, 1 modérée et 10 élevées), dépendances de développement incluses.

La livraison Go-Live reste bloquée jusqu'à résolution de ces écarts et nouvelle
exécution de la CI locale, du lint, du build et de l'audit cockpit.
