# Rapport — Lot 14.1 : Clôture pgvector (coexistence + review réel)

## Gate quality→gate→review RÉEL

- `build_review_manifest.py` : valide (dim, NaN, metadata) puis produit `review_manifest.json`
- Indexeur ne lit QUE les chunks approuvés (chunk_id+sha matchent). Chunk absent ou sha modifié → rejeté.
- Plus de `REVIEW.ok` auto-vrai.

## Filtrage COEXISTENCE (SORTIE RÉELLE — chunks synthétiques injectés)

### Niveau (premiere + terminale coexistent, DB=126)
```
Q: 'dérivée' (niveau=terminale) → terminale/derivation [0.831] (premiere EXCLU)
Q: 'dérivée' (niveau=premiere) → premiere/derivation [0.927] (terminale EXCLU)
```

### Audience (aefe + tous coexistent)
```
Q: 'AEFE' (audience=libre) → (0 résultats — aefe EXCLU pour libre)
Q: 'AEFE' (audience=aefe) → terminale/programme_aefe [0.941]
```

## Retrieval pertinent (124 chunks pilotes)

| Requête | Top-1 | Score |
|---|---|---|
| comment calculer la dérivée | **derivation** | 0.875 |
| la justice dans la philosophie | **justice** | 0.872 |
| pile et file informatique | **piles** | 0.844 |
| les suites numériques | **suites** | 0.835 |

## CI locale : 7/7 PASS
