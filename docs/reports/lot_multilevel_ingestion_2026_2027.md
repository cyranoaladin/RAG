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
- inventaire produit SHA-256 :
  `4b73de9bd1a83aa7c6713ecf2c3aa7e8eb45bd82f4ac813ce091c860dbbd9479`.

## Comptage exact-grade

| Collection | SHA uniques | Placements | Objets physiques | SHA multi-placement | Disposition inventaire |
|---|---:|---:|---:|---:|---|
| `rag_nexus_maths_seconde_tc` | 6 | 6 | 6 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_francais_seconde_tc` | 8 | 8 | 8 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_maths_quatrieme_tc` | 1 | 1 | 1 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_francais_quatrieme_tc` | 9 | 9 | 9 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_maths_premiere_gen_specialite` | 12 | 12 | 12 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_nsi_premiere_specialite` | 10 | 10 | 10 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_francais_premiere_tc` | 83 | 84 | 83 | 1 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_maths_terminale_gen_specialite` | 8 | 8 | 8 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_nsi_terminale_specialite` | 11 | 11 | 11 | 0 | `EXACT_GRADE_GATES_PENDING` |
| `rag_nexus_pc_terminale_specialite` | 0 | 0 | 0 | 0 | `PLACEMENT_PROOF_OR_CORPUS_DELTA_REQUIRED` |

Totaux dédupliqués : 148 SHA, 149 placements, 148 objets physiques et un
SHA multi-placement. La partition des dix collections ne contient aucun
`unevaluated` : neuf collections attendent leurs gates exact-grade et la
Physique-Chimie Terminale exige une preuve de placement ou un delta corpus.

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
| Français Première TC | 83 | 71 | 1 | 126 | 84 | 1 |
| Maths Terminale spécialité | 8 | 8 | 51 | 18 | 38 | 1 |
| NSI Terminale spécialité | 11 | 11 | 0 | 28 | 6 | 1 |
| Physique-Chimie Terminale spécialité | 0 | 0 | 132 | 0 | 71 | 1 |

L'inventaire JSON conserve, pour chaque voie, les placements ou chemins exacts
et les valeurs observées de niveau, matière, scope, type documentaire, statut
pédagogique et chemin physique. Aucun hit de découverte non exact-grade n'est
promu automatiquement en candidat.

## Reproductibilité

Deux exécutions indépendantes du sous-commande `inventory` sur le même
catalogue ont produit des octets identiques (`cmp` exit 0). La sérialisation ne
contient aucun horodatage et termine par un saut de ligne.

## Gates restant à exécuter

Currentness artifact-bound, droits, PII v5, extraction, chunking E5,
conformité de placement et release eligibility ne sont pas encore évalués
dans ce jalon d'inventaire.
