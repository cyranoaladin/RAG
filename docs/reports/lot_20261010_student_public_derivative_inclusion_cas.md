# Lot — inclusion probante des dérivés étudiants

Date UTC : 2026-10-10. Base de développement : `f74c0ad766b434fb9554b20324590d7ae4d17582`.

Le vérificateur indépendant relit le candidat #312, les deux rapports
individuels PII/actualité et 253 chaînes de preuve depuis un CAS privé durable.
Le CAS contient 1 817 fichiers (193 728 689 octets), dont 253 textes dérivés,
253 PDF sources privés, 253 reçus de dérivation, 253 preuves de source #300,
253 anciens et 253 nouveaux checkpoints, 253 reçus GET, neuf reçus de
listings distincts avec leurs 27 corps HTML normalisés, textes extraits et
captures, ainsi que l'autorité Éduscol–Etalab scellée. Chaque fichier et la
population exacte sont contrôlés par SHA-256. L'index CAS est lié par le digest
`09dc8eeaf5e853b3e793eca6b2ef339a5ad4366ed44a1f20d47140d31f8b69e6`.
Le paquet doit demeurer hors dépôt, en accès privé. Il ne constitue pas le
transfert des octets vers la cible d'ingestion finale.

Autorités relues : Éduscol–Etalab
`013527a0819e548f9962f04676aee5c02707c717b01296a6f61d59f30d8b0ec1`,
adjudication PII
`7bf534b50a7eef90ca34d52daa22293a835273b0b2abf556d48e976721d05dd0`
et attestation d'actualité/révocation
`4882c95b47e807f0efe55ee5768637b47907af4d5f91e331a0e273acf684e62d`.
Le rapport de simple dépistage par motifs est refusé comme autorité d'inclusion.
La fraîcheur est bornée par chaque reçu de listing, GET, actualité et révocation,
ainsi que par la clôture de l’index ; chaque capture doit précéder cette clôture
de moins d'une heure. Le plus ancien listing expire le
`2026-10-11T13:39:22.520000Z`. Une promotion différée exige un nouveau rejeu.

La feuille déterministe
`docs/reports/go_live/student_public_derivative_inclusions_20261010.json`
porte le SHA-256
`efd88ef80d63c6a4b999bfed2c7aab0eef52e6e0c22dc17a968cdc02a00cb899` :
253 décisions `INCLUDE`, zéro `PENDING`, liées à chaque paire de preuves et au
CAS. Le constructeur refuse l'ancien format V1 à simples SHA déclaratifs et
rejoue le CAS avant toute émission. Il a préparé un nouveau paquet immuable
`student-public-successor-20261010-d5f2bcf9e44c2a79`, manifeste
`54b35f6187e0a4f5bec46ca70f1f0de34b13e5d403cfa36cb55bc3dd98b2a714` :
11 collections, 253 artefacts textuels, 377 placements, 3 975 chunks.

L'index V2 (`773ee81f00a64e1f8939822bc060cfe32a66c7dee2b7c873f7431f53ec853f9a`)
lie les digests des registres de droits (`03c7761b16840da036997b0c24878bcc4b08f11093e8e45eb7c58164c5812f3e`),
d'actualité et révocation par dérivé (`17bf6d706068e8a96824bee38b5bbb79bbe0d4c68779d7d206a0321ba3153ed6`)
et PII (`bd66e3ce15e42a0d45ab3e49181bd5834e37141d9c0a3417e88b77b8f5a2bec8`).
Chaque ligne du registre de droits relie le SHA du dérivé exact, son PDF source,
l'autorité globale et la preuve d'actualité. Ces registres ne sont pas une
autorisation de publication.

Les onze sujets et identifiants de scopes **proposés, non émis** sont liés
dans `preparation-index.json` :

| Collection | SHA-256 du sujet préparatoire | Scope proposé |
| --- | --- | --- |
| `rag_nexus_dgemc_terminale_option` | `a8d0864ba2c9074b78c9285e625fc4d3a20d089c88181b7ee57959cbefc82c52` | `student_public_dgemc_terminale_option_v1` |
| `rag_nexus_hggsp_premiere_specialite` | `5c398cb380fa31c3915eab289fd2dabf525f208205f22cd1d81ac85c8feeb40a` | `student_public_hggsp_premiere_specialite_v1` |
| `rag_nexus_hggsp_terminale_specialite` | `b68423979b26cc95ee2ff8b55561e068dc4c0757e64dac0471d1b5fdcaa02d25` | `student_public_hggsp_terminale_specialite_v1` |
| `rag_nexus_hlp_premiere_specialite` | `6cf215bac0ab2a8a5d8e1ca3ea398f66a3b7c128cdd2e186801c203de5cda639` | `student_public_hlp_premiere_specialite_v1` |
| `rag_nexus_hlp_terminale_specialite` | `ba026df87133dfe756c891d6ee6159fef12ad3b43f02d48fba5f2cb0a1d20577` | `student_public_hlp_terminale_specialite_v1` |
| `rag_nexus_nsi_premiere_specialite` | `9c181906db4430012f12f493bbb97adb12ea17642a3cc772937d765af76638c4` | `student_public_nsi_premiere_specialite_v1` |
| `rag_nexus_nsi_terminale_specialite` | `d08bba37ab56005c4b8dea1979e02a725b53ef31a4aa5937648e8ea499684a42` | `student_public_nsi_terminale_specialite_v1` |
| `rag_nexus_ses_premiere_specialite` | `043794090b1f3738df465254dede793913489acb86cb48d1eaa4987529c98eb7` | `student_public_ses_premiere_specialite_v1` |
| `rag_nexus_ses_terminale_specialite` | `e517c8d2149b97fa4009067ad75abd93b7094fb80bc239c639037ff458d433b4` | `student_public_ses_terminale_specialite_v1` |
| `rag_nexus_svt_premiere_specialite` | `64ddd6ef36019ebe04eb9ed48460f0685b5f0265f734c770113a63c048384f79` | `student_public_svt_premiere_specialite_v1` |
| `rag_nexus_svt_terminale_specialite` | `48cda0bc1997b86ffe410486bbf9c9f2b674da992200493209a101a5eb1d0172` | `student_public_svt_terminale_specialite_v1` |

Statut du paquet : `PREPARATION_ONLY_NOT_ACTIVABLE`, `NOT_TRANSFERRED`,
`candidate/NOT_PROMOTABLE/PRE_REVIEW/NO_PRODUCTION_ACTIVATION`. Aucun PDF
source n'entre dans les artefacts publics ; aucun déploiement staging ou
production n'a eu lieu. Le digest d'inclusion et les preuves d'actualité ne
constituent ni revue de scope exacte, ni autorisation successeur, ni reçu de
transfert de la cible finale. Le schéma `public_successor` demeure bloqué.

Vérifications du lot : 35 tests ciblés verts, dont les tests du constructeur et
du vérificateur ; sabotage de statut PII, fraîcheur périmée, source croisée
avec digest de ligne recalculé, reçu privé manquant, octets CAS altérés,
autorité de droits modifiée, population incomplète et format V1. Le CAS saboté
avec index/report avancés au 12 octobre est rejeté.
Ruff vert sur les quatre fichiers Python modifiés ou créés.
