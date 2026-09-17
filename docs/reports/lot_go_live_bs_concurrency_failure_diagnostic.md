# Lot BS — Diagnostic d'échec de la qualification de concurrence et tentative de remédiation

- Lots : `LOT_GO_LIVE_FINAL_BS_QUALIFY_CONCURRENCY_AND_LOAD` puis
  `LOT_GO_LIVE_FINAL_BS_FIX_RETRIEVAL_CONCURRENCY_AND_REPLAY_BS`
- Branche : `go-live/fix-retrieval-concurrency-and-replay-bs` — base `52f80f6c7a2171498b9fe713d6b7bf7ff0720098`
- **Décision : `GO_LIVE_BS_REMEDIATION_INSUFFICIENT`** — CONCURRENCE reste **ouvert**.
- Ce lot ne ferme rien. Il livre l'outillage de mesure, le vérificateur fail-closed et une mesure honnête.

## 1. Mesure initiale (conservée comme diagnostic, jamais comme fermeture)

Preuve scellée `docs/reports/evidence/concurrency_load_proof.json` (`a466a3d3b4427bc93414a5d2ec8005885e1798e21718679aeb7982cd9faaa203`), statut `BUDGET_FAILED`.
Budget déclaré avant mesure : `docs/reports/go_live/concurrency_load_budget.json` (inchangé depuis).
La preuve a été prise sur la branche locale `go-live/qualify-concurrency-and-load` (commit `660873bc`, budget
déclaré en `0a62257f`) ; outillage et budget sont repris ici à l'identique par cherry-pick (empreinte du budget identique,
vérifiée par le vérificateur).

| Mesure | Séquentiel (30) | 8 clients (240) | Budget |
|---|---|---|---|
| p50 | 2294 ms | **6005 ms** | 3000 ms |
| p95 | 3038 ms | **6031 ms** | 6000 ms |
| p99 | 3057 ms | 6053 ms | 7500 ms |
| erreurs | 0 | **232 × HTTP 503** | 0 |
| timeouts client | 0 | 0 | 0 |

Tenu : pic de connexions PostgreSQL 6 ≤ 10, 0 connexion après arrêt, base identique avant/après, 0 doublon,
0 conteneur et 0 processus résiduels, compteurs de gouvernance inchangés, aucune production touchée.

## 2. Où se produit la contention

| Piste demandée | Constat |
|---|---|
| Sémaphore / limite d'inférence | **Déjà en place** : `inference_runtime.py`, `INFERENCE_MAX_CONCURRENCY = 1`, sans file non bornée. Il n'y a donc **pas** de saturation incontrôlée ni de thrashing : les inférences sont sérialisées. |
| Timeout applicatif | `runtime_request_budget` = 6000 ms (`pg_pool.py`, plafond `MAX_RUNTIME_DATABASE_BUDGET_MS`). L'attente du créneau consomme ce budget : sous 8 clients, l'attente (≈ 7 × 2,3 s) dépasse 6 s → 503. |
| Embedding E5-large | ≈ 150 ms par requête (8 threads). Secondaire. |
| **Reranker** | **Dominant** : le pipeline canonique rerank **tous** les candidats fusionnés (jusqu'à 2 × `CHANNEL_LIMIT` = 100 paires, ≈ 35 sur ce corpus), à ≈ 49 ms/paire (chunks réels, médiane 377 tokens) → ≈ 1,7 s. |
| Pool PostgreSQL | Hors de cause : pic 6/10, aucune attente, aucune fuite. |
| Workers Uvicorn / threadpool | Hors de cause : le travail est borné par le calcul CPU, pas par l'ordonnancement. |

C'est un problème de **capacité de calcul**, pas de concurrence mal maîtrisée. Loi de Little : 8 clients en boucle
fermée avec p50 ≤ 3000 ms exigent un débit ≥ **2,67 req/s** ; p95 ≤ 6000 ms exige au moins 1,33 req/s.

## 3. Tentative de remédiation : ce que les leviers sûrs peuvent donner

Profilage hors moteur, mêmes artefacts de modèles vérifiés, texte officiel réel découpé à la granularité des chunks,
35 paires par requête, 8 clients en boucle fermée (scripts ad hoc, non versionnés) :

| Réglage (créneaux × threads torch) | Débit | p50 |
|---|---|---|
| 1 × 8 (équivalent actuel) | 0,53 req/s | — |
| 2 × 4 | 0,62 req/s | 3332 ms |
| 4 × 2 | 0,76 req/s | 5136 ms |
| 8 × 1 | 0,84 req/s | 8856 ms |
| 2 × 8 | 0,74 req/s | 2700 ms (p95 > 26 s) |
| 4 × 4 | 0,86 req/s | 4668 ms |

Autres leviers mesurés sur le rerank seul (35 paires, 8 threads, 1711 ms de référence) : tri par longueur 1689 ms
(gain nul) ; quantification dynamique int8 1292 ms (× 1,3, **et modifie les scores**, donc le seuil `RERANK_THRESHOLD`).
Sensibilité aux cœurs : 16 threads 2471 ms, 4 threads 2268 ms, **2 threads 3267 ms**, 1 thread 6010 ms.

**Plafond observé ≈ 0,85 req/s, pour 2,67 req/s requis : facteur 3 manquant.** Aucun réglage de créneaux, de threads
ou de file ne le comble. Aucun code moteur n'a donc été modifié : un correctif qui n'atteint pas le profil et qui touche
le pipeline canonique n'aurait été qu'un changement de comportement non justifié.

Non tentés car interdits ou hors mandat : cache de requêtes (le banc répète 30 requêtes : ce serait gagner le test, pas
la capacité) ; réduction des candidats rerankés, troncature à 256 tokens, quantification (altèrent le classement et le
seuil calibré → ADR + revalidation des golden queries) ; statut de surcharge 429 (contrat → ADR) ; autre hôte.

## 4. Alerte go-live distincte de BS

`inference_runtime.py` indique que **le runtime canonique dispose de deux CPU**. À 2 threads, le rerank seul coûte
≈ 3,3 s : une requête **unique** approcherait le budget de 6000 ms, sans aucune concurrence. À vérifier sur la cible
avant tout déploiement ; ce point ne dépend pas du profil de charge retenu.

## 5. Décisions humaines possibles (aucune n'est prise ici)

1. **Capacité matérielle** : GPU ou service d'inférence dédié sur la cible, puis rejouer BS tel quel sur cet
   environnement *désigné comme cible*, pas choisi après coup.
2. **ADR pipeline** : borner le nombre de candidats rerankés (top-N après RRF) et/ou runtime d'inférence optimisé,
   avec revalidation complète de la qualité (golden queries, seuil), puis rejouer BS tel quel.
3. **ADR profil de charge** : uniquement si l'usage Nexus réel justifie moins de 8 recherches simultanées ; profil fixé
   avant toute nouvelle mesure, dans un commit distinct de toute fermeture. Rien dans les mesures ne prouve à ce jour
   que 8 clients soit disproportionné : cette voie n'est pas recommandée par défaut.

## 6. Garanties du câblage livré

`verifier_concurrence` ne ferme que sur `VERIFIED` ; il refuse : preuve absente, altérée, stale, `BUDGET_FAILED`,
sans mesures, résumé incohérent avec les mesures brutes (percentiles recalculés), budget absent, incomplet, non déclaré
avant mesure ou modifié après, latence/erreurs/timeouts hors budget, mock, fuite ou pic de connexions, base altérée,
résidus, `production_db_writes`/`production_deployments`/`current_switch` ≠ 0. 23 épreuves.

## 7. Readiness

Avant et après : `GO_LIVE_READY=false`, `--assert-ready=1`, `go_live_qualification_blockers=5`,
`pii_undecided=149`, `release_promoted_refused_contents=26`, `current_switch=0`, `production_db_writes=0`,
`production_deployments=0`.
