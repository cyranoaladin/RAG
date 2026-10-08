# Lot go-live — décision d'accès étudiant public, sans activation

- Branche : `go-live/student-public-v4-v5-20261008`.
- Base de lecture : `main` `1ab971838e90c876bf185da03b67423f9f0a32c9` ; arbre `cbdae38bedfe6a4ba9f3a1f32a6b29fe9bfa4c88`.
- Cible relue **en lecture seule** le 2026-10-08 à 20:12:50 UTC : hôte SSH `nexus-prod` (`korrigo`, connexion `root`), conteneur `nexus-staging-pgvector-1` (image `sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc`), base `ragdb_profile_gate_v4` sous rôle `raguser` ; transaction `BEGIN READ ONLY` puis `ROLLBACK`.
- Auteur du relevé : agent Codex exécutant, via les accès opérateur existants ; aucune valeur de secret n'est extraite. Requête versionnée : [SQL](go_live/evidence/student_servability_staging_20261008.sql), SHA-256 `14f27046bfd2b935db8de7f0299f7a8d48f12747fce5ae520dce51d2e9fe3b99`. Résultat brut : [sortie](go_live/evidence/student_servability_staging_20261008.txt), SHA-256 `8a6724dffbe310b8de11ca1d5b10194db83b39158949f9bc0d81851e82c12550`.
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
