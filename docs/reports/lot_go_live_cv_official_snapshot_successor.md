# Lot CV — publier un instantané officiel sans le déclarer vérifié, et préparer le successeur de V2

**Branche** : `go-live/cv-official-snapshot-currentness`
**Base** : `main` (PR #246 fusionnée : `f430aa15`).
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

## 3. Mesures (candidat final de ce lot, pas une comparaison historique)

| Suite | Résultat |
|---|---|
| Installation propre `make install` (rag-engine, rag-pedago) | `rc=0`, `pip check` : aucun conflit |
| `nexus-contracts` | 934 vertes (925 + 9) ; contre-épreuve dans une copie isolée du contrat 0.19.0 : les 2 épreuves positives échouent, les 7 invariants tiennent |
| rag-engine unitaire (`-m "not integration"`) | 0 échec |
| rag-engine `mypy src` | aucun constat, 148 fichiers |
| `make test-governance-pg` (répétition complète de retour arrière/réapplication, trou refusé puis reprise, bootstraps concurrents, runner de rollback — 018 comprise) | `rc=0`, 0 échec |
| Migration 018, intégration | 12/12 |
| Acceptation batch, E5 réel, deux PostgreSQL | 17/17 : les 15 scénarios existants + le successeur qui adopte puis publie + la lignée étrangère refusée |
| Migration produit 005 (`test_hybrid_integration.sh`, `test_lot40_hybrid_pgvector.py`) | PASS ; 51/51 — montée depuis 004 sans réécrire de ligne, rejeu à la tête, rollback refusé en présence d'un instantané, restauration exacte des définitions 004, empreintes relues sur base réelle |
| `packages/release-chain` | 56 vertes |
| rag-pedago | 3552 vertes, 4 ignorées (préexistantes, ci-dessous), 0 échec |
| `scripts/qualification` | 3 épreuves périmées par ce lot corrigées (§5), vertes |

Mutations sur la planification d'adoption : les 8 gardes neutralisées une à une
sont toutes détectées.

### Épreuves ignorées, et leur incidence

Aucun `skip` ni `xfail` ajouté. Les quatre ignorées de rag-pedago sont
préexistantes et exigent une matière qui ne se versionne pas :

| Épreuve | Motif | Incidence |
|---|---|---|
| `test_corpus_catalog_compiler.py:1375` | corpus scellé réel absent | couverte en intégration opérateur |
| `test_finding_identity.py:207` | paquets de revue PII réels (matière personnelle) | idem |
| `test_model_snapshot_completeness.py:114` | instantanés de modèle | couverte par l'acceptation E5 réelle |
| `test_recompute_final_release_set.py:311` | preuves scellées externes | aucune sur ce lot |

## 4. Le successeur V3 — état

Le producteur sait construire le successeur `production-profile-gate-2026-2027-v3` :

- actualité V3, avec 315 × `OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE` et 0 vérifié ;
- inventaire aux comptes justes (479 placements, 315 contenus, 164 multi-placements) ;
- les 315 URL d'artefact identiques à V2, dont 13 URL de fichier officielles ;
- preuve PII régénérée sous le scanner courant ;
- refus d'un scanner non déclaré.

**Il n'est pas encore construit**, parce que la règle ADR-0047 refuse le jeu du 03/09 sur la population 315 : ce jeu décide d'un contenu exclu, et son index porte sur 320 contenus. Le propriétaire du corpus a retenu le 2026-09-22 la voie A3 (ADR-0059 §6), et une campagne canonique neuve est prête :

| Élément | Valeur |
|---|---|
| Base du run `8bbaa039…` | conteneur `nexus-drive-staging-restored-20260917`, lu en lecture seule ; 2473 artefacts, partition des pages identique au rapport du run, 315/315 contenus présents |
| Index versionné (empreintes seules) | `docs/reports/evidence-index/pii_review_index_20260922_profile_gate_v3.json`, `abdd1525…` ; population revue `04b731e2…` (les 315), 22 paquets, 48 constats |
| Concordance avec le 03/09 | identifiants de constats identiques 22/22 ; `157309db` absent |
| Paquets et brouillon (hors dépôt, 700/600) | `/home/alaeddine/nexus-pii-review-20260922-profile-gate-v3/` ; brouillon `5632900d…`, tout à `__A_DECIDER__` |

L'inventaire Drive d'origine (`9e8e09db…`) est introuvable. Il a été
reconstitué pour les 315 contenus comme copie en lecture des lignes du run
lui-même. Il ne sert que de localisateur : chaque fichier est rehaché.

## 5. Défauts trouvés et corrigés en chemin

- La projection batch lisait des déclarations **brutes** : une ligne se disant `CURRENT` ou `DETECTED_REVIEWED_ACCEPTED` sans passer les chargeurs aurait ouvert la porte.
- L'enregistrement d'une attestation batch ne confrontait **pas** l'actualité approuvée à l'actualité persistée.
- Worker B ne vérifiait pas qu'un artefact appartient à la release attestée.
- `--only-attributions` sortait en 0 sur un rattrapage vide.
- Le banc semait des lignes d'un format que Worker A n'écrit pas : il sème désormais `sealed_placement_evidence`.
- Le sceller PII plantait sur un index canonique (`page_number`).
- Trois épreuves de qualification jugeaient un comportement que ce lot change. L'épreuve de périmètre CH5 jugeait toute branche contre le périmètre de CH5, et ne jugeait rien en CI (clone superficiel). Elle juge désormais le commit CH5 lui-même.

## 6. Observations sans correction

- `servability_matrix_v1.json` porte `"applied": false`, littéral de son producteur antérieur au câblage ; la politique qu'elle applique se déclare `applied: true` et le producteur la charge par `charger_politique`.
- `requests` avertit de `chardet 7.4.3` (tiré par `unstructured`) : la borne `<6` ne vaut que pour l'extra `use_chardet_on_py3`, non installé ; `pip check` est propre.
- Les payloads acquis ne sont immuables que par procédure : `app_role` a `UPDATE` sur `resources`, `resource_candidates` et `artifacts`. À instruire séparément.
- Le jeu de décisions PII du 17/09 (149 décisions), nommé par le registre d'exclusion et la matrice, n'a pas de reçu ADR-0035.
- GitGuardian 37529040 sur #247 : faux positif (identifiant de test `scope_authorization_id`), à classer.

## 7. Suite, par ordre de dépendance

1. Relecture et décision des 22 contenus (humain), scellement, PR du jeu de décisions, approbation, reçu.
2. Construction du successeur V3 (commande prête), diff machine V2→V3, chargeurs canoniques rejoués sur ses octets, PR du candidat.
3. Image worker (contrats 0.20.0), provenance, amendement de l'autorisation staging.
4. Staging : migrations produit 005 et contrôle 018, readiness du successeur, rattrapage d'attribution des 479 lignes V2, adoption, revue batch, Worker B, vérification indépendante et retrieval.
