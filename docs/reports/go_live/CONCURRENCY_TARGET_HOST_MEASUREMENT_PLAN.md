# CONCURRENCE — plan de mesure sur l'hôte cible

Plan seulement : rien n'est mesuré ici, aucune connexion n'est ouverte. Exécution subordonnée à
`SSH_STAGING_AUTHORIZED` (staging en place, cf. `docs/runbooks/staging_externe_nexus_prod_cloisonne_EXECUTION_PLAN.md`), puis à un feu vert
distinct pour la charge complète.

## Ce qui ne bouge pas

- Budget : `docs/reports/go_live/concurrency_load_budget.json`, empreinte `0a8c0dc3384b9522658ee9f77669a3d463c060049bd8b033dfc8c8e6334db0b2`, déclaré avant
  la première mesure. **Inchangé.** 8 clients, 240 requêtes, 10 d'échauffement, délai client 7500 ms ; p50 ≤ 3000,
  p95 ≤ 6000, p99 ≤ 7500 ms ; 0 erreur, 0 timeout ; pic de connexions ≤ 10 ; 0 fuite ; 0 résidu.
- La preuve `BUDGET_FAILED` de #211 reste un diagnostic. Elle ne ferme rien, et ne sera pas « corrigée ».
- Verdict : `evaluer_concurrence` (source unique du gate), percentiles recalculés depuis les mesures brutes.
- Aucun mock, aucun cache activé, reranker et E5 réels, `k = 8`, `hybrid` et `rerank` à `true`.

## Pourquoi mesurer sur la cible

Sur le poste de travail (16 threads) : 2,3 s par requête, plafond ≈ 0,85 req/s pour 2,67 requis. Mais le conteneur
`ingestor` est limité à **2 CPU** : le profilage y donne ≈ 3,6 s pour une requête **unique**. La vraie question est
donc d'abord celle de la requête seule sur la cible, avant celle de la concurrence.

## Étapes

**C0 — Référence séquentielle (coût faible, décisive).** 10 requêtes d'échauffement puis les 30 requêtes gouvernées,
une à la fois, délai 7500 ms, depuis le poste par tunnel **et** depuis l'hôte en loopback (pour isoler le réseau).
Charge ≈ 2 CPU pendant ≈ 2–3 min. Lecture :

| p50 séquentiel sur la cible | Conséquence |
|---|---|
| > 3000 ms | le budget est inatteignable à 8 clients **et même à 1**. Inutile de lancer C1 : décision de dimensionnement (§ Décisions) |
| 375 – 3000 ms | 8 clients sérialisés dépasseront p50 (8 × service). C1 le confirmera ; à lancer seulement si vous voulez la mesure scellée |
| ≤ 375 ms | C1 a une chance réelle de passer |

**C1 — Profil complet, inchangé** (feu vert distinct : ≈ 5–10 min à 2 CPU saturés sur la machine de production).
240 requêtes, 8 clients, mêmes 30 requêtes gouvernées, mêmes vérifications par réponse (résultats, citations,
artefact attendu). Échantillonnage de `pg_stat_activity` par `docker compose -p nexus-staging exec pgvector psql` ;
empreinte de la base avant/après ; conteneurs de production comparés avant/après (aucun redémarrage).

**Outillage à écrire (lot dédié, après autorisation)** : un client de charge pointant une URL, reprenant
`_one_request` du banc existant et le même budget ; le banc actuel démarre lui-même moteur et base, il ne sait pas
viser un hôte. Le scelleur reçoit un mode « hôte cible » : `observed_on: target_host_cloisonne`, résidus =
conteneurs `nexus-staging` uniquement. Tests de refus inchangés.

## Garde-fous de la mesure

- Fenêtre hors usage ; arrêt immédiat si la latence ou la charge de la production se dégrade.
- Une seule mesure de fermeture par configuration ; toute mesure, bonne ou mauvaise, est scellée et versionnée.
- Aucune modification du moteur entre C0 et C1. Aucun réglage « pour voir » suivi d'une re-mesure silencieuse.

## Décisions possibles après mesure (toutes humaines)

1. **Dimensionnement** : lever la limite CPU du conteneur, GPU, ou service d'inférence dédié — puis rejouer C0/C1 tels quels.
2. **ADR de plafond de rerank** (N premiers candidats après RRF) : change la qualité ; revalidation des golden queries
   et du seuil 1,90 **avant** toute mesure de charge ; N fixé dans l'ADR. Seul, il ne suffit pas (N = 8 : ≈ 891 ms à 2 CPU).
3. **ADR de profil de charge** — *uniquement* si l'usage réel le justifie.

## Quand, et seulement quand, proposer l'ADR de profil

Aucun ADR n'est proposé aujourd'hui : rien ne démontre que 8 recherches simultanées soit disproportionné. Il ne sera
rédigé que si les **trois** conditions sont réunies :

1. vous fournissez une donnée d'usage (effectifs, recherches par séance, simultanéité attendue ou observée) ;
2. cette donnée donne un niveau de simultanéité cible différent de 8, justifié par l'usage et non par la latence mesurée ;
3. l'ADR fixe le nouveau profil **avant** toute nouvelle mesure, dans un commit distinct de toute fermeture, et l'ancien
   budget reste versionné avec sa mesure en échec.

Un profil abaissé parce que la mesure a échoué serait un faux vert. Ce plan ne l'autorise pas.
