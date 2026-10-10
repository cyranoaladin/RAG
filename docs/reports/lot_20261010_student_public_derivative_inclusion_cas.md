# Lot — inclusion probante des dérivés étudiants

Date UTC : 2026-10-10. Base de développement : `f74c0ad766b434fb9554b20324590d7ae4d17582`.

Le vérificateur indépendant relit le candidat #312, les deux rapports
individuels PII/actualité et 253 chaînes de preuve depuis un CAS privé durable.
Le CAS contient 1 790 fichiers (182 002 351 octets), dont 253 textes dérivés,
253 PDF sources privés, 253 reçus de dérivation, 253 preuves de source #300,
253 anciens et 253 nouveaux checkpoints, 253 reçus GET et neuf reçus de
listings distincts, ainsi que l'autorité Éduscol–Etalab scellée. Chaque fichier et la population exacte sont contrôlés par
SHA-256. L'index CAS est lié par le digest
`859b8ef80be5554e0a8979eacb15a17dbf8ee1eeb697dbc4188e67c623a5d9e1`.
Le paquet doit demeurer hors dépôt, en accès privé. Il ne constitue pas le
transfert des octets vers la cible d'ingestion finale.

Autorités relues : Éduscol–Etalab
`013527a0819e548f9962f04676aee5c02707c717b01296a6f61d59f30d8b0ec1`, adjudication PII
`7bf534b50a7eef90ca34d52daa22293a835273b0b2abf556d48e976721d05dd0`
et attestation d'actualité/révocation
`4882c95b47e807f0efe55ee5768637b47907af4d5f91e331a0e273acf684e62d`.
Le rapport de simple dépistage par motifs est refusé comme autorité d'inclusion.
La fraîcheur des captures expire 24 h après le constat source, le
`2026-10-11T13:43:39.206000Z`. Une promotion différée exige un nouveau rejeu.

La feuille déterministe
`docs/reports/go_live/student_public_derivative_inclusions_20261010.json`
porte le SHA-256
`3c47e0eb9f854508e29c45fe2288f2543bfb3faac7dfcc8b20461d8613f68a1d` :
253 décisions `INCLUDE`, zéro `PENDING`, liées à chaque paire de preuves et au
CAS. Le constructeur refuse l'ancien format V1 à simples SHA déclaratifs et
rejoue le CAS avant toute émission. Il a préparé un nouveau paquet immuable
`student-public-successor-20261010-8438d2d225eb9ea8`, manifeste
`636c2bba0273ac64c3f69ffc2fec4019756c7d9048849df00b7f3ee35def9e4d` :
11 collections, 253 artefacts textuels, 377 placements, 3 975 chunks.

L'index V2 (`be7db07c4064cd03cd08f6c8a0ab05a21ec38d9cf97918e21baae65ce8c68d40`)
lie les digests des registres de droits (`f935ab39a87790125641f1c5434a6a736f968be44ae370fe465cf60fe3bac0a2`),
d'actualité et révocation par dérivé (`a6c97f8cbab533f2b06bb646512484ae9c19da29a8ad2cf15a38b6b1e55f268b`)
et PII (`c977fbc3d2316dedb2d4c5cfad77fc09f90e681334eb37a04c0af4bfd06328a0`).
Chaque ligne du registre de droits relie le SHA du dérivé exact, son PDF source,
l'autorité globale et la preuve d'actualité. Ces registres ne sont pas une
autorisation de publication.

Les onze sujets et identifiants de scopes **proposés, non émis** sont liés
dans `preparation-index.json` :

| Collection | SHA-256 du sujet préparatoire | Scope proposé |
| --- | --- | --- |
| `rag_nexus_dgemc_terminale_option` | `7bcc7c2d9f4feac1b7bf6f2c47fc6af098f10b18021b63b4c73fb0c5b7548b85` | `student_public_dgemc_terminale_option_v1` |
| `rag_nexus_hggsp_premiere_specialite` | `eb5a7260de2cdc7a8c84b8eed9d517ad20cf3265744be23f19d0d78ed66bdf66` | `student_public_hggsp_premiere_specialite_v1` |
| `rag_nexus_hggsp_terminale_specialite` | `b981d2a14b486d8c46e7fab2fd53d4f42c47f7226950e79b5ed36a16fee1eba1` | `student_public_hggsp_terminale_specialite_v1` |
| `rag_nexus_hlp_premiere_specialite` | `34b03b403ee5cb97c5f5866b3c1a725946a05fd6245918d0af348449a2347edf` | `student_public_hlp_premiere_specialite_v1` |
| `rag_nexus_hlp_terminale_specialite` | `62dc0feffde57f3ec415f1cf2a271b104d4986a6bae6bd4aa0a5f59c3b1cae29` | `student_public_hlp_terminale_specialite_v1` |
| `rag_nexus_nsi_premiere_specialite` | `0f30d7d53c5b7842e93167dc7fb8aa7ee4e07c28873c3c69c1db1f44a3d893c3` | `student_public_nsi_premiere_specialite_v1` |
| `rag_nexus_nsi_terminale_specialite` | `73808c50eb25a606ba4b84000406c07c45937090b0d362deb88ab2b6676c6734` | `student_public_nsi_terminale_specialite_v1` |
| `rag_nexus_ses_premiere_specialite` | `b267742ed8c043c0e24362e14b3b4872ed5b6cb30b3b0f927f43135b2ce8ad96` | `student_public_ses_premiere_specialite_v1` |
| `rag_nexus_ses_terminale_specialite` | `2d38eec9ae8c0504c4c533a40c3cdf573a6460b7b4a502d837ec4fe8cf75c6ff` | `student_public_ses_terminale_specialite_v1` |
| `rag_nexus_svt_premiere_specialite` | `fb3a3997438c439a83aa34aa0ee975c4be62758c8133c1c89bb39f9c0d44c30c` | `student_public_svt_premiere_specialite_v1` |
| `rag_nexus_svt_terminale_specialite` | `150e68d2090a79b6f92067d15959aec1ae9393a4e43a74f9a84288292bbe48f8` | `student_public_svt_terminale_specialite_v1` |

Statut du paquet : `PREPARATION_ONLY_NOT_ACTIVABLE`, `NOT_TRANSFERRED`,
`candidate/NOT_PROMOTABLE/PRE_REVIEW/NO_PRODUCTION_ACTIVATION`. Aucun PDF
source n'entre dans les artefacts publics ; aucun déploiement staging ou
production n'a eu lieu. Le digest d'inclusion et les preuves d'actualité ne
constituent ni revue de scope exacte, ni autorisation successeur, ni reçu de
transfert de la cible finale. Le schéma `public_successor` demeure bloqué.

Vérifications du lot : 33 tests ciblés verts, dont les tests du constructeur et du vérificateur ; sabotage de
statut PII, fraîcheur périmée, source croisée avec digest de ligne recalculé,
reçu privé manquant, octets CAS altérés, autorité de droits modifiée, population incomplète et format V1.
Ruff vert sur les quatre fichiers Python modifiés ou créés.
