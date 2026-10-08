# Lot go-live — décision d'accès étudiant public, sans activation

- Branche : `go-live/student-public-v4-v5-20261008`.
- Base de lecture : `main` `0e47ea707c9dbdf68bc0c181e414da2577d4b332` ; arbre `b650b5096ad6e42e44c7b17d4ba08a1a7ce8846e`. Worktree propre de cette PR avant la commande : HEAD `f73e352a16af6671a30114a0fd061eeb77bc677f` ; arbre `2279169d2aea99b9a55e1d17fc29014fbec52907`.
- Cible relue **en lecture seule** le 2026-10-08 à 21:06:39.044692 UTC : hôte SSH `nexus-prod` (`korrigo`, connexion `root`), conteneur `nexus-staging-pgvector-1` (image `sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc`), base `ragdb_profile_gate_v4` sous rôle `raguser` ; transaction `BEGIN READ ONLY` puis `ROLLBACK`. La sortie brute porte cet horodatage et le marqueur `student_servability_left_join_v2`.
- Auteur du relevé : agent Codex exécutant, via les accès opérateur existants ; aucune valeur de secret n'est extraite. Requête versionnée : [SQL](go_live/evidence/student_servability_staging_20261008.sql), SHA-256 `2d3196aa446d70dca4beb7fba043625a35694f156d0296557c46ebfe9b0a6a21`. Résultat brut : [sortie](go_live/evidence/student_servability_staging_20261008.txt), SHA-256 `4772e36173a4f0a3adf3875262321137d93daed4b94bc6ae0ddffe643ad6aa55`.
- Décision proposée : ADR-0064 ; exécution différée selon `docs/runbooks/student_public_release_PLAN.md`.

Commande exécutée depuis la racine du worktree, après vérification du SHA et de l'arbre ci-dessus :

```sh
set -euo pipefail
ssh -o ProxyJump=none -o BatchMode=yes nexus-prod \
  'docker exec -i nexus-staging-pgvector-1 psql -X -A -F "|" -v ON_ERROR_STOP=1 -U raguser -d ragdb_profile_gate_v4' \
  < docs/reports/go_live/evidence/student_servability_staging_20261008.sql \
  > docs/reports/go_live/evidence/student_servability_staging_20261008.txt
sha256sum docs/reports/go_live/evidence/student_servability_staging_20261008.sql \
  docs/reports/go_live/evidence/student_servability_staging_20261008.txt
```

## État réellement mesuré

| Collection | Placements | Chunks sous ce scope | Visibilité | STUDENT_SERVABLE |
|---|---:|---:|---|---|
| `rag_nexus_dgemc_terminale_option` | 12 | 343 | `internal` | `false` |
| `rag_nexus_hggsp_premiere_specialite` | 39 | 1 858 | `internal` | `false` |
| `rag_nexus_hggsp_terminale_specialite` | 35 | 1 874 | `internal` | `false` |
| `rag_nexus_hlp_premiere_specialite` | 115 | 1 984 | `internal` | `false` |
| `rag_nexus_hlp_terminale_specialite` | 89 | 1 599 | `internal` | `false` |
| `rag_nexus_nsi_premiere_specialite` | 29 | 483 | `internal` | `false` |
| `rag_nexus_nsi_terminale_specialite` | 47 | 904 | `internal` | `false` |
| `rag_nexus_ses_premiere_specialite` | 30 | 726 | `internal` | `false` |
| `rag_nexus_ses_terminale_specialite` | 28 | 804 | `internal` | `false` |
| `rag_nexus_svt_premiere_specialite` | 19 | 663 | `internal` | `false` |
| `rag_nexus_svt_terminale_specialite` | 36 | 1 078 | `internal` | `false` |
| **Produit présent** | **479** | **8 268 chunks physiques** | **479/479 `internal`** | **0/11** |

Les colonnes `artifacts` et `scope_chunks` sont dédupliquées **dans chaque collection**, pas entre collections : un même artefact et ses chunks sont répétés dans plusieurs lignes. Leurs sommes valent respectivement 479 et 12 316 ; les totaux physiques distincts sont 315 artefacts et 8 268 chunks. La jointure externe de la requête conserve les placements d'artefacts sans chunks, si de tels cas apparaissent. Les 479 placements relus sont `active`, `reviewed` et `current` ou `official_snapshot` ; les 315 artefacts correspondants portent `rights=officiel_public`. Les 74 placements HGGSP V5 sont présents. Ce relevé ne qualifie pas à lui seul l'API ou l'accès public.

Le code au SHA de base fixe `_ROLE_VISIBILITIES['student'] = ('public',)` ; `build_server_retrieval_scope` refuse les scopes V4/V5 `internal` pour ce rôle. Pour les chunks gouvernés, le SQL de retrieval exige en plus `rag_artifact_placements.visibility` dans la portée signée et `rag_artifacts.rights` dans les droits admis. Les onze scopes du registre mixte portent `internal` ; les onze profils V4 et les deux politiques HGGSP V5 portent également `internal`. Les anciens `rag_chunks.visibility=internal` sont conservés, jamais changés pour masquer ce refus.

## Source et suites

- Manifeste V4 : `bab9c398f59eb8b0f2f5324ed28536525b37052ba075a4b5547e851b38cda4be` ; 11/315/479/8268, mais HGGSP V4 est remplacé dans l'union cible.
- Manifeste HGGSP V5 : `8286388002071e31a4d80d357feb19d802292c862055e6749d9371fc15441daf` ; 2/52/74/2590.
- Registre mixte : `59db12e82dcbf6fc1b7581a2576d728860d8828de55d72c04e6ab51c77071ab6` ; cible 9/263/405/5678 + 2/52/74/2590.
- Politique V4 : `83bbabb8f446a34e0745d1cb7a7eabcaae597dbd175d57a0eee99a07d78c630c` ; politique HGGSP V5 : `eee2f69e30d32c5c115b9446c1d0a186c7a049a2b132f1f48ba93d761d489eb2`.

La review humaine doit décider explicitement l'ouverture publique décrite par ADR-0064. Ce lot documentaire ne crée ni nouveau scope, ni release, ni placement, ni droit effectif et n'autorise aucune mutation staging ou production. La future PR technique devra livrer les octets scellés, les vérifications et les preuves de publication sur cible propre avant qu'un parcours étudiant puisse être déclaré passant.
