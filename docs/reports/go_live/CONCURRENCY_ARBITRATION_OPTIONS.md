# CONCURRENCE — options d'arbitrage

Document d'aide à la décision. Rien n'est adopté ici : aucun budget, aucun profil, aucun code moteur n'est modifié.
Le budget versionné (`concurrency_load_budget.json`) et la mesure en échec de #211 restent tels quels.
Plan de mesure associé : `CONCURRENCY_TARGET_HOST_MEASUREMENT_PLAN.md`.

## 1. Les faits mesurés

Pipeline canonique : embedding E5-large de la requête, recherche dense + lexicale, fusion RRF, **rerank de tous les
candidats fusionnés** (jusqu'à 100 ; ≈ 35 sur le corpus du banc), seuil, MMR, `k = 8`. L'inférence est sérialisée
(`inference_runtime.py`, 1 créneau) ; le budget d'exécution d'une requête est de 6000 ms ; le conteneur `ingestor` est
limité à **2 CPU** par le Compose.

| Coût d'une requête (ms) | 8 threads, poste de travail | 2 threads ≈ conteneur cible |
|---|---|---|
| embedding | 169 | 273 |
| rerank 35 paires (actuel) | 1700 – 2800 | 3300 |
| **requête complète, actuelle** | **≈ 2300** | **≈ 3600** |
| rerank 16 / 12 / 8 paires | 679 / 481 / 272 | 1440 / 916 / 618 |

Mesures sur poste partagé (± 30 %), mêmes artefacts de modèles vérifiés, texte officiel réel.

**Ce que le profil actuel représente.** 8 clients en boucle fermée **sans temps de réflexion** ne sont pas « 8 élèves » :
c'est une file toujours pleine. Pour tenir p50 ≤ 3 s il faut servir ≥ 2,67 requêtes/s. Un utilisateur réel qui lance une
recherche par minute en produit 1/63 par seconde : **le profil équivaut à ≈ 170 utilisateurs activement en recherche au
même moment**. À l'inverse, la capacité mesurée vaut ≈ 0,43 req/s sur le poste (≈ 27 utilisateurs de ce type) et
≈ 0,28 req/s à 2 CPU (≈ 17), chacun attendant alors 2,3 à 3,6 s par recherche.

**Le premier problème n'est donc pas la concurrence** : à 2 CPU, une requête *unique* prend ≈ 3,6 s — au-delà du p50 visé,
et à portée du budget moteur de 6 s dès que deux requêtes se suivent.

## 2. Voie A — Dimensionnement de la cible

| Configuration | Requête seule | Débit | Profil 8 clients / p50 ≤ 3 s | Nature du chiffre |
|---|---|---|---|---|
| 2 CPU (actuel) | ≈ 3,6 s | 0,28 req/s | **échec**, y compris à 1 client | mesuré (2 threads) |
| 8 cœurs, 1 réplica | ≈ 2,3 s | 0,43 req/s | échec | mesuré |
| 8 cœurs × N réplicas | ≈ 2,3 s | 0,43 × N | N ≥ 7 (≈ 56 cœurs) ; la latence unitaire reste 2,3 s | extrapolé du mesuré |
| 1 GPU d'inférence (classe T4 / L4) | ≈ 0,1 – 0,2 s | 5 – 10 req/s | passe avec marge | **ordre de grandeur non mesuré**, à vérifier |

- Effet sur E5 / reranker : le rerank (cross-encoder, 35 paires × ≈ 380 tokens) est le poste dominant et c'est celui qu'un
  GPU accélère le plus ; le CPU plafonne vers 8 threads (16 threads : *plus lent*, 2471 ms).
- Ce poste a un GPU dont le pilote est inutilisable (`CUDA error 804`) : aucune mesure GPU n'a pu être faite ici.
- Coût d'intégration : faible côté moteur si le GPU est visible du conteneur (`CUDA_VISIBLE_DEVICES`, image avec
  runtime CUDA) ; la qualité est **inchangée** (mêmes modèles, mêmes scores).
- Test à rejouer sur staging : **C0** (30 requêtes séquentielles) puis **C1** (profil complet, budget inchangé).
- Risque : coût d'hébergement ; disponibilité d'un GPU chez l'hébergeur de `nexus-prod`.

## 3. Voie B — ADR de plafond de rerank

Reranker seulement les **N premiers** candidats après RRF.

- Gain : linéaire en N. À 2 CPU : N = 16 → ≈ 1,7 s ; N = 12 → ≈ 1,2 s ; N = 8 → ≈ 0,9 s par requête.
- **Insuffisant seul** pour le profil actuel : même N = 8 (plancher, puisque `k = 8`) donne ≈ 0,9 s × 8 clients ≈ 7 s à
  2 CPU, et ≈ 3,5 s sur 8 cœurs. Il ne passe le budget qu'associé à la voie A (N = 12 sur 8 cœurs × 2 réplicas ≈ 2,6 s).
- Impact qualité : un document pertinent classé au-delà du rang N par la fusion n'est plus jamais reranké. Le seuil
  `RERANK_THRESHOLD = 1,90` et le MMR opèrent sur moins de candidats : moins de résultats, possiblement moins de diversité.
  Le risque croît avec la taille des collections — négligeable sur 35 chunks, réel sur le corpus servable (55 251 vecteurs).
- Non-régression exigée **avant** toute mesure de charge : golden queries (`rag-pedago/tests/golden_queries`), les
  30 requêtes gouvernées du banc (artefact attendu retrouvé, concept attendu dans le premier extrait), la validation du
  contrat de retrieval (8 conditions de C4) — sur le corpus **servable**, pas sur le corpus du banc. Mesure utile et sans
  risque à faire d'abord sur staging : le rang de fusion maximal d'où proviennent les 8 résultats finaux ; il donne le plus
  petit N sans perte.
- Budget : inchangé. Un ADR qui changerait N **et** le budget dans le même mouvement ne prouverait rien.
- Coût : ADR, modification du pipeline canonique (contrat de retrieval inchangé), revalidation qualité complète.

## 4. Voie C — ADR de profil de charge

- Question produit, que je ne peux pas trancher : combien d'utilisateurs lancent une recherche **au même moment** au
  lancement ? Repère : simultanéité ≈ (utilisateurs actifs × recherches par minute / 60) × durée d'une requête.
  Exemples : une classe de 30 élèves, une recherche toutes les 2 min, requête de 2,3 s → ≈ 0,6 requête en vol ;
  10 classes simultanées → ≈ 6.
- Si l'usage de lancement est de l'ordre de quelques classes, un profil de 2 à 4 clients en boucle fermée le couvre
  largement ; le profil actuel (≈ 170 utilisateurs actifs) vise une échelle bien supérieure.
- Budget : à fixer dans l'ADR **avant** toute mesure, dans un commit distinct de toute fermeture ; l'ancien budget et sa
  mesure en échec restent versionnés.
- Risque d'exploitation : sous-dimensionner. Au-delà du profil retenu, le moteur répond 503 après 6 s d'attente — il
  échoue proprement mais l'utilisateur voit une erreur. À accompagner d'une supervision du taux de 503 et d'un seuil
  d'alerte. Et **C ne corrige pas la latence unitaire** : ≈ 3,6 s par recherche à 2 CPU.
- Garde-fou : un profil abaissé parce que la mesure a échoué, sans donnée d'usage, serait un faux vert.

## 5. Recommandation technique (non adoptée)

**Voie A d'abord, avec un GPU d'inférence, précédée de la mesure C0 sur le staging.** Raisons :

1. c'est la seule voie qui corrige le vrai défaut — la latence d'une requête *seule* sur la cible — et la seule qui ne
   touche ni à la qualité ni au budget ;
2. C0 coûte 3 minutes de staging et tranche : si p50 séquentiel > 3000 ms à 2 CPU, ni B ni C ne suffisent ;
3. B est un bon complément (coût / qualité maîtrisable) mais ne passe pas seul, et exige une revalidation lourde ;
4. C ne se justifie que par une donnée d'usage que vous seul détenez, et laisse la latence unitaire intacte.

Si un GPU est exclu : A en CPU (lever la limite à ≥ 8 cœurs) **et** B (N ≈ 12 – 16, après revalidation), puis C seulement
si l'usage le justifie.

## 6. La décision à rendre

```
CONCURRENCY_DECISION voie=A|B|C [gpu=oui|non] [cpus=<n>] [N=<plafond>] [clients=<n> donnée_usage=<référence>]
```
Selon la voie : A → je prépare la configuration et rejoue C0/C1 sur staging ; B → je rédige l'ADR et la campagne de
non-régression, **avant** toute mesure ; C → je rédige l'ADR de profil à partir de votre donnée d'usage, **avant** toute
mesure. Dans les trois cas, CONCURRENCE ne se ferme que par une preuve `VERIFIED` contre un budget déclaré avant elle.
