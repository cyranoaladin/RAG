# Rapport — Lot 13 : Calcul des embeddings gouverné

## Décision modèle/réseau

- **Modèle pilote** : `all-MiniLM-L6-v2` (384 dims, ~80MB, sentence-transformers)
- **Modèle production** : BGE-M3 (1024 dims) — à basculer au lot de mise à l'échelle
- Téléchargement via HuggingFace (réseau sous ADR-0004)
- Vecteurs normalisés L2 (norme = 1.0000)

## Levée tracée

`embeddings_allowed: true # ADR-0007` dans contrat + transition + baseline. ADR-0007 versionné. `ingestion_allowed` et `qdrant_allowed` restent false. Garde-fou 17/17.

## Résultats

| Métrique | Valeur |
|---|---|
| Chunks embeddés | **124/124** |
| Dimension | 384 (cohérent) |
| Norme L2 | 1.0000 (normalisé) |
| NaN/Inf | 0 |
| Métadonnées filtrage | 124/124 (niveau/voie/audience/matiere) |

## Idempotence

```
Run 1: 124 computed, 0 skipped
Run 2: 0 computed, 124 skipped
```

## Sanity sémantique

```
maths[0] ↔ maths[1] = 0.5931 (intra-notion)
maths[0] ↔ philo[0] = 0.2509 (inter-matière)
Intra > Inter: True
```

## Gating

5 tests : false→blocked, true→allowed, empty→blocked, malformed→blocked, missing→blocked.

## CI locale : 7/7 PASS
