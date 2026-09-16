# Rapport de lot — Adoption du budget de latence staging et validation du retrieval

- **Lot** : `LOT_GO_LIVE_FINAL_BL_CLOSE_REMAINING_TECHNICAL_BLOCKERS_NO_OAUTH_REVOCATION` (Lot 1)
- **Branche** : `go-live/retrieval-latency-budget`
- **Base** : `main` (`f9b4294a5d86c09f35442bd01598faa44711c38e`)
- **Date** : 2026-09-16
- **Décision humaine associée** : Décision 2 (Budget de latence staging accepté)
- **Verdict** : `GO_LIVE_BL_LATENCY_BUDGET_PR_OPEN`

---

## 1. Contexte et objectif

Dans les lots #200 et #201, 54 719 vecteurs ont été produits dans la base dédiée et le contrat technique de retrieval a été validé sur 6 des 8 conditions.
Cependant, la condition `latency_validated` demeurait fausse : le dépôt ne fixait aucun seuil d'admissibilité formel pour la latence. Mesurer sans seuil ne validant rien, le gate restait fail-closed.

Ce lot matérialise la politique gouvernée de budget de latence pour la validation staging, la fait consommer par le validateur de contrat et ferme la condition `latency_validated`.

---

## 2. Périmètre et réalisations

### A. Politique de budget de latence staging adoptée
- Création de `docs/reports/go_live/retrieval_latency_budget.json` et `docs/reports/go_live/RETRIEVAL_LATENCY_BUDGET.md`.
- Seuils gouvernés :
  - `p50_ms_max` : **200.0 ms**
  - `p95_ms_max` : **250.0 ms**
  - `timeouts_max` : **0**
  - `errors_max` : **0**
- Portée explicite : seuil d'admissibilité technique de readiness staging, et non un SLA de production sous charge.

### B. Consommation par le validateur de contrat
- Modification de `scripts/go_live/validate_retrieval_contract.py` :
  - Fonction `charger_budget_latence()` et fonction pure `evaluer_latence()`.
  - Comportement strictement fail-closed : en l'absence de budget adopté ou en cas de dépassement, `latency_validated` reste `False`.
- Mesures observées :
  - `p50` : **193.9 ms** (<= 200.0 ms)
  - `p95` : **197.6 ms** (<= 250.0 ms)
  - Timeouts : 0, Erreurs : 0
  - Résultat : `latency_validated` passe à **`True`**.

### C. Réconciliation des artefacts de décision et correction live vs snapshot
- Régénération de `docs/reports/go_live/retrieval_contract_validation.json` et `.md`.
- Régénération de `docs/reports/go_live/rag_searchability_gap.json` et `.md` via `build_rag_searchability_gap.py` :
  - `rag_searchability_conditions_not_met` : `['target_scope_searchable']` (seule condition restante).
- Régénération du snapshot `docs/reports/go_live/go_live_readiness_state.json` et `.md` via `check_go_live_readiness.py` :
  - Résolution de l'écart disque : `disk_policy_ok` est désormais mesuré et consigné à `true` (206 Gio libres >= 40 Gio requis, 72% utilisé).
  - Retrait de `disk_policy_ok` des `blocking_reasons`.
- Tests de cohérence : `pytest scripts/tests/test_readiness_artifacts_coherence.py` passe à 100% (19 passed).

---

## 3. Garde-fous et Invariants

- **Production** : aucune écriture, aucune base de production interrogée, aucun current switch.
- **Base de revue** : non lue et non écrite (`review_db_read: false`, `review_db_written: false`).
- **OAuth / Secrets** :
  - `GOOGLE_OAUTH_REVOCATION_DEFERRED_BY_HUMAN=true`
  - `tokens_not_versioned=true`
  - `rclone_config_not_reprinted=true`
  - Aucun token ni secret n'a été affiché, consigné ni versionné.
- **Fail-closed** :
  - `--assert-ready` rend toujours **1** (blocages restants : PII, qualification blockers, PRs bloquantes, target scope 22 PDF, reseal v3).
  - Aucune fausse déclaration de readiness.
