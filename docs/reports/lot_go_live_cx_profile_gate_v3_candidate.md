# Lot CX — construire le successeur profile-gate V3, le comparer à V2, le rejouer

- Branche : `go-live/cx-v3-build-diff-loaders`
- Base : `b2ffbc7a5ecb776ac1be6863635fc0bb17f592ad` (main après #249)
- Lots précédents : CV (#247, successeur prêt en code), CW (#248, #249 : jeu de
  décisions PII V3 et son reçu ADR-0035)

## Portée

Ce lot livre l'outillage de construction et de contrôle du successeur V3, et
le candidat V3 qu'il a produit. Il ne publie rien, n'active rien, n'écrit dans
aucune base et ne modifie aucun verrou de gouvernance. Le candidat est
`NOT_PROMOTABLE`, `NO_PRODUCTION_ACTIVATION`, `PRE_REVIEW`, mode `rehearsal` ;
le moteur refuse une telle release en environnement de production
(`_validate_unpromoted_release_guard`).

## Outillage

| Élément | Rôle |
|---|---|
| `scripts/go_live/build_profile_gate_v3.sh` | essai à blanc, construction dans un répertoire neuf, diff V2→V3, rejeu des chargeurs ; refuse une sortie existante ou des autorités non commitées ; le motif d'écart d'autorité cite, pour chaque autorité PII, le dernier commit qui a touché son fichier |
| `scripts/go_live/diff_profile_gate_releases.py` | diff JSON canonique : champs du manifeste, autorités, octets de chaque fichier, artefacts et identité de leurs chunks, placements, statut PII et disposition d'actualité par contenu |
| `attest_publication_cli verify-release-sources` | rejoue en lecture seule `_charger_sources_scellees` — catalogue scellé, inventaire, actualité (chargeurs canoniques), PII avec sa chaîne de revue, droits — et résume leur verdict ; aucun chargeur réimplémenté |

Tests : `scripts/tests/test_diff_profile_gate_releases.py` (5) et
`services/rag-engine/tests/test_verify_release_sources_cli.py` (4, dont V2 réel
refusé par son propre inventaire et V3 réel accepté).

## Choix techniques

- **Mode `rehearsal`** depuis la lignée `profile_gate` avec le registre
  d'exclusion (4 contenus) : c'est le mode de V2, le seul qui réémet la preuve
  PII depuis les PDF et lie la chaîne de revue ; le mode production re-découpe,
  ce que l'adoption d'ADR-0059 § 5 (égalité exacte des chunks) interdit.
- **`review_status` = `PRE_REVIEW`** (défaut, comme V2) : la revue PII porte sur
  les contenus ; la release candidate n'a pas encore été relue en tant que telle.
- **Référence** : la release V2 (`release-1b9eba0c0eb0ab13`), pas V1.
- **Entrées** : matrice `servability_matrix_v1.json` (`5dc4c898…`), registre
  d'exclusion (`07a346b8…`), politique d'actualité par défaut (`4226aba5…`),
  miroir des PDF (315 fichiers, tous rehachés), manifeste de transfert V2
  (même ensemble de 315 artefacts), registre des droits du dépôt.

## Résultat

- Release : `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_v3/release-f8fb983d04f4b7c1`
- Manifeste `production-profile-gate.release.json` :
  `c0f5897bf0a2d2f388ba0534de2cc4bb3198ab5d68173f4d28713572ce222e16`
- 315 artefacts, 479 placements, 11 collections, 8 268 chunks
- Déterminisme : une répétition hors dépôt, depuis un autre commit portant les
  mêmes autorités, a produit des octets identiques (`diff -r` vide).
- Motif d'écart (`docs/reports/evidence/lot_cx_profile_gate_v3/authority_change_motive.txt`) :
  4 autorités ajoutées, 4 preuves par commit (`AUTHORITY_MOTIVE_PROVEN`).

### Diff V2 → V3 (`diff_v2_v3.json`, `d9f9305d…`)

| Dimension | Constat |
|---|---|
| Artefacts | 315 = 315 ; 0 ajouté, 0 retiré, 0 champ modifié ; identité des chunks inchangée (8 268) |
| Placements | 479 = 479 ; 0 ajouté, 0 retiré |
| PII | 293 `CLEARED` → `CLEARED` ; 22 `CLEARED` → `DETECTED_REVIEWED_ACCEPTED` |
| Actualité | 315 `CURRENT` → `OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE` (ADR-0055/0059 : instantané officiel, jamais « actuel ») |
| Autorités ajoutées | `pii_decision_set_sha256`, `pii_review_index_sha256`, `pii_review_receipt_sha256`, `pii_review_trust_anchor_sha256` |
| Autorités régénérées | `candidate_inventory_sha256`, `currentness_evidence_sha256`, `pii_evidence_sha256` |
| Manifeste | seul champ scalaire modifié : `release_id` |

Les 4 contenus « retirés » des preuves PII et d'actualité sont les exclus
ADR-0055, déjà absents du catalogue V2 (315).

### Chargeurs canoniques sur V3 (`canonical_loaders_v3.json`, `424deff0…`)

`SEALED_SOURCES_VERIFIED=production-profile-gate-2026-2027-v3` : 315 artefacts,
293 `CLEARED`, 22 `DETECTED_REVIEWED_ACCEPTED`, 0 refus PII, 315
`OFFICIAL_SNAPSHOT_NETWORK_UNVERIFIABLE`, chaîne de revue vérifiée égale à celle
que la release déclare (jeu `1b70d91b…`, reçu `22361dd1…`, ancre `a7835fc6…`,
index `abdd1525…`). Pour comparaison, V2 est refusée par son propre inventaire
(`unique_artifacts count differs`), défaut antérieur consigné au lot CU.

## Ce qui reste, par ordre de dépendance

1. Revue et fusion de ce candidat.
2. Image worker (contrats 0.20.0), provenance, amendement de l'autorisation
   staging pour V3.
3. Staging, sous son autorisation : migrations produit 005 et contrôle 018,
   readiness, rattrapage d'attribution des 479 lignes V2, adoption
   (`adopt-predecessor-release`), revue batch dans sa fenêtre, Worker B,
   vérification indépendante et retrieval.
4. Recette, qualification d'exploitation, promotion et déploiement de
   production, chacun sous son autorisation propre.

## CI

Référence : les checks GitHub Actions du head `94d28160` — tous verts
(contrats, pdf-page-policy, release-chain, rag-pedago, rag-engine, cockpit,
verrous de gouvernance, contrôles du dépôt, scripts/tests, qualification,
acceptation modèle réel, image worker, governance postgres, GitGuardian).

Localement (disque à ~8 Go, aucun venv neuf installable ; venvs de `main`
empruntés avec `PYTHONPATH` sur ce worktree) :

| Cible | Résultat |
|---|---|
| verrous de gouvernance | 18/18 inchangés |
| unicité des autorités (+ garde) | vert |
| hygiène du dépôt (+ tests), taxonomie, preuves de sources | vert |
| scripts/tests | 540 réussis ; 4 échecs `disk_policy_ok`, préexistants (`lot_go_live_cw_dettes.md`) |
| rag-pedago | 3 558 réussis ; 1 échec `test_cleanup_dry_run` provoqué par la poussée de la branche pendant le run (ligne de suivi git), vert au rejeu et sur GitHub |
| rag-engine | ruff, mypy verts ; échecs locaux dus au venv emprunté (`nexus_release_chain` d'un autre checkout, empreinte d'environnement) ; verts au rejeu avec les paquets du worktree, et sur GitHub |
