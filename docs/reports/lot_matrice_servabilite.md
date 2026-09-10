# Matrice de servabilité — NEXUS-SERVABILITY-MATRIX-V1

Une ligne par relation d'artefact, sur toute la population du plan de données.
La matrice ne décide rien : elle est émise `applied=false`. Elle croise les
dimensions déjà mesurées et rend un verdict par cascade, de sorte qu'une seule
dimension bloquante suffise à refuser.

```
SERVABILITY_ROWS_TOTAL=2530
SERVABILITY_ROWS_DISTINCT_CONTENTS=2530
SERVABILITY_UNACCOUNTED=0
MATRIX_SHA256=0258d79604ca23e5f221169889afcc3530cf9ef41cbd595f208d3b0df99f02fb
```

## Verdicts

| Verdict | Nombre |
| --- | ---: |
| `CANDIDATE_NO_BLOCKING_DIMENSION` | 2301 |
| `BLOCKED_PII_HUMAN_REVIEW` | 149 |
| `BLOCKED_NO_URL_PROVENANCE` | 59 |
| `NOT_INDEXABLE_BY_ROLE` | 20 |
| `REFUSED_PROGRAM_INCOMPATIBLE` | 1 |

La somme fait 2530. Aucune ligne n'échappe au compte.

Un contenu « candidat » n'est pas un contenu servable. Il signifie exactement
ceci : aucune des dimensions mesurées ne le bloque aujourd'hui. La servabilité
reste subordonnée aux autorités de gouvernance, dont deux ne sont pas adoptées.

## Une confusion écartée, et pourquoi elle comptait

La population du plan de données compte 2530 relations ; la partition programme
n'en mesure que 2451, celles appariées au catalogue. Une première version de
cette matrice classait les 79 non appariées en `UNKNOWN`, ce qui portait
l'inconnu programme à 2519 au lieu de 2440.

L'erreur était silencieuse : elle produisait une matrice d'apparence cohérente,
dont la somme tombait juste, mais qui contredisait la partition qualifiée sans
le dire. Les 79 ne sont pas d'un programme inconnu ; elles sont **hors de la
population mesurée**, faute d'appariement au catalogue. La distinction est
maintenant portée par la valeur `OUTSIDE_PROGRAM_POPULATION`, et la
réconciliation est vérifiée à chaque construction :

```
MATRIX_UNKNOWN=2440        PARTITION_UNKNOWN=2440
MATRIX_COMPATIBLE=10       PARTITION_COMPATIBLE=10
MATRIX_INCOMPATIBLE=1      PARTITION_INCOMPATIBLE=1
MATRIX_IN_PARTITION_POPULATION=2451   PARTITION_POPULATION=2451
RECONCILES=true
```

Le constructeur **refuse d'écrire** la matrice si cette réconciliation échoue.
Une matrice qui contredit son autorité ne doit pas exister sur disque.

## Dimensions

| Dimension | Répartition |
| --- | --- |
| Provenance | 2451 avec preuve d'URL, 79 sans |
| Programme | 2440 inconnus, 79 hors population, 10 compatibles prouvés, 1 incompatible prouvé |
| Actualité | 2158 à vérifier, 164 actuels déclarés, 84 transition ou actuel, 79 sans statut, 40 archives, 5 mixtes |
| PII | 149 non tranchés, 2381 hors revue |
| Indexabilité | 2510 indexables, 20 non indexables par rôle |

## Ce que la matrice ne dit pas

Elle ne dit pas que 2301 contenus sont servables. Trois autorités manquent :
la politique d'actualité n'a **aucune ADR** qui l'adopte, l'autorité de version
de programme est une proposition, et l'ADR qui nomme la version déclarée comme
autorité n'est pas fusionnée. Tant que ces trois points tiennent, l'actualité
n'est pas un critère de servabilité applicable, et la colonne correspondante de
cette matrice est une mesure, pas un gate.

Elle ne dit pas non plus que les 149 PII sont un défaut : ce sont des décisions
humaines en attente, et aucune automatisation ne peut les rendre.

## Épreuves

Sept épreuves tiennent les propriétés, pas des chiffres figés. Quatre mutations
ont été appliquées au constructeur pour vérifier qu'elles tuent réellement :

| Mutation | Épreuve qui la tue |
| --- | --- |
| Retirer la distinction hors-population | `test_une_relation_hors_catalogue_n_est_pas_un_programme_inconnu` |
| Faire passer la PII après l'indexabilité | `test_une_pii_non_tranchee_bloque_meme_un_contenu_par_ailleurs_propre` |
| Écrire malgré une réconciliation fausse | `test_la_matrice_refuse_de_s_ecrire_si_elle_ne_se_reconcilie_pas` |
| Se rabattre sur une entrée absente | `test_une_entree_absente_est_un_refus_pas_une_reconstruction` |

Chaque mutation rend rouge exactement une épreuve, et la restauration rend le
lot vert. Une épreuve qu'aucune mutation ne fait tomber ne prouve rien.

## Entrées

Toutes versionnées, aucune reconstruite :

```
docs/reports/handoff/url_provenance_reconciliation.json     NEXUS-URL-PROVENANCE-RECONCILIATION-V1
docs/reports/handoff/program_partition_v4.json              NEXUS-PROGRAM-PARTITION-V4
docs/reports/handoff/artifact_program_bindings.json         NEXUS-ARTIFACT-PROGRAM-BINDING-DISCOVERY-V2
docs/reports/evidence-index/pii_review_index_v2_20260907.json
docs/reports/evidence-index/non_pdf_disposition_consolidation_20260907.json
```

Deux de ces entrées ne sont pas encore sur `main` : la partition programme et
les liaisons viennent du lot de gouvernance programme. Le constructeur refuse de
tourner tant qu'une entrée manque, plutôt que de produire une matrice partielle.
