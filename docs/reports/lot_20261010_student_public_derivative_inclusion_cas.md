# Lot — rejeu complet du CAS privé étudiant

Date UTC : 2026-10-10. Base de développement : `56d5d672ddb7a34dd031d521ed17c12018c9824c`.

Le vérificateur reconstruit chaque reçu de listing depuis le HTML normalisé, le texte extrait et la capture conservés dans le CAS. Il recalcule les ancres PDF, refuse une URL demandée ou finale non officielle et compare intégralement le reçu reconstruit. Les scripts de capture, contrôle de source, adjudication PII et attestation d’actualité sont eux-mêmes archivés, vérifiés par leurs SHA déclarés et comparés aux octets du dépôt courant.

Le CAS privé V4 contient 1 821 fichiers (193 785 824 octets), dont 253 textes dérivés, 253 PDF sources privés, 253 reçus de dérivation, 253 preuves de source #300, 253 anciens et 253 nouveaux checkpoints, 253 reçus GET, neuf reçus de listings, leurs 27 corps et quatre scripts. Index CAS SHA-256 : `757f41e4aabceaed603196294b3a980c7ecd5d228de8a48b6fc0e3c60fc06d36`. Ce paquet reste hors dépôt et n’atteste aucun transfert vers la cible d’ingestion.

Autorité de droits Éduscol–Etalab `013527a0819e548f9962f04676aee5c02707c717b01296a6f61d59f30d8b0ec1` ; PII `7bf534b50a7eef90ca34d52daa22293a835273b0b2abf556d48e976721d05dd0` ; actualité/révocation `4882c95b47e807f0efe55ee5768637b47907af4d5f91e331a0e273acf684e62d`. Le dépistage par motifs seul ne constitue pas une autorité d’inclusion.

Le rejeu des 253 chaînes de preuve à `2026-10-10T14:30:00Z` produit 253 `INCLUDE`, zéro `PENDING`. Inclusion SHA-256 : `76e54dd68025a730fb5c94cc2db9c7091d402d15a02f11c0e0e5ab1524f605ef`. Les reçus individuels, dont les listings et GET, expirent au plus tard le `2026-10-11T13:39:22.520000Z` : un rejeu frais sera requis avant toute promotion.

Paquet préparatoire immuable : `student-public-successor-20261010-b1dda0c8503aa474`, manifeste `abb563fbd2623bc8dc3c73597a68c313fa9dc0291bcc335b7d18ec06e133bd44`, index `34bbf66ef8f2196ad66a84a4bee6bdf43ec232cd6bddcc29c146b97cf536f9e9`. Comptes calculés : 11 collections, 253 artefacts textuels, 377 placements, 3 975 chunks. Registres droits `9129a6b1dabebb929506f3b44b989ee5ae3edcb9d5846d691a68ba680827ca89`, actualité `579c6c016586db820ae4e0708fbb62ae0db52ccd64d5d6fedef4eb43ed83c570`, PII `5558cfae648107d201f3f2e27c3d0f8952b7c987b6e40f63227c1d61e5b62f6e`. Ces registres ne valent ni revue finale ni autorisation de publication.

| Collection | SHA-256 du sujet préparatoire | Scope proposé |
| --- | --- | --- |
| `rag_nexus_dgemc_terminale_option` | `cfbd15f182361e807c2a5e8a52e18429f1d060909cda8cd8b450a96b0034cb56` | `student_public_dgemc_terminale_option_v1` |
| `rag_nexus_hggsp_premiere_specialite` | `fe36cf99b4e7b14d8f3fc93f21a426ab42d3abf6bae915589cb3fd84d079a785` | `student_public_hggsp_premiere_specialite_v1` |
| `rag_nexus_hggsp_terminale_specialite` | `788d427177b5981b383004ddf7549e85b21c0630f5468efc9a7abf5319c98b7e` | `student_public_hggsp_terminale_specialite_v1` |
| `rag_nexus_hlp_premiere_specialite` | `8bf0ef408ab89ee9de3212e6bfa779ac758d0c914cd2167553c1c7f22e1cd4a0` | `student_public_hlp_premiere_specialite_v1` |
| `rag_nexus_hlp_terminale_specialite` | `1ddacadca208ac72bfd1e9fd72c135fe0257993d09674be923ab12d4eb7fc9f3` | `student_public_hlp_terminale_specialite_v1` |
| `rag_nexus_nsi_premiere_specialite` | `8cc97816bc5f35e1da7141fbb93f0c5b91094576ba6398762e139a47fe84e3cd` | `student_public_nsi_premiere_specialite_v1` |
| `rag_nexus_nsi_terminale_specialite` | `eba537eaba448409d12665bdcf07f9881c7cd8a32463e78903c87ae5f60d20b3` | `student_public_nsi_terminale_specialite_v1` |
| `rag_nexus_ses_premiere_specialite` | `9c576ef9263cc51f83aabe3884c3cc4eabf526a2e598047a96b6528f5730938d` | `student_public_ses_premiere_specialite_v1` |
| `rag_nexus_ses_terminale_specialite` | `d227b4362e67332a94ea126b97d13d986549d924c714a8c3e8181b8ec5eda3df` | `student_public_ses_terminale_specialite_v1` |
| `rag_nexus_svt_premiere_specialite` | `d8d7c6a4b12fce18a65ebddf7331d0c0bb08bd9ed2309213626ff1b002b69364` | `student_public_svt_premiere_specialite_v1` |
| `rag_nexus_svt_terminale_specialite` | `a1821937b985f35fd86e9414658fc3fd8003767a1bc0f12c25489a9d6d8c3f69` | `student_public_svt_terminale_specialite_v1` |

Statut : `PREPARATION_ONLY_NOT_ACTIVABLE`, `NOT_TRANSFERRED`, `candidate/NOT_PROMOTABLE/PRE_REVIEW/NO_PRODUCTION_ACTIVATION`. Aucun PDF n’est un artefact public. Restent nécessaires : revue exacte des scopes, preuves fraîches à la promotion, reçu de transfert privé et autorisation/revue successeur. Aucun staging ou production modifié.

Vérification : 37 tests ciblés verts ; tests ciblés du vérificateur et du constructeur, sabotage des ancres PDF, URL demandée/finale non officielle, SHA du script de capture et des trois autres scripts, plus les sabotages historiques (PII, fraîcheur, source croisée, octets CAS, population). Rejeu réel des 253 preuves et construction du paquet préparatoire.
