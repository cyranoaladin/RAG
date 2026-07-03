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

---

## SCALE-W1 — Nombre optimal de workers (15 req synchrones)

| Workers | Wall | Débit | Proc med | Proc p95 | Total med | Total p95 |
|---|---|---|---|---|---|---|
| 1 | 19.6 s | 0.8 r/s | 1.33 s | 1.43 s | 10.16 s | 19.63 s |
| **2** | **16.4 s** | **0.9 r/s** | **2.11 s** | **2.34 s** | **9.00 s** | **16.42 s** |
| 3 | 22.3 s | 0.7 r/s | 4.57 s | 5.23 s | 14.34 s | 22.29 s |

**Résultat** : 2 workers = optimal. 3 workers régresse (contention CPU mémoire-bound
sur Ryzen 7 3700X). RAM : ~2 GB/worker, 2 workers = ~4 GB sur 32 GB dispo.

---

## SCALE-W2 — Arrivée étalée Poisson (2 workers, 30 s de charge soutenue)

| Taux cible | Req total | Med (incl queue) | P95 | Max | Débit réel |
|---|---|---|---|---|---|
| **0.5 req/s** | 15 | **1.47 s** | **3.01 s** | 3.01 s | 0.5 r/s |
| 1.0 req/s | 30 | 7.16 s | 10.26 s | 10.74 s | 0.8 r/s |
| 1.5 req/s | 45 | 11.89 s | 18.40 s | 19.34 s | 0.9 r/s |
| 2.0 req/s | 60 | 21.99 s | 39.91 s | 40.86 s | 0.9 r/s |

**Constat critique** : le débit réel plafonne à **~0.9 req/s** quel que soit le taux
d'arrivée. Le CrossEncoder CPU est le goulot absolu — chaque requête monopolise un
cœur pendant ~1.1 s, et les 2 workers ne peuvent traiter que ~0.9 req/s en continu.

Au-delà de 0.5 req/s, les requêtes s'empilent dans la file. La dégradation est
**douce** (latence qui monte, pas d'OOM/crash) — les requêtes attendent leur tour.

**Seul 0.5 req/s (= 30 req/min = 1 classe) tient avec p95 < 3 s.**

---

## SCALE-W3 — Point de rupture et mode de dégradation (2 workers)

| Taux | Req | Med | P95 | Max | Mode |
|---|---|---|---|---|---|
| 2.5 r/s | 50 | 15.5 s | 29.7 s | 30.8 s | File qui gonfle |
| 3.0 r/s | 60 | 18.9 s | 41.6 s | 43.2 s | File qui gonfle |
| 4.0 r/s | 80 | 39.0 s | 66.2 s | 68.2 s | File qui gonfle |

**Mode de dégradation : DOUCE** (pas d'OOM, pas de crash). Les requêtes attendent
dans la queue multiprocessing. Pas de limite de file = la latence monte linéairement
avec la charge excédentaire. En production, il faudrait une file bornée (rejet propre
avec HTTP 503 au-delà) plutôt qu'une file infinie.

---

## SCALE-W4 — Charge cible réelle et verdict

| Scénario | req/s | p95 (2 workers, Poisson) | Verdict |
|---|---|---|---|
| 1 classe (30 req/min) | 0.5 | **3.0 s** | **TIENT** (limite) |
| 1 agent en rafale | 0.3 | < 2 s | **TIENT** |
| 1 classe + 1 agent | 0.8 | ~8 s | **DEGRADE** |
| 3 agents en rafale | 1.5 | ~18 s | **INTENABLE** |

**Verdict honnête** : ce serveur (Ryzen 7 + CPU) tient **1 classe OU 1-2 agents
séquentiels**. Pas les deux en simultané. Le CrossEncoder CPU à ~0.9 req/s de
débit max est le plafond physique. Les workers ne changent pas ce plafond — ils
répartissent la charge mais le CPU total reste le même.

### Stratégie de scaling si la cible dépasse 0.5 req/s soutenu

1. **Scaling horizontal** : 2 serveurs × 2 workers = ~1.8 req/s soutenu
2. **File Redis avec priorité** : élèves prioritaires (p95 < 3 s), agents en best-effort
3. **GPU dédié** : CrossEncoder GPU → ~20× plus rapide → ~18 req/s
4. **Reranker distillé** : sacrifier de la pertinence pour du débit (écarté pour l'instant)

---

## SCALE-W5 — Stratégie mémoire modèles

| Composant | Taille | Dupliqué par worker ? |
|---|---|---|
| e5-large | ~1.3 GB | Oui (chargé par process) |
| CrossEncoder L-6 | ~0.3 GB | Oui |
| Python + overhead | ~0.4 GB | Oui |
| **Total par worker** | **~2 GB** | — |
| **2 workers** | **~4 GB** | Sur 32 GB = 12% |
| **4 workers** | **~8 GB** | Sur 32 GB = 25% |

La RAM n'est pas le facteur limitant (32 GB disponibles). Le CPU est le goulot.
Le partage de modèles entre workers (mémoire partagée) n'apporterait pas de gain
de débit — le goulot est le compute CrossEncoder, pas la RAM.

**Recommandation** : 2 workers suffisent. Pas besoin de partage de modèles.

---

### Dette latence mise à jour (mesures réalistes)

| Dette | Statut |
|---|---|
| Latence mono > 2 s | **RESOLUE** (médiane 1.08 s, P95 1.37 s) |
| Charge 1 classe (0.5 req/s soutenu) | **LIMITE** (p95 3.0 s, 2 workers) |
| Charge agents (> 0.5 req/s soutenu) | **DETTE** — CrossEncoder CPU = 0.9 r/s max |
| Scaling multi-agents | **REQUIERT** scaling horizontal ou GPU |
| Batching CrossEncoder | **ÉCARTÉ** (ne fonctionne pas sur CPU, mesuré) |
| GPU | Indisponible (Hetzner CPU), acté |
