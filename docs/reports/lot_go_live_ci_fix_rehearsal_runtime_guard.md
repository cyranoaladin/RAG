# Lot CI-Fix — Brancher la Garde d'Exécution sur NEXUS_ENVIRONMENT pour le Staging

- **Lot** : `LOT_GO_LIVE_FINAL_CI_FIX_REHEARSAL_RUNTIME_GUARD_FOR_STAGING`
- **Branche** : `go-live/fix-rehearsal-runtime-guard-for-staging`
- **Base** : `e2b0aaef08770ab7398e0d755a20deb8329d1538` (HEAD de `main` post-PR #226)
- **Composant ciblé** : `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py`

---

## 1. Contexte et Problème Résolu

Lors du démarrage du conteneur `nexus-staging-ingestor-1` pour la qualification du staging externe (Lot CI), le lifespan FastAPI a levé une exception au démarrage :

```text
RuntimeError: cannot activate rehearsal or unpromotable release in production runtime: release_id=production-profile-gate-2026-2027-v2, promotion_status=NOT_PROMOTABLE, activation_status=NO_PRODUCTION_ACTIVATION, review_status=PRE_REVIEW
```

### Cause racine
Dans `retrieval_v2_endpoint.py`, les fonctions `validate_release_startup_configuration` et `validate_configured_release_database` rejetaient inconditionnellement toute release portant `promotion_status: NOT_PROMOTABLE`, `activation_status: NO_PRODUCTION_ACTIVATION`, `review_status: PRE_REVIEW` ou `release_mode: rehearsal`.
Or, conformément à l'ADR-0050 §5, la release candidate V2 scellée au Lot CG porte légitimement ces statuts d'attente de qualification tant que les gates de go-live (staging, charge, signature finale) ne sont pas franchis.

---

## 2. Modifications Appliquées

1. **Prise en compte gouvernée de `NEXUS_ENVIRONMENT`** dans `services/rag-engine/src/ingestor/retrieval_v2_endpoint.py` :
   - Lecture de la variable canonique `NEXUS_ENVIRONMENT` (utilisée historiquement par `readiness_gate.py` et les workers multi-niveaux).
   - Valeur par défaut : `"production"` (**fail-closed**).
   - Valeurs supportées : `{"production", "rehearsal"}`.
   - Toute valeur arbitraire ou inconnue (ex: `"staging"`, `"dev"`, `"test"`) est **strictement rejetée** avec `RuntimeError("unsupported NEXUS_ENVIRONMENT: ...")`.
   - Si `runtime_env == "production"` : application stricte du refus des releases en mode rehearsal / non promues.
   - Si `runtime_env == "rehearsal"` : autorisation d'activation pour exécution et qualification sur l'environnement de staging.
2. **Préservation absolue des invariants de sécurité** :
   - Aucun hash de release V2 candidate ou de registre historique n'est modifié.
   - Le manifeste scellé V2 reste à son digest exact `e9506f5a66edec1f54f5a91935b5d3a9ba54c5c47abc040e93c02f278395d864`.
   - `release_registry.json` conserve son digest scellé `82051777ba0bea6a316fa65ea7aca468f0d6187891d0c8ccb69c0156801ea5db`.
   - Invariants : `current_switch=0`, `production_db_writes=0`, `production_deployments=0`.
3. **Suite de tests dédiée** :
   - Ajout de `services/rag-engine/tests/test_rehearsal_runtime_guard.py` (8 tests passés, 100% vert).

---

## 3. Résultats de Validation

- `pytest services/rag-engine/tests/test_rehearsal_runtime_guard.py` : **8 passed**
- `ruff check src tests/test_rehearsal_runtime_guard.py` : **All checks passed**
- `mypy src tests/test_rehearsal_runtime_guard.py` : **Success: no issues found in 141 source files**
- `bash scripts/check-authority-uniqueness.sh` : **NEXUS-AUTHORITY-UNIQUENESS-V1: PASS**
