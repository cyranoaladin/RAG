# Audit du magasin de vecteurs

- kind : `NEXUS-VECTOR-STORE-AUDIT-V1`
- mesuré sur : **DEDICATED_VECTOR_DB**

> les vecteurs sont écrits dans la base dédiée ; mesurer la base de revue rendrait zéro après une vectorisation réussie et ferait conclure qu'elle n'a rien produit

## Base dédiée

| Mesure | Valeur |
|---|---:|
| base | `nexus_vector_staging_a_20260912T060731Z` |
| hôte/port | `127.0.0.1:55436` |
| extension vectorielle | `True` |
| **vecteurs** | **54719** |
| contenus vectorisés | 2242 |
| passages re-découpés | 54719 |
| contenus porteurs de passages | 2242 |
| liste blanche | 2264 |
| dimensions fausses | 0 |
| lignes hors liste blanche | 0 |

## Base de revue — mesurée pour prouver qu'elle est intacte

- base : `drivestaging` (`127.0.0.1:55435`)
- extension vectorielle : `False`
- colonnes vectorielles : 0
- artefacts : 2473
- `review_db_intact` : `True`
- `review_db_written` : `False`

## Ce que ceci ne prouve pas

- ne prouve pas que le retrieval fonctionne
- ne prouve pas que les citations sont disponibles
- ne rend pas target_scope_searchable vrai
