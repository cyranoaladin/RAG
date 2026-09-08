# Dénominateurs fermés, 16 réexaminés, et le levier chiffré

## 1. Le périmètre du scan n'est pas celui de la population

Deux périmètres différents étaient additionnés. Relevés par **ensembles**,
jamais par soustraction :

```
PROGRAM_POPULATION_TOTAL=2451
PROGRAM_POPULATION_SCANNED=2444
PROGRAM_POPULATION_NOT_ASSESSABLE=7
PROGRAM_POPULATION_WITHOUT_CANONICAL_TEXT=0
                                     2444 + 7 + 0 = 2451
intersections=0            PROGRAM_SCAN_UNACCOUNTED=0

CANONICAL_TEXT_ARTIFACTS_SCANNED=2464
NON_PROGRAM_PDF_SCANNED=20           (2444 + 20 = 2464)
PROGRAM_POPULATION_SHA_SET_SHA256=baa2a8501ccbf94b0d46cbe5cc4b843c44fabeb95b91543980fb14b81f9c030a
```

Un détail que la mesure révèle : **7** des 9 non évaluables appartiennent à la
population du catalogue ; les 2 autres n'y sont pas. `2464 − 9` aurait donné 2455
et n'aurait rien voulu dire.

## 2. Les 66 nouvelles liaisons sont dans le bon périmètre

```
OLD_BINDINGS=10      NEW_BINDINGS_FROM_EXPLICIT_SOURCE_REFERENCE=66      TOTAL=76
OLD ∩ NEW = ∅
NEW ⊆ PROGRAM_POPULATION          NEW_BINDINGS_OUTSIDE_PROGRAM_POPULATION=0
TOTAL ⊆ PROGRAM_POPULATION
```

## 3. Les 99 occurrences résolues, projetées

```
RESOLVED_REFERENCE_OCCURRENCES=99
ARTIFACTS_WITH_RESOLVED_REFERENCES=83
ARTIFACTS_WITH_ONE_RESOLVED_PROGRAM=67
ARTIFACTS_WITH_MULTIPLE_RESOLVED_PROGRAMS=16

RESOLVED_REFERENCES_CORROBORATING_EXISTING_BINDINGS=1
RESOLVED_REFERENCES_CREATING_NEW_BINDINGS=66
RESOLVED_REFERENCES_ON_MULTI_PROGRAM_ARTIFACTS=32
                                     1 + 66 + 32 = 99
RESOLVED_REFERENCE_UNACCOUNTED=0
```

83 artefacts pour 99 occurrences : occurrences et artefacts ne se confondent pas.

## 4. Les 16 réexaminés par placement — et un critère que j'ai dû corriger

```
MULTI_PROGRAM_ARTIFACTS=16
MULTI_SCOPE_PROGRAM_BINDINGS=4
PROGRAM_BINDING_CONFLICTS=0
PROGRAM_BINDING_AMBIGUOUS=12
                                     sum = 16
```

**Aucun conflit réel.**

Mon premier critère classait par *matière* et rendait 4 conflits. Il ne mesurait
rien : chaque BO couvre déjà sept matières, donc l'union de deux références est
**toujours** multi-matières. L'axe pertinent est le **niveau** — un conflit est
deux programmes pour le même couple `(niveau, matière)`.

Les 4 multi-scope sont des ressources de français citant les programmes de
seconde **et** de première. Les 12 ambigus portent des matières que l'autorité
courante ne déclare pas du tout : arts plastiques, danse, musique, LSF, théâtre,
LLCER, multi-disciplines.

Les 4 multi-scope **restent en `UNKNOWN`** : leur placement déclaré
(terminale/français) n'est pas parmi les scopes que leurs références couvrent.
Les faire sortir de `UNKNOWN` demanderait de prouver le verdict de chacun de
leurs placements.

## 5. Les 645 sont des candidats, pas des autorités

```
DRIVE_PROGRAM_DOCUMENT_CANDIDATES=645
DRIVE_PROGRAM_DOCUMENTS_EXAMINED=645
DRIVE_PROGRAM_AUTHORITIES_VERIFIED=58
DRIVE_PROGRAM_CANDIDATES_REJECTED=0
DRIVE_PROGRAM_CANDIDATES_PENDING=489
candidats cités sans référence résolue=98
```

Un document dont le type porte « programme » n'est pas une autorité programme.

## 6. Le levier, chiffré

```
REFERENCES_UNKNOWN_OCCURRENCES=213
DISTINCT_UNKNOWN_REFERENCES=80
```

| artefacts | occ. | référence | matières dominantes |
|---:|---:|---|---|
| 29 | 29 | `BOEN_special_11_2015-11-26` | éducation musicale, technologie |
| 18 | 18 | `BOEN_11_2015-11-26` | histoire-géographie |
| 17 | 17 | `BOEN_special_2_2020-02-13` | danse, français, arts du cirque |
| 14 | 14 | `BOEN_31_2020-07-30` | langues vivantes, DGEMC, EPS |
| 8 | 8 | `BOEN_special_6_2020-07-31` | LLCER, français |
| 6 | 6 | `BOEN_31_2019-08-29` | danse, physique-chimie |

**Deux autorités officielles ajoutées résoudraient 47 artefacts.** C'est là que
l'effort rapporte — pas dans 213 inspections.

## 7. `effective_from_school_year` est obligatoire

Le cas réel : le BO n° 14 du 2 avril 2026 porte **deux** programmes de
mathématiques — Première applicable en 2026-2027, Terminale en 2027-2028. Au
7 septembre 2026, la Première suit le nouveau texte pendant que la Terminale
suit encore le précédent.

Un moteur qui choisit « le BO le plus récent » attribue le nouveau programme aux
deux, et déclare incompatible tout document de Terminale pourtant conforme au
programme en vigueur.

**Six épreuves** scellent ce cas, dont une qui exécute la règle naïve et exige
qu'elle **diverge** du résultat correct. Le resolver rend `EXACTLY_ONE`, `NONE`
ou `MULTIPLE` — et `MULTIPLE` est un refus de gouvernance, jamais un arbitrage
par date.

`CurrentProgramAuthorityV1` porte désormais 18 champs : NOR, numéro et date de
bulletin, date d'arrêté, période d'effet, et les deux relations de supersession.

## 8. Partition inchangée

```
PROGRAM_COMPATIBILITY_PROVEN=76
PROGRAM_INCOMPATIBILITY_PROVEN=0
PROGRAM_COMPATIBILITY_UNKNOWN=2375
PROGRAM_PARTITION_UNACCOUNTED=0
```

`INCOMPATIBILITY_PROVEN` reste à zéro : aucune chaîne de supersession n'est
établie, et sans elle une référence ancienne ne prouve rien.
