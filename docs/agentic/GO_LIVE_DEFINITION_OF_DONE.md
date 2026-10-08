# Définition de GO_LIVE_READY

> `CI_GREEN ≠ GO_LIVE_READY`. Une CI verte prouve le code et les gardes testées ; elle ne
> prouve ni la base, ni les droits, ni le déploiement.

`GO_LIVE_READY` est vrai **pour un SHA de `main` et une release précis**, à l'instant où
chaque critère ci-dessous est démontré par une preuve citée. Un critère non démontré vaut
`NO_GO`. Le verdict par défaut est `NO_GO`.

## Critères

| # | Critère | Preuve attendue | Catégorie |
|---|---|---|---|
| 1 | `main` exact identifié | SHA complet après `git fetch` | LIVE |
| 2 | CI de `main` verte sur ce SHA | runs GitHub `push` du SHA, tous `success` | LIVE |
| 3 | Aucune PR gouvernante requise en état invalide | liste des PR requises : fusionnées au SHA attendu ; aucune ouverte qui les remplace | LIVE |
| 4 | Release scellée | manifeste de release, `release_id`, ADR d'adoption | SEALED |
| 5 | Manifestes vérifiés | empreintes SHA-256 recalculées = empreintes déclarées | SEALED |
| 6 | Images par digest | Compose de promotion sans tag seul ; digests = inventaire de provenance | SEALED |
| 7 | Provenance de build vérifiée | workflow `production-image-provenance` sur le SHA, attestation vérifiée | SEALED/LIVE |
| 8 | Migrations appliquées en staging | HEAD des deux chaînes lu dans la base staging = HEAD du dépôt | LIVE |
| 9 | Ingestion complète | jobs terminés, aucun en échec ou en attente pour la release | LIVE |
| 10 | Cardinalités attendues | collections, artefacts, placements, chunks mesurés = valeurs dérivées des manifestes | LIVE vs SEALED |
| 11 | Scopes valides | chaque scope servi a son autorité r4 et son autorisation LOT41A active | SEALED/LIVE |
| 12 | Retrieval indépendant | sonde indépendante (`staging_retrieval_probe.py`) sur tous les scopes, zéro non-conformité | LIVE |
| 13 | Évaluation qualité | golden set revu par un humain, métriques au-dessus des seuils décidés | SEALED |
| 14 | Sauvegarde / rollback | sauvegarde restaurée sur volume neuf et rollback exercé, datés | LIVE |
| 15 | Secrets présents, jamais exposés | présence vérifiée sans lecture de valeur ; journaux sans secret | LIVE |
| 16 | Observabilité | métriques, alertes et journaux opérationnels vérifiés | LIVE |
| 17 | Garde de readiness | `python3 scripts/go_live/check_go_live_readiness.py --assert-ready` rend 0, en direct, sur ce SHA | LIVE |
| 18 | Autorisation production | décision humaine explicite pour ce SHA et cette release | humain |

Les critères 1–17 font `GO_LIVE_READY` ; le 18 autorise le déploiement (G6). Les preuves
sont archivées dans le rapport du lot de go-live, avec heure de lecture pour chaque
critère LIVE.

## Premier cut production visé

Cible logique au 29 septembre 2026, **à recalculer depuis les manifestes avant usage** :

| Composante | Collections | Artefacts | Placements | Chunks | Source |
|---|---:|---:|---:|---:|---|
| V4 hors HGGSP (reprise DI) | 9 | 263 | 405 | 5 678 | journaux opérateur DI (hors dépôt) |
| Successeur HGGSP | 2 | 52 | 74 | 2 590 | manifeste du successeur (scellé) |
| **Total** | **11** | **315** | **479** | **8 268** | somme |

Ces nombres sont une cible de contrôle (critère 10), pas une mesure. Un changement de
release les invalide.

## Ce que GO_LIVE_READY n'est pas

- un instantané committé (`go_live_readiness_state.json` se déclare lui-même non courant) ;
- un README ou un rapport, même récent ;
- une CI verte, une PR approuvée, une sonde sur fixture ;
- un souvenir de session ou une mémoire d'agent.
