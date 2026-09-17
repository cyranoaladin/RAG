# Lot CJ — Arbitrage de concurrence, par PR

- Lot : `LOT_GO_LIVE_FINAL_CJ_CONCURRENCY_ARBITRATION_PR`
- Branche : `go-live/concurrency-arbitration`
- Décision : `GO_LIVE_CJ_CONCURRENCY_ARBITRATION_PR_OPEN`
- Décision scellée : `docs/reports/go_live/concurrency_arbitration_decision.json`
- Ne ferme pas CONCURRENCE. Ne modifie ni le budget, ni le profil de charge, ni le moteur, ni aucun compteur.

**L'approbation de la PR de ce lot par abenrhouma vaut validation humaine du profil de concurrence retenu** : la voie A
(dimensionnement de la cible), sous le profil et le budget **inchangés**, avec le protocole de mesure et l'ordre de repli
fixés ci-dessous **avant** toute nouvelle mesure.

## Voie retenue : A — dimensionnement de la cible

1. Elle corrige le défaut réel : à 2 CPU, une requête **seule** coûte ≈ 3,6 s pour un p50 visé de 3 s. La concurrence
   n'est pas le premier problème.
2. C'est la seule voie qui ne touche ni à la qualité du retrieval, ni au budget.
3. B seul est insuffisant (même en ne rerankant que 8 candidats : ≈ 891 ms par requête à 2 CPU, ≈ 7 s sous 8 clients) ;
   C seul laisse la latence unitaire intacte.

Je le dis sans détour : sur CPU, aucune voie **seule** ne garantit le budget ; A est la plus sûre parce qu'elle peut
suffire (GPU, ou assez de cœurs) sans rien dégrader, et parce qu'elle se mesure en 3 minutes.

## Protocole pré-enregistré — fixé avant toute mesure, donc non ajustable après

| Étape | Règle |
|---|---|
| 1. Dimensionner | sur le staging cloisonné : lever la limite `cpus` du conteneur `ingestor` jusqu'à la capacité relevée en phase 0, en laissant au moins 2 cœurs et 4 Gio à la production ; GPU si l'hôte en expose un utilisable |
| 2. Mesurer C0 | 10 requêtes d'échauffement, puis les 30 requêtes gouvernées, une à la fois, délai 7500 ms |
| 3a. Si p50 séquentiel ≤ **375 ms** | rejouer C1 (8 clients, 240 requêtes) contre le budget **inchangé** ; CONCURRENCE ne se ferme que sur preuve `VERIFIED` |
| 3b. Si p50 séquentiel > 375 ms | le budget est arithmétiquement inatteignable (8 × service > 3000 ms) : **ne pas** lancer C1 ; sceller C0 comme diagnostic ; ouvrir le repli |

375 ms = p50 du budget (3000 ms) / 8 clients sérialisés : le seuil découle du budget, il n'est pas choisi (épreuve).

Ordre de repli, chacun par **sa propre PR de décision** :
1. **B — plafond de rerank** : ADR, N ∈ {16, 12} fixé dans l'ADR, non-régression qualité **avant** toute mesure de charge
   (golden queries, 30 requêtes gouvernées, 8 conditions du contrat de retrieval sur le corpus servable), budget inchangé.
2. **C — profil de charge de lancement** : ADR et donnée d'usage ; nouveau profil et nouveau budget fixés avant mesure,
   dans un commit distinct de toute fermeture ; l'ancien budget et sa mesure en échec restent versionnés.

Interdits : modifier budget ou profil après lecture d'une mesure ; fermer CONCURRENCE avec la preuve `BUDGET_FAILED` ;
activer un cache de recherche publique ; désactiver E5 ou le reranker ; mesurer sur un hôte non désigné.

## Conséquences

- **Approuvée** : dès le staging en place (lots CH et CI), j'applique l'étape 1, je mesure C0 et j'applique la règle 3a
  ou 3b. Lot CK.
- **Refusée** : CONCURRENCE reste ouvert, aucune mesure n'est rejouée.
- Compteurs : aucun ne change par cette PR. CONCURRENCE ne peut se fermer que par une preuve `VERIFIED` du lot CK.
- Dépendance : le staging cloisonné. Conditions d'arrêt : celles du plan d'exécution du staging, plus toute dégradation de
  la production pendant la mesure.

## Épreuves (exécutées en CI)

Décision scellée ; budget versionné inchangé et lié par empreinte (8 clients, p50 3000 ms, 0 erreur) ; l'arbitrage ne
ferme pas CONCURRENCE ; seuil de 375 ms cohérent avec le budget, ordre de repli et interdits présents.
