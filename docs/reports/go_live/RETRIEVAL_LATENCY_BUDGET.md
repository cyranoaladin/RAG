# Budget de latence staging — politique de validation du retrieval

- kind : `NEXUS-RETRIEVAL-LATENCY-BUDGET-V1`
- statut : **ADOPTÉ**
- décision humaine : `LOT_GO_LIVE_FINAL_BL_CLOSE_REMAINING_TECHNICAL_BLOCKERS_NO_OAUTH_REVOCATION`
- portée : `STAGING_READINESS_THRESHOLD_NOT_PRODUCTION_SLA`

## Définition du budget

| Paramètre | Seuil maximal autorisé | Nature |
|---|---:|---|
| **Latence p50** | **200.0 ms** | Seuil de validation staging |
| **Latence p95** | **250.0 ms** | Seuil de validation staging |
| **Timeouts** | **0** | Aucune requête expirée |
| **Erreurs** | **0** | Aucune requête en échec |

## Périmètre et application

> **Important** : Ce budget est un **seuil de qualification staging**, pas un SLA de production.
> Il s'applique à la suite gouvernée de 8 requêtes multi-matières exécutée contre l'index vectoriel dédié de staging (`validate_retrieval_contract.py`).

## Règles d'évaluation

1. L'évaluation s'exécute sur un protocole reproductible contre la base dédiée de staging.
2. La base de production reste intouchée (`production_touched: false`).
3. La base de revue n'est ni lue ni écrite (`review_db_read: false`, `review_db_written: false`).
4. Si le budget est respecté, la condition `latency_validated` est déclarée vraie.
5. En l'absence de ce fichier de politique ou si la politique n'est pas adoptée, le validateur refuse de valider (`latency_validated: false`, fail-closed).

## Ce que cette politique ne ferme pas

- Ne ferme pas `target_scope_searchable` (couverture complète des 2264 contenus).
- Ne ferme pas les bloqueurs de qualification du go-live.
- Ne tranche aucune décision PII.
- Ne constitue pas une autorisation de mise en production.
