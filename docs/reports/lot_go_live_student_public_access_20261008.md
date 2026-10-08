# Lot go-live — décision d'accès étudiant public, sans activation

- Branche : `go-live/student-public-v4-v5-20261008`.
- Base de lecture : `main` `ee35544bce5af74d6186ea0ef61f6902a2258ffe`.
- Cible relue **en lecture seule** le 2026-10-08 à 05:02 UTC : hôte SSH `nexus-prod`, conteneur `nexus-staging-pgvector-1`, base `ragdb_profile_gate_v4` ; transactions `BEGIN READ ONLY`.
- Décision proposée : ADR-0064 ; exécution différée selon `docs/runbooks/student_public_release_PLAN.md`.

## État réellement mesuré

| Collection | Placements publiés | Chunks publiés | Visibilité des placements | STUDENT_SERVABLE |
|---|---:|---:|---|---|
| `rag_nexus_dgemc_terminale_option` | 12 | 343 | `internal` | `false` |
| `rag_nexus_hggsp_premiere_specialite` | 0 | 0 | aucun ; r4 V5 `internal` | `false` |
| `rag_nexus_hggsp_terminale_specialite` | 0 | 0 | aucun ; r4 V5 `internal` | `false` |
| `rag_nexus_hlp_premiere_specialite` | 115 | 1 274 | `internal` | `false` |
| `rag_nexus_hlp_terminale_specialite` | 89 | 756 | `internal` | `false` |
| `rag_nexus_nsi_premiere_specialite` | 29 | 223 | `internal` | `false` |
| `rag_nexus_nsi_terminale_specialite` | 47 | 690 | `internal` | `false` |
| `rag_nexus_ses_premiere_specialite` | 30 | 466 | `internal` | `false` |
| `rag_nexus_ses_terminale_specialite` | 28 | 573 | `internal` | `false` |
| `rag_nexus_svt_premiere_specialite` | 19 | 592 | `internal` | `false` |
| `rag_nexus_svt_terminale_specialite` | 36 | 761 | `internal` | `false` |
| **Produit présent** | **405** | **5 678** | **405/405 `internal`** | **0/11** |

Les 405 placements présents sont `active`, `reviewed`, `official_snapshot` ; les 263 artefacts publiés portent `rights=officiel_public`. Les 13 autorisations r4 enregistrées pour les onze collections (11 V4 et 2 V5 HGGSP) ont toutes `visibility=internal`, `rights_categories={officiel_public}`, `pii_absence_attested=true`, aucune révocation et une validité observée au moins jusqu'au 2027-08-31. Les ressources HGGSP en contrôle restent `NEEDS_REVIEW` : ce relevé **précède** la publication V5 et ne doit pas être présenté comme un état final. Le conteneur PostgreSQL était `Up` mais déclaré `unhealthy` par Docker lors du relevé ; ce statut demande un diagnostic séparé avant qualification finale.

Le code au SHA de base fixe `_ROLE_VISIBILITIES['student'] = ('public',)` ; `build_server_retrieval_scope` refuse les scopes V4/V5 `internal` pour ce rôle. Pour les chunks gouvernés, le SQL de retrieval exige en plus `rag_artifact_placements.visibility` dans la portée signée et `rag_artifacts.rights` dans les droits admis. Les onze scopes du registre mixte portent `internal` ; les onze profils V4 et les deux politiques HGGSP V5 portent également `internal`. Les anciens `rag_chunks.visibility=internal` sont conservés, jamais changés pour masquer ce refus.

## Source et suites

- Manifeste V4 : `bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be` ; 11/315/479/8268, mais HGGSP V4 est remplacé dans l'union cible.
- Manifeste HGGSP V5 : `8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf` ; 2/52/74/2590.
- Registre mixte : `59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6` ; cible 9/263/405/5678 + 2/52/74/2590.
- Politique V4 : `83bbabb8f446a34e0745d1cb7a7eabcaae597dbd175d57a0eee99a07d78c630c` ; politique HGGSP V5 : `eee2f69e30d32c5c115b9446c1d0a186c7a049a2b132f1f48ba93d761d489eb2`.

La review humaine doit décider explicitement l'ouverture publique décrite par ADR-0064. Ce lot documentaire ne crée ni nouveau scope, ni release, ni placement, ni droit effectif et n'autorise aucune mutation staging ou production. La future PR technique devra livrer les octets scellés, les vérifications et les preuves de publication sur cible propre avant qu'un parcours étudiant puisse être déclaré passant.
