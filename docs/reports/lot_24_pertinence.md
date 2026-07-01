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

## Seuil +1.90 (recalé FF-02b)

Après suppression de la troncature 512 caractères (FF-02), la distribution des scores a bougé. Nouveau plancher in-domain : +2.30 (jointure SQL), plafond hors-domaine : +1.51 (sélection naturelle). Marge : 0.79. Seuil = milieu de marge = **+1.90**.

- In-domain conservé : **15/15** (100 %)
- Hors-domaine rejeté : **10/10** (100 %)

### Impact de la suppression de la troncature (FF-02b)

| Question | Avant ([:512] chars) | Après (texte complet) | Δ |
|---|---|---|---|
| Boucle while | +3.25 | **+4.86** | **+1.61** (le texte complet aide) |
| Clé étrangère | +6.22 | +5.43 | -0.79 (texte complet dilue) |
| Jointure SQL | +2.99 | **+2.30** | -0.69 (nouveau plancher) |
| Récursivité | +3.81 | +3.77 | -0.04 (stable) |

**Verdict DD-02 corrigé** : la troncature à 512 chars n'était PAS la cause des scores bas — elle AIDAIT certaines questions (en isolant le début du chunk, souvent la partie pertinente) et NUISAIT à d'autres (en coupant du contenu utile). Les scores bas sont **confirmés comme dette technique R8** (chunking proxy), pas un bug de troncature.

**PROVISOIRE** : le seuil +1.90 est lié au chunking actuel. Après ré-ingestion LOT 25, le plancher in-domain devrait monter → seuil à réviser.

**PRÉDICTION à valider au LOT 25** : les 4 questions faibles doivent passer de +2.3-4.9 à > +5 après ré-ingestion heading-aware. Critère de succès mesurable.

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
seuil: +1.90 (score rerank, recalé FF-02b, provisoire lié au chunking)
hybride: DÉSACTIVÉ (DD-01, collision lexicale mono-matière)
scoping: WHERE collection = ? (une collection par requête)
answer_generation_allowed: false
```

Implémenté dans `services/rag-engine/scripts/retrieval_v2.py`. Testé : in-domain → résultats citables, hors-domaine → 0 résultat.

## Garde-fous

- `resolve_collection_v2` seul chemin
- Hybride désactivé côté v2 (commentaire renvoyant à DD-01)
- Scoping `WHERE collection = ?` maintenu
- `answer_generation_allowed = false`
- Secret via variable de session, jamais en clair
