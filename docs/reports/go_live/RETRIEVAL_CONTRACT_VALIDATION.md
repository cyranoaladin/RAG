# Validation du contrat de retrieval

- kind : `NEXUS-RETRIEVAL-CONTRACT-VALIDATION-V1`
- index : `nexus_vector_staging_a_20260912T060731Z` (`127.0.0.1:55436`)
- vecteurs interrogés : 54719
- contenus couverts : 2242
- top-k : 10

## Conditions

| Condition | État |
|---|---|
| `citations_validated` | **True** |
| `gate_refused_absent_from_results` | **True** |
| `latency_validated` | **False** |
| `out_of_scope_query_stays_in_allowlist` | **True** |
| `retrieval_top_k_validated` | **True** |
| `rollback_validated` | **True** |
| `scope_filters_validated` | **True** |

## Mesures

| Mesure | Valeur |
|---|---:|
| requêtes | 8 |
| requêtes sans résultat | 0 |
| résultats hors liste blanche | 0 |
| résultats refusés par le gate | 0 |
| résultats sans citation | 0 |
| doublons | 0 |
| latence p50 | 193.9 ms |
| latence p95 | 197.6 ms |

> le dépôt n'épingle aucun budget de latence : `retrieval_evaluation` porte un champ `latency_ms_p95` mais aucun seuil. Mesurer sans cible ne valide rien, donc `latency_validated` reste faux jusqu'à ce qu'un budget soit décidé.

## Filtres de portée

- requêtes filtrées : 8
- résultats hors filtre : **0**
- métadonnées chargées : 2697

## Retour arrière

- éprouvé : `True`
- un conteneur jumeau jetable est créé, la procédure documentée lui est appliquée, puis on vérifie qu'il a disparu — conteneur ET volume — et que l'index dédié est intact. L'index en place n'est jamais supprimé pour prouver qu'on saurait le supprimer.

## Ce que ceci ne prouve pas

- ne prouve rien sur la production : aucune base de production n'a été interrogée
- ne valide pas la qualité pédagogique des réponses, seulement les propriétés du contrat
- ne rend pas le go-live prêt
