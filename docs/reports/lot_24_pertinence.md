# LOT 24 — Pertinence du retrieval NSI

**Branche** : `lot-24-pertinence`
**Date** : 1er juillet 2026
**Config finale** : dense (e5-large 1024) → rerank CrossEncoder (ms-marco-MiniLM-L-6-v2) → seuil +2.25.

---

## Constat principal

Le retrieval vectoriel pur ne discriminait pas in-domain vs hors-domaine (écart 0.05). Le rerank CrossEncoder seul **transforme** la discrimination (écart 10.18). Un seuil à +2.25 rejette **100 % du hors-domaine** et conserve **100 % de l'in-domain**.

L'hybride BM25/RRF **dégrade** la pertinence sur corpus mono-matière (collision lexicale inter-domaine). Il est désactivé mais conservé pour un futur test multi-matières.

---

## L24-0 — Baseline vectoriel pur (corpus propre 20 835 chunks)

| | Avg top-1 | Range |
|---|---|---|
| In-domain (15) | 0.8658 | 0.8440 — 0.8872 |
| Hors-domaine (10) | 0.8170 | 0.7794 — 0.8542 |
| **Écart** | **0.0488** | **Insuffisant** |

## L24-A — Rerank CrossEncoder SEUL

| | Avg score rerank | Range |
|---|---|---|
| In-domain (15) | **+5.34** | +2.99 — +7.56 |
| Hors-domaine (10) | **-4.84** | -10.30 — +1.51 |
| **Écart** | **10.18** | **Discrimination transformée** |

## Seuil +2.25

Fondé sur la marge BB-03 : plus bas in-domain (+2.99, jointure SQL) vs plus haut hors-domaine (+1.51, sélection naturelle). Milieu de marge = +2.25.

- In-domain conservé : **15/15** (100 %)
- Hors-domaine rejeté : **10/10** (100 %)

**PROVISOIRE** : ce seuil est lié au chunking actuel (proxy phrases/tokens). Les 4 questions in-domain basses (+2.99 à +3.81) traînent à cause du découpage (DD-02), pas du contenu. Après ré-ingestion LOT 25 (chunker heading-aware), le plancher in-domain devrait monter → seuil à réviser (probablement relevable).

**PRÉDICTION à valider au LOT 25** : les 4 questions faibles (clé étrangère, récursivité, jointure SQL, boucle while) doivent passer de +3 à un score franc (> +5) après ré-ingestion. Critère de succès mesurable.

## L24-B — Hybride BM25/RRF : DÉGRADE

| | Rerank seul | Hybride + rerank | Delta |
|---|---|---|---|
| Plancher in-domain | +2.99 | +2.99 | 0.00 (inchangé) |
| Plafond hors-domaine | +1.51 | +2.04 | +0.53 (dégradé) |
| Marge | 1.48 | 0.95 | -0.53 (rétrécie) |

### Mécanisme (DD-01) : collision lexicale inter-domaine

Le BM25 matche sur des mots communs présents dans des chunks NSI sans rapport avec la requête :
- « Révolution française » → `23-NSIJ1G11.pdf` matche sur « française » (souveraineté numérique française)
- « Équation du second degré » → cours histoire algorithmique matche sur « équation » (Al-Khawarizmi)
- « Moteur thermique » → QCM NSI matche sur « moteur » (moteur pas à pas)

**Verdict** : hybride inutile/nuisible sur corpus mono-matière. À RE-TESTER quand le corpus deviendra multi-matières (le BM25 sur des termes disciplinaires spécifiques pourrait alors aider la discrimination).

## Scores in-domain bas (DD-02)

Les 4 questions in-domain basses pointent des sujets **PRÉSENTS** dans le corpus (96-255 docs) mais le chunker proxy (phrases/tokens) ne fait pas remonter le chunk le plus pertinent en premier. Le meilleur chunk remonté est souvent un passage adjacent (exercice mentionnant le sujet sans le définir).

**C'est une dette TECHNIQUE (R8 chunking), pas une dette de contenu.** Le corpus n'est pas mince — c'est le découpage qui est insuffisant. Le chunker heading-aware (LOT 25) isolera les sections cours/définition → les scores devraient monter.

**PRÉDICTION** (à valider, pas un fait) : le chunker heading-aware fera monter ces scores. À mesurer au LOT 25.

## Config finale figée

```
dense: intfloat/multilingual-e5-large (1024 dim)
rerank: cross-encoder/ms-marco-MiniLM-L-6-v2
seuil: +2.25 (score rerank, provisoire lié au chunking)
hybride: DÉSACTIVÉ (DD-01, collision lexicale mono-matière)
scoping: WHERE collection = ? (une collection par requête)
answer_generation_allowed: false
```

Implémenté dans `scripts/retrieval_v2.py`. Testé : in-domain → résultats citables, hors-domaine → 0 résultat.

## Garde-fous

- `resolve_collection_v2` seul chemin
- Hybride désactivé côté v2 (commentaire renvoyant à DD-01)
- Scoping `WHERE collection = ?` maintenu
- `answer_generation_allowed = false`
- Secret via variable de session, jamais en clair
