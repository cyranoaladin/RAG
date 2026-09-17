# Go-Live — Verrous humains restants, et remédiation CONCURRENCE (BS2)

- Lot : `LOT_GO_LIVE_FINAL_BZ_REMAINING_HUMAN_GATES_REPORT` (inclut l'analyse BS2)
- Branche : `go-live/remaining-human-gates-report` — base `7d93bff46757fc979d7645d3c4dd966b20d09739`
- Décision BS2 : **`GO_LIVE_CONCURRENCY_STILL_BLOCKED`**
- Ce lot ne ferme rien, ne modifie aucun compteur, aucun budget, aucun code moteur.

## 1. État mesuré

`GO_LIVE_READY=false`, `--assert-ready=1`, `open_prs_blocking=0`, `go_live_qualification_blockers=4`
(C1, STAGING_EXTERNE, CONCURRENCE, MANIFESTE_PRODUCTION), `pii_undecided=149`,
`release_promoted_refused_contents=26`, `current_switch=0`, `production_db_writes=0`, `production_deployments=0`.

Acquis de la campagne : COCKPIT_E2E (#210), SYNC_INCREMENTALE (#212). Livrés sans fermeture : diagnostic CONCURRENCE
(#211), dossier de décision PII/actualité (#213), runbook staging et vérificateur fail-closed (#214).

## 2. Tout ce qui reste est une décision humaine

| # | Verrou | Ce qui est attendu de l'opérateur | Débloque |
|---|---|---|---|
| 1 | **PII / actualité** | remplir `pii_currentness_decision_sheet.tsv`, puis confirmer l'import | `pii_undecided`, les 26 promus refusés, C1 |
| 2 | **Staging externe** | désigner l'hôte : (A) `nexus-prod` cloisonné + feu vert SSH, (B) hôte séparé, ou exécuter soi-même le runbook | STAGING_EXTERNE |
| 3 | **Concurrence** | arbitrer capacité matérielle / ADR de plafond de rerank / ADR de profil de charge (§ 4) | CONCURRENCE |
| 4 | **Exclusion de contenu** (si des décisions excluent) | ADR : le constructeur de release ne sait pas exclure (`RESEAL_BUILDER_CAPABILITY_REPORT.md`) | C1 |
| 5 | **Manifeste de production** | signature, une fois 1–4 clos | MANIFESTE_PRODUCTION |
| 6 | **Déploiement** | `GO_PROD_EXECUTE sur commit <SHA> avec manifest <SHA256>` | production |

Ordre conseillé : 1 et 2 en parallèle (indépendants), 3 dès que l'hôte de staging existe (c'est là que la latence à
2 CPU se mesure), puis 4 → 5 → 6.

## 3. Mode d'emploi du reviewer PII / actualité

Feuille : `docs/reports/go_live/pii_currentness_decision_sheet.tsv`. Intégrité vérifiée dans ce lot : dossier scellé
conforme, 631 lignes (3 + 149 + 479), **0 cellule de décision remplie**, 0 `finding_id` dupliqué, 0 ligne sans empreinte,
les 26 promus en tête. Toutes les lignes sont donc « incomplètes » au sens de la décision : c'est l'état attendu.

**Chemin minimal pour débloquer C1 : 75 lignes** — les 3 `CURRENTNESS_CONTENT`, les 23 `PII_CONTENT` en
`P1_PROMOTED_BLOCKS_RELEASE` et leurs 49 `PII_FINDING`. Les 126 autres contenus (430 findings) ne bloquent que
`pii_undecided`.

1. Ouvrir le paquet hors dépôt : `~/nexus-pii-review-v2-20260907/<review_bundle_dir>/` (`document.pdf`,
   `pages/page-NNNN.txt`). Ne jamais recopier un extrait dans la feuille : `COMMENT` ne cite pas de donnée personnelle.
2. Pour **chaque** ligne `PII_FINDING` : `FINDING_DISPOSITION` ∈ `FALSE_POSITIVE_TECHNICAL` | `PUBLIC_INSTITUTIONAL_DATA` |
   `SYNTHETIC_EXAMPLE` | `PERSONAL_DATA_PRESENT`. Repères : `pattern_id`, `page`.
3. Pour la ligne `PII_CONTENT` : `HUMAN_DECISION` ∈ `PII_CLEARED` | `PII_REDACTION_REQUIRED` | `EXCLUDE_FROM_SERVABLE_SET` |
   `HUMAN_REVIEW_REQUIRED` ; `JUSTIFICATION_CATEGORY` ∈ `INSTITUTIONAL_CONTACT` | `PEDAGOGICAL_EXAMPLE` | `FICTIONAL_IDENTITY` |
   `TECHNICAL_FALSE_POSITIVE` | `PUBLIC_OFFICIAL_PUBLICATION` | `PERSONAL_DATA_PRESENT` ; `REVIEWER_LOGIN`.
   Règle du contrat : `PII_CLEARED` est **refusé à l'import** si un seul finding du contenu est `PERSONAL_DATA_PRESENT`.
4. Pour les 3 `CURRENTNESS_CONTENT` : `HUMAN_DECISION` ∈ `KEEP_IF_STILL_CURRENT_WITH_EVIDENCE` (preuve datée obligatoire
   dans `EVIDENCE_REFERENCE` : la source elle-même déclare l'archive) | `REPLACE_WITH_CURRENT_SOURCE` |
   `EXCLUDE_FROM_PROMOTED_RELEASE` | `HUMAN_REVIEW_REQUIRED`.
5. La colonne `prior_v1_decision_not_extended` rappelle la décision V1 : elle **informe**, elle ne vaut pas décision
   (texte canonique V2 différent, ADR-0047).
6. Une ligne laissée vide, ou `HUMAN_REVIEW_REQUIRED`, laisse le contenu bloquant : c'est sans risque.

Rien n'est importé sans confirmation explicite. `pii_undecided` ne baissera que du nombre de décisions rendues.

## 4. BS2 — CONCURRENCE : pourquoi ce n'est pas techniquement actionnable

Rappel (#211) : budget déclaré avant mesure (8 clients, p50 ≤ 3000 / p95 ≤ 6000 / p99 ≤ 7500 ms, 0 erreur) ; mesuré
232/240 HTTP 503. L'inférence est sérialisée (1 créneau) : le service doit tenir **≈ 375 ms par requête** pour que
8 clients en boucle fermée restent sous p50 = 3000 ms.

Mesures de ce lot (mêmes artefacts vérifiés, texte officiel réel, scripts ad hoc ; le poste était partagé, ±30 %) :

| Candidats rerankés | 8 threads (ce poste) | 2 threads (limite CPU du conteneur `ingestor`) |
|---|---|---|
| embedding seul | 169 ms | 273 ms |
| 8 (= k, plancher sensé) | 272 ms → requête ≈ **441 ms** | 618 ms → requête ≈ **891 ms** |
| 12 | 481 ms | 916 ms |
| 16 | 679 ms | 1440 ms |
| 24 | 1518 ms | 2250 ms |
| 35 (≈ actuel sur ce corpus) | 2843 ms | 3351 ms |

| Option explorée | Verdict |
|---|---|
| Plafond de candidats rerankés | **insuffisant seul** : même au plancher N = 8, 441 ms × 8 clients ≈ 3,5 s > p50. À 2 CPU : ≈ 7,1 s > budget moteur de 6 s → effondrement identique |
| Cache de requêtes / rerank | **écarté** : le moteur l'interdit délibérément sur la recherche publique (`CACHE_ENABLED = False`, chaque requête doit observer l'état de revue courant). De plus le banc répète 30 requêtes : ce serait gagner le test, pas la capacité |
| Batch contrôlé | ne réduit pas le calcul total ; déjà par lots de 32 |
| SDPA | gain nul (déjà le noyau par défaut ; écart de score 0.0) |
| `torch.compile` | échec sur ce modèle (`AttributeError`) |
| int8 dynamique (#211) | × 1,3 seulement, et modifie les scores donc le seuil `RERANK_THRESHOLD` |
| Créneaux × threads (#211) | plafond ≈ 0,85 req/s pour 2,67 requis |
| ONNX / OpenVINO | absents du venv ; nouvelle dépendance + nouvel artefact de modèle à gouverner → ADR |
| Instrumentation par étage | utile à l'exploitation, ne ferme rien ; non ajoutée pour ne pas toucher au pipeline canonique sans objet |
| Mesure sur hôte cible | non autorisée |

Aucun budget n'a été modifié, aucun profil abaissé, aucune mesure de fermeture tentée.

### Proposition soumise à arbitrage (non adoptée, aucun numéro d'ADR pris)

Les chiffres montrent que **deux** décisions sont nécessaires ensemble, et qu'aucune ne relève d'un lot technique :

1. **Dimensionnement de la cible** : à 2 CPU, une requête *unique* coûte ≈ 3,6 s avec le pipeline actuel (35 paires) ;
   la concurrence n'est pas le premier problème. Options : lever la limite CPU du conteneur, GPU, ou service d'inférence dédié.
2. **Plafond de rerank gouverné** (ADR) : reranker les N premiers candidats après RRF. Exige une revalidation complète
   de la qualité (golden queries, seuil 1,90) **avant** toute mesure de charge ; N fixé dans l'ADR, pas après lecture des latences.
3. **Profil de charge** (ADR, seulement s'il reflète l'usage réel) : à titre indicatif, sur ce poste, N = 12 donne ≈ 650 ms
   par requête, soit ≈ 2,6 s sous 4 clients. Ce n'est **pas** une recommandation de baisser le profil : rien ne prouve que
   8 recherches simultanées soit disproportionné pour Nexus. Si le profil est révisé, il l'est avant mesure, dans un commit
   distinct de toute fermeture.

Après arbitrage, le banc `test_concurrency_load.py` et le scelleur se rejouent tels quels.

## 5. Garanties de la campagne

Aucun garde-fou supprimé ou affaibli ; aucune auto-approbation ; chaque merge sous CI success + `trusted-human-review/head-pinned`
+ `--match-head-commit` ; aucun budget ajusté après mesure ; deux mesures hors budget ou non qualifiantes scellées comme
telles (`BUDGET_FAILED`, `RUNBOOK_ONLY_NOT_QUALIFIED`) ; aucune décision PII ; aucune release produite ; aucune production
touchée ; aucun secret versionné ni affiché.
