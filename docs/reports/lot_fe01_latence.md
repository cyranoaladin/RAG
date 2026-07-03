# Latence /search/v2 — Mesure, qualification et projection

**Date** : 3 juillet 2026
**Config retenue** : D-CONFIG-RETRIEVAL-PREPROD — dense top-20 → rerank MiniLM-L-6 → seuil +1.90

---

## LAT-01 — Choix du pool rerank (mesuré)

| RERANK_CANDIDATES | Latence moy. | Marge in/out | 15/15 in | 10/10 out | Verdict |
|---|---|---|---|---|---|
| 20 (retenu) | 1.08 s | +4.07 | 15/15 | 10/10 | **Config retenue** |
| 10 | 0.69 s | +5.69 | 15/15 | 10/10 | Viable mais non retenu |
| 5 | 0.41 s | +3.82 | **14/15** | 10/10 | **ECARTE** (perd 1 in-domain) |

GPU (Hetzner CPU) : indisponible, acté.
Rerank L-2 : écarté (marge 1.00 → 0.71, dégrade la pertinence).

---

## LAT-03a — Distribution mono-requête (25 golden queries, warm)

| Composante | Médiane | P95 | Max |
|---|---|---|---|
| **Total** | **1.080 s** | **1.366 s** | **1.388 s** |
| Embed | 0.148 s | 0.175 s | 0.201 s |
| Dense HNSW | 0.013 s | 0.016 s | 0.017 s |
| Rerank | 0.931 s | 1.167 s | 1.222 s |

**Verdict mono** : médiane 1.08 s, P95 1.37 s — **sous 2 s** en mono-utilisateur.

---

## LAT-03b — Charge concurrente

| Concurrence | Requêtes | Wall time | Médiane | P95 | Débit |
|---|---|---|---|---|---|
| 1 | 10 | 12.8 s | 1.28 s | 1.56 s | 0.8 req/s |
| 5 | 10 | 9.5 s | 4.66 s | 4.80 s | 1.1 req/s |
| 10 | 10 | 9.9 s | **9.52 s** | **9.77 s** | 1.0 req/s |

### Analyse

Le CrossEncoder CPU est **single-threaded** : les requêtes concurrentes sont sérialisées sur le même cœur. Le débit plafonne à **~1 req/s** quel que soit le nombre de threads.

**Sous charge de classe (30 requêtes/min = 0.5 req/s)** :
- 0.5 req/s < 1.0 req/s de capacité → **le serveur tient**
- Latence dégradée à ~2 s pour les requêtes qui attendent en file

**Sous charge de pic (5 élèves en même temps)** :
- P95 = 4.8 s → **décrochage pour les derniers de la file**

### Dette scaling identifiée

| Scénario | Capacité | Verdict |
|---|---|---|
| 1 classe (30 req/min) | Tient (0.5 < 1.0 req/s) | Acceptable |
| 2 classes simultanées | Risque file d'attente | À surveiller |
| Pic 5+ simultanées | P95 > 4 s | **Nécessite scaling** |

**Pistes de scaling** (pas à résoudre maintenant, à connaître) :
1. **Workers uvicorn** : le serveur FastAPI peut être lancé avec N workers, chacun chargeant ses modèles en mémoire. 2 workers = 2 req/s, 4 = 4 req/s, au prix de la RAM (~2 GB/worker).
2. **Batching rerank** : grouper les paires (query, chunk) de requêtes concurrentes en un seul appel CrossEncoder. Complexité de code, gain significatif.
3. **GPU** : le CrossEncoder sur GPU passerait de ~0.9 s à ~0.05 s. Non disponible sur Hetzner CPU.

---

## LAT-04 — Décomposition dense vs rerank (projection échelle)

| Composante | Temps moyen | % du total | Dépend du corpus ? |
|---|---|---|---|
| Embed (query) | 0.145 s | 14% | Non (1 requête fixe) |
| Dense HNSW | 0.013 s | 1% | Oui (O(log N), HNSW) |
| Rerank | 0.855 s | **84%** | Non (20 candidats fixes) |

### Projection à l'échelle

Le rerank domine (84%) et est **fixe** (toujours 20 candidats, indépendant du corpus).
Le dense HNSW est négligeable (1%) et croît en O(log N) :

| Corpus | Dense estimé | Total estimé |
|---|---|---|
| 16 892 (actuel NSI) | 0.013 s | 1.01 s |
| 100 000 (multi-matières) | ~0.017 s | ~1.02 s |
| 500 000 | ~0.020 s | ~1.02 s |

**Verdict** : la latence mono-requête reste **stable à l'échelle** grâce au rerank fixe et au HNSW logarithmique. Le goulot est le débit concurrent (CrossEncoder CPU single-threaded), pas la taille du corpus.

---

## LAT-05 — Config figée

```
dense: intfloat/multilingual-e5-large (1024 dim)
rerank: cross-encoder/ms-marco-MiniLM-L-6-v2 (max_length=512)
pool rerank: 20 candidats (RERANK_CANDIDATES)
seuil: +1.90 (RERANK_SCORE_THRESHOLD)
hybride BM25/RRF: DESACTIVE (DD-01)
answer_generation_allowed: false
```

Pertinence : 15/15 in-domain, 10/10 out-domain, marge +4.07.
Latence mono : médiane 1.08 s, P95 1.37 s.
Débit : ~1 req/s (CPU single-threaded).

---

## SCALE-01 — Batching CrossEncoder : ÉCARTÉ (mesuré, ne fonctionne pas sur CPU)

Le batching (regrouper les paires de requêtes concurrentes en un seul `predict()`)
a été implémenté, mesuré, et **retiré** :

| Concurrence | Sans batching (wall) | Avec batching (wall) | Gain |
|---|---|---|---|
| 1 | 11.0 s | 12.9 s | **-17%** (dégradation) |
| 5 | 9.1 s | 12.7 s | **-39%** (dégradation) |
| 10 | 9.8 s | 12.4 s | **-27%** (dégradation) |
| 20 | 20.2 s | 19.3 s | +4% (marginal) |

**Cause** : le CrossEncoder sur CPU ne bénéficie pas du batching. Sur CPU, `predict()`
traite les paires séquentiellement quel que soit la taille du batch (pas de parallélisme
tensoriel). Le batching ajoute de la latence (fenêtre 50 ms + synchronisation threads)
sans rien gagner. Le batching est un levier **GPU uniquement**.

---

## SCALE-02 — Workers multiples : levier modeste (mesuré)

Simulation de N processus uvicorn, chacun chargeant ses propres modèles :

| Workers | 10 req concurrentes | Médiane | P95 | Débit (hors cold start) |
|---|---|---|---|---|
| 1 | séquentielles | 1.26 s | 1.39 s | ~0.8 req/s |
| 2 | 5 par worker | 2.08 s | 2.26 s | ~1.8 req/s |
| 4 | 2-3 par worker | 6.06 s | 7.24 s | ~1.2 req/s |

**Cause de la régression à 4 workers** : contention CPU — les workers se disputent les
cœurs L2/L3 cache et la bande passante mémoire. Sur ce serveur (16 cœurs), le CrossEncoder
est mémoire-bound, pas compute-bound.

**Sweet spot : 2 workers** = ~2x débit (1.8 req/s), latence individuelle légèrement
dégradée (2.08 s vs 1.26 s) mais acceptable. Coût RAM : ~4 GB (2 × 2 GB/worker).

---

## SCALE-03 — Cible de charge et projection

### Estimation de charge cockpit multi-agents

| Scénario | Requêtes/min | Req/s | Workers nécessaires |
|---|---|---|---|
| 1 élève interactif | ~2-5 | ~0.08 | 1 |
| 1 classe (30 élèves, bursts) | ~30 | ~0.5 | 1 |
| 3 agents IA en rafale | ~60-120 | ~1-2 | 2 |
| 10 agents + 1 classe | ~150-300 | ~2.5-5 | 3-4 (mais contention CPU) |

### La config retenue tient-elle ?

| Config | Capacité | Cible 3 agents (2 req/s) | Cible 10 agents (5 req/s) |
|---|---|---|---|
| 1 worker | 0.8 req/s | **NON** | **NON** |
| 2 workers | 1.8 req/s | **OUI** (p95 ~2 s) | **NON** |
| 4 workers | 1.2 req/s (contention) | **NON** | **NON** |

### Recommandation

**Déployer avec 2 workers uvicorn** (`uvicorn api:app --workers 2`). Tient 3 agents
en rafale (2 req/s). Au-delà de 3 agents simultanés, options :

1. **Scaling horizontal** : répliques du conteneur derrière un load balancer.
   2 répliques × 2 workers = ~3.6 req/s. Chaque réplique = ~4 GB RAM.
2. **File d'attente** : les agents tolèrent une latence de 5-10 s (pas interactifs).
   Une file Redis avec priorité élève > agent absorbe les pics.
3. **GPU** : le CrossEncoder sur GPU passerait de ~0.9 s à ~0.05 s par requête.
   Non disponible sur Hetzner CPU, acté.

---

## SCALE-04 — review_status exposé dans /search/v2 (livré)

Chaque hit porte `review_status` (reviewed | needs_review). Quarantined jamais retourné
(gate inchangé). Test prouvé sur requête réelle.

---

### Dette latence mise à jour

| Dette | Statut |
|---|---|
| Latence mono > 2 s | **RESOLUE** (médiane 1.08 s, P95 1.37 s) |
| Charge 1 classe (30 req/min) | **RESOLUE** (0.5 < 0.8 req/s, 1 worker suffit) |
| Charge 3 agents (2 req/s) | **RESOLUE avec 2 workers** (1.8 req/s) |
| Charge 10+ agents (5+ req/s) | **DETTE** — nécessite scaling horizontal ou file |
| Batching CrossEncoder | **ÉCARTÉ** (ne fonctionne pas sur CPU, mesuré) |
| GPU | Indisponible (Hetzner CPU), acté |
