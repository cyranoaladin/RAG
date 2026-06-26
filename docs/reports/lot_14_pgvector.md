# Rapport — Lot 14 : Indexation pgvector + retrieval filtré (EXÉCUTION RÉELLE)

## Levée tracée

`ingestion_allowed: true # ADR-0008`. `server_start_allowed` et `runtime_api_allowed` restent false.

## Gate quality→gate→review

Script vérifie `ingestion_allowed` ET `REVIEW.ok` avant toute écriture.

## Indexation (SORTIE RÉELLE)

```
Indexed: 124, rejected: 0, total: 124
DB count: 124
```

Idempotence 2e run : DB count = 124 (0 doublon).

## Retrieval filtré (SORTIE RÉELLE)

| Requête | Niveau | Top-1 | Score |
|---|---|---|---|
| comment calculer la dérivée | terminale | **derivation** | 0.875 |
| la justice dans la philosophie | terminale | **justice** | 0.872 |
| pile et file informatique | terminale | **piles** | 0.844 |
| les suites numériques | terminale | **suites** | 0.835 |
| dérivée d'une fonction | **premiere** | **(0 résultats)** | — |

**Filtrage niveau prouvé** : premiere → 0 (corpus = terminale).

## Dettes D (héritées 13.2)

- input_format dans _can_reuse (ajouté)
- Refresh métadonnées à la réutilisation (ajouté)
- Tests embedding_utils (ajoutés)

## CI locale : 7/7 PASS
