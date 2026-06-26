# Rapport — Lot 13.1 : Modèle d'embedding de production

## Décision modèle (DÉFINITIVE)

- **Modèle** : `intfloat/multilingual-e5-large` (multilingue FR/EN, 1024 dims, ~1.3GB)
- **Dimension** : **1024** — définitive, conditionne le schéma pgvector
- BGE-M3 écarté (poids ~2.3GB, overhead sans gain mesurable vs e5-large sur corpus FR)
- `all-MiniLM-L6-v2` (384d, anglophone) abandonné — artefacts 384d supprimés

## Téléchargement

Via HuggingFace — réseau sous ADR-0004 (scope « téléchargement modèle embedding »). `MODEL_NAME` = `intfloat/multilingual-e5-large`, figé dans `build_embeddings.py`.

## Résultats recalculés (1024 dims)

| Métrique | Valeur |
|---|---|
| Chunks embeddés | **124/124** |
| Dimension | **1024** (cohérent) |
| Norme L2 | **1.0000** (normalisé) |
| NaN/Inf | 0 |
| Métadonnées filtrage | 124/124 |

## Idempotence

```
Run 1: 124 computed, 0 skipped
Run 2: 0 computed, 124 skipped
```

## Sanity sémantique FR

### Intra vs inter
```
Intra-maths: 0.9162
Inter maths↔philo: 0.8026
Inter maths↔nsi: 0.8059
Intra > Inter: True
```

### Requêtes françaises → top chunk
| Requête | Attendu | Top-1 | Score |
|---|---|---|---|
| « comment calculer la dérivée d'une fonction » | derivation | **derivation** | 0.858 |
| « qu'est-ce que la justice selon Platon » | justice | **justice** | 0.871 |
| « structure de données pile en informatique » | piles | **piles** | 0.869 |
| « théorème des valeurs intermédiaires continuité » | continuite | **continuite** | 0.851 |

**4/4 requêtes FR → notion correcte en top-1.**

## CI locale : 7/7 PASS
