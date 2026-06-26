# Rapport — Lot 13.2 : Préfixes e5 + idempotence par modèle

## A — Préfixes e5

- `passage: ` appliqué avant `model.encode()` pour tous les chunks (embedding)
- `query: ` à appliquer au retrieval (Lot 14) via `format_query()`
- Utilitaires centralisés dans `scrapers/embedding_utils.py`
- Convention documentée dans ADR-0007

## B — Idempotence par (sha, model, dim)

La clé de réutilisation vérifie :
1. `chunk_sha256` identique (contenu inchangé)
2. `model` identique (même modèle)
3. `dim` identique (même dimension)

**Test** : un fichier d'embeddings avec `model="DIFFERENT_MODEL"` → `_can_reuse()` retourne False → recalcul forcé. Pas de dimensions mixtes possible.

## C — Sanity FR avec préfixes

### Intra vs inter (avec passage:/query:)
```
Intra-maths: 0.9171  (vs 0.9162 sans préfixe)
Inter maths↔philo: 0.7990  (vs 0.8026 sans préfixe)
Écart: 0.118 → meilleure séparation
```

### Requêtes françaises (query: prefix)
| Requête | Top-1 | Score |
|---|---|---|
| « comment calculer la dérivée d'une fonction » | **derivation** | 0.875 |
| « qu'est-ce que la justice selon Platon » | **justice** | 0.873 |
| « structure de données pile en informatique » | **piles** | 0.878 |
| « théorème des valeurs intermédiaires continuité » | **continuite** | 0.854 |

**4/4 correct.** Scores légèrement améliorés avec préfixes (derivation: 0.858→0.875).

## Validation

- 124/124, dim=1024, norme=1.0, 0 NaN/Inf
- Métadonnées filtrage 124/124
- Idempotence: 2nd run = 0 recalcul (confirmé)
- 10/10 tests PASS (gating + dimension + model-change + metadata)
- CI locale : 7/7 PASS
