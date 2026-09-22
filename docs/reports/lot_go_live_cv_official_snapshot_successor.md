# Lot CV — publier un instantané officiel sans le déclarer vérifié, et préparer le successeur de V2

**Branche** : `go-live/cv-official-snapshot-currentness`
**Base** : PR #246 (lot CU), empilée — ce lot dépend de la projection batch
et de l'attestation LOT42-RELEASE-BATCH-V1 qu'elle introduit.
**Décision instruite** : ADR-0059 (Proposé), `nexus-contracts` 0.19.0 → 0.20.0.

Aucune écriture sur staging ni production. Aucune release existante n'est
modifiée. Aucun verrou de gouvernance n'est touché.

## 1. Le fait qui a réorienté le lot

Le lot CU concluait que l'actualité du candidat V2 ne pouvait pas être
régénérée honnêtement sans une décision de gouvernance nouvelle, et
proposait trois voies — dont une livraison réduite à 5 contenus sur 315.

Mesuré sur les fichiers du dépôt, cette conclusion ignorait un fondement
**déjà adopté** :

| Source | Ce qu'elle dit des 315 contenus publiés |
|---|---|
| `docs/reports/handoff/servability_matrix_v1.json` (ADR-0055 appliquée) | **315 × `OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE`**, verdict `CANDIDATE_NO_BLOCKING_DIMENSION` ; **0** `VERIFIED_CURRENT` |
| `currentness_network_audit.json` de V2 | `CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE`, `verified: 0` sur 486 |
| `currentness_evidence.json` de V2, livré à côté de cet audit | 486 × `CURRENT`, `byte_identity: true`, « downloaded read-only and byte-matched » |
| La politique elle-même | « `OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE` n'est pas `VERIFIED_CURRENT`, et ces deux valeurs ne doivent jamais se confondre dans une release » |

L'actualité de V2 **contredit l'audit livré avec elle** : c'est la
contrefaçon que l'ADR-0055 interdit. Le producteur courant ne la commet
plus (il écrit `REVIEW_REQUIRED`), mais le runtime ne connaissait que
`CURRENT` et `REVIEW_REQUIRED` : une actualité honnête rendait la release
impubliable, alors que la gouvernance l'avait déclarée servable.

Le manque était donc d'implémentation, pas de gouvernance. Les deux
rapports du lot CU ont été rectifiés sur place (commit `21058c68` sur
#246), historique conservé.

## 2. Ce que le lot change

*(sections détaillées ci-dessous — voir aussi ADR-0059)*

| Maillon | Avant | Après |
|---|---|---|
| Preuve d'actualité | `CURRENT` / `REVIEW_REQUIRED` | V3 : les quatre dispositions ADR-0055, faits exigés par disposition, V1/V2 lus à l'identique |
| Résolveur multi-niveaux | refuse tout sauf `CURRENT` | publie un instantané en `official_snapshot`, cité par la provenance de son artefact |
| Produit (migration 005) | `currentness ∈ {current, archive, review_required}` | + `official_snapshot`, servi par le retrieval |
| Contrat de revue batch | `currentness: "current"` | `"current"` ou `"official_snapshot"`, uniforme, jamais mélangé |
| Projection batch | lecture **brute** des fichiers d'actualité et de PII | chargeurs **canoniques** : actualité vérifiée, PII vérifiée avec jeu de décisions, reçu, ancre et chaîne de revue confrontée au manifeste |
| Porte de projection | `current` + `CLEARED` | `current`/`official_snapshot` + `CLEARED`/`DETECTED_REVIEWED_ACCEPTED`, et seulement d'origine `DERIVATION` |
| Enregistrement d'une attestation batch | actualité approuvée **jamais** comparée à l'actualité persistée | comparée |
| Successeur d'une release acquise | aucun chemin (tout sélectionne par `release_id` du payload) | **adoption** en ajout seul (migration de contrôle 018), bijection et égalité exacte des faits non corrigés |
| Worker B | ne vérifiait pas que l'artefact appartient à la release attestée | refuse un artefact ni acquis sous, ni adopté par la release |
| `--only-attributions` | code 0 sur un rattrapage vide | code 1, rien n'est validé |
| Readiness produit (`release-chain`) | `currentness != "current"` compté faux | égalité à l'actualité que la release prescrit |
| Producteur de release | recopie en répétition l'inventaire, l'actualité et la PII | réémet inventaire (comptes justes), actualité V3 dérivée de la matrice, PII sous le scanner courant ; refuse un scanner non déclaré |

## 3. Mesures

*(à compléter au point de consolidation)*
