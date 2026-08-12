# Lot multi-niveaux 2026-2027 — inventaire initial

## Périmètre de ce jalon

Ce premier jalon ne porte que sur l'inventaire déterministe du catalogue H2-E
scellé. Il n'exécute encore ni réseau, ni décision de currentness, ni scan PII,
ni ingestion. Les dix collections restent soumises aux gates gouvernés des
jalons suivants.

Autorités lues :

- catalogue scellé SHA-256 :
  `301c0dcce4e49cd9b6e524708bde82b262a09b05bd52e0431233813ecf8ae04b` ;
- manifest corpus SHA-256 :
  `d7e5caa59278b98d6982a8441332c22fed493d2e0dec913c603d400148e4cc1e` ;
- catalogue de placements SHA-256 :
  `095ca37cc4c2126d06b77106f9f1663d4f5ad881ae4952dbf5b951477fd54c39` ;
- descriptor vNext append-only SHA-256 :
  `cc12e73643bcb36102a992982e756356b34a908c60d0d742ea48d2ee61cfd99b` ;
- payload des deux placements ajoutés SHA-256 :
  `5131ba7a72cdc59c0816d89795e6c917d8348d1b5c0beb7b07b2fc216a2276e1` ;
- autorité catalogue effective SHA-256 :
  `5cc8e30b81157fbc1789a0b82ad38cd3673276167890bced55151cbac1523c2f` ;
- inventaire produit SHA-256 :
  `86531933e0779a739f20c347d32dd02e54672f058024d16e1198809cef965300`.

Le descriptor ne contient aucun octet PDF et n'ajoute aucun objet physique. Il
lie deux placements exacts aux objets déjà scellés, sans modifier le catalogue
parent : le programme de Français Première `b88b5c...` et le programme de
Physique-Chimie Terminale `c07f8b...`.

## Comptage exact-grade

| Collection | SHA uniques | Placements | Objets physiques | SHA multi-placement | Disposition inventaire |
|---|---:|---:|---:|---:|---|
| `rag_nexus_maths_seconde_tc` | 6 | 6 | 6 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_francais_seconde_tc` | 8 | 8 | 8 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_maths_quatrieme_tc` | 1 | 1 | 1 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_francais_quatrieme_tc` | 9 | 9 | 9 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_maths_premiere_gen_specialite` | 12 | 12 | 12 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_nsi_premiere_specialite` | 10 | 10 | 10 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_francais_premiere_tc` | 84 | 85 | 84 | 1 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_maths_terminale_gen_specialite` | 8 | 8 | 8 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_nsi_terminale_specialite` | 11 | 11 | 11 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_pc_terminale_specialite` | 1 | 1 | 1 | 0 | `EXACT_GRADE_GATES_PENDING` |

Totaux dédupliqués : 150 SHA, 151 placements, 150 objets physiques et un
SHA multi-placement. La partition des dix collections ne contient aucun
`unevaluated` : les dix collections attendent leurs gates exact-grade.

## Six voies de découverte

Les valeurs ci-dessous comptent les SHA uniques trouvés par voie ; la dernière
colonne compte les sources officielles configurées.

| Collection | Placements exacts | Chemins physiques | Multi-niveaux | Non-classe | Matière + programme | Sources configurées |
|---|---:|---:|---:|---:|---:|---:|
| Maths Seconde | 6 | 6 | 51 | 18 | 38 | 1 |
| Français Seconde | 8 | 7 | 1 | 126 | 84 | 1 |
| Maths Quatrième | 1 | 1 | 0 | 0 | 38 | 0 |
| Français Quatrième | 9 | 9 | 0 | 0 | 84 | 0 |
| Maths Première spécialité | 12 | 12 | 51 | 18 | 38 | 1 |
| NSI Première spécialité | 10 | 10 | 0 | 28 | 6 | 1 |
| Français Première TC | 84 | 71 | 1 | 126 | 84 | 1 |
| Maths Terminale spécialité | 8 | 8 | 51 | 18 | 38 | 1 |
| NSI Terminale spécialité | 11 | 11 | 0 | 28 | 6 | 1 |
| Physique-Chimie Terminale spécialité | 1 | 0 | 132 | 0 | 71 | 1 |

L'inventaire JSON conserve, pour chaque voie, les placements ou chemins exacts
et les valeurs observées de niveau, matière, scope, type documentaire, statut
pédagogique et chemin physique. Aucun hit de découverte non exact-grade n'est
promu automatiquement en candidat.

## Reproductibilité

Deux exécutions indépendantes du sous-commande `inventory` sur le même
catalogue et le même descriptor vNext ont produit des octets identiques (`cmp`
exit 0). La sérialisation ne contient aucun horodatage et termine par un saut
de ligne.

## Currentness artifact-bound

La preuve `MULTILEVEL_ARTIFACT_CURRENTNESS_V1` est liée à l'inventaire
SHA-256
`86531933e0779a739f20c347d32dd02e54672f058024d16e1198809cef965300`.
Elle réutilise sans nouveau téléchargement l'audit réseau officiel SHA-256
`198e23717618f58d3ab146fbc1bd9df0c90c284c42be25049a49efa1cb02e231`.
La preuve produite a pour SHA-256
`2ad7209f28cd7cbf9f1ea91724b687983579c36c91619e8d107d28b72b849122`.

La partition est complète : 150 SHA évalués, 12 `CURRENT`, 138
`REVIEW_REQUIRED` et aucun `unevaluated`. Les douze décisions positives
portent une URL de listing officielle, une URL de télìhargement officielle,
une identité d'octets exacte et l'année scolaire `2026-2027`. Les autres SHA
restent fermés avec au minimum
`CURRENT_SOURCE_BYTE_IDENTITY_NOT_AUDITED`; les cas de programme et les
chemins physiques HLP portent en plus un reason code d'alignement. Aucun
statut physique du catalogue n'est promu en `CURRENT`.

| Collection | Évalués | Current | Review required |
|---|---:|---:|---:|
| `rag_nexus_maths_seconde_tc` | 6 | 1 | 5 |
| `rag_nexus_francais_seconde_tc` | 8 | 2 | 6 |
| `rag_nexus_maths_quatrieme_tc` | 1 | 1 | 0 |
| `rag_nexus_francais_quatrieme_tc` | 9 | 1 | 8 |
| `rag_nexus_maths_premiere_gen_specialite` | 12 | 1 | 11 |
| `rag_nexus_nsi_premiere_specialite` | 10 | 2 | 8 |
| `rag_nexus_francais_premiere_tc` | 84 | 1 | 83 |
| `rag_nexus_maths_terminale_gen_specialite` | 8 | 1 | 7 |
| `rag_nexus_nsi_terminale_specialite` | 11 | 1 | 10 |
| `rag_nexus_pc_terminale_specialite` | 1 | 1 | 0 |

## Gates restant à exécuter

Droits, PII v5, extraction, chunking E5, conformité de placement et release
eligibility ne sont pas encore évalués dans ce jalon.
