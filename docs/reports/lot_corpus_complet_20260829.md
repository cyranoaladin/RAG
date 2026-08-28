# Corpus complet — placements résolus, profils générés, ingestion non atteinte

*29 août 2026, rapport de fin de lot.*

## Placements — rien d'exclu, rien de faussement précis

| | Documents |
|---|---|
| **Placés** | **2 400** |
| Hors périmètre assumé (ST2S, STL, STI2D, STD2A, S2TMD, STHR) | 51 |
| **COVERAGE_GAP** | **0** |
| Total | 2 451 |

### Par granularité

| Granularité | Documents |
|---|---|
| `cycle` | **912** |
| `niveau_exact` | **730** |
| `transversal_discipline` | 473 |
| `transversal_lycee` | 285 |

### Par autorité

| Autorité | Documents |
|---|---|
| **P0 — bandeau éditeur** | **994** |
| catalogue élargi | 945 |
| discipline seule | 461 |

**133 documents voient leur niveau corrigé par l'éditeur**, extrait à l'appui —
y compris dans l'ensemble que nous allions ingérer, qui portait donc lui-même des
niveaux faux.

La règle a tenu sans exception : on n'élargit jamais vers le faux, on n'affine
jamais sans preuve.

## Profils — 120 collections, valides au contrat

| | |
|---|---|
| Collections candidates | 130 |
| **Profils valides `CollectionProfile`** | **120** |
| Refusés | **0** |
| Retirés en COVERAGE_GAP (`cycle3`) | 10 |

Les 10 profils `cycle3` sont retirés : `cycle3` n'appartient pas à l'enum `Niveau`
et le corpus n'en porte aucun contenu. **Aucune collection n'est fabriquée pour
combler un vide.**

Deux défauts de ma génération, corrigés : `statut_enseignement` n'appartient pas à
`ResourceScope` — je l'y avais ajouté — et `cycle3` n'est pas une valeur du
contrat.

### `expected_topics` — nommé pour ce qu'il est

Le champ contient **les intitulés que l'éditeur a donnés aux documents que la
collection contient**. Ce ne sont **pas** « les thèmes du programme », et nous ne
le prétendons pas.

Ils sont vrais, cités document par document, et ils remplissent la fonction du
champ : rejeter un document hors sujet. Un champ dont on nomme précisément le
contenu ne ment pas, même si son nom est plus ambitieux que lui.

**Dette ouverte** : renommer le champ, ou y porter les vrais thèmes de programme
quand l'extraction par structure éditoriale sera faite.

## Ce qui reste avant l'ingestion

Le verrou du producteur est corrigé (`!= manifest.declared_count`) et le registre
charge les 120 profils. Restent trois travaux, tous identifiés :

1. **Le manifeste de profils** doit déclarer 120 — l'invariant l'exige.
2. **La matrice de preuve** doit être partitionnée pour 2 400 documents. Mécanique,
   dérivable des placements résolus.
3. **`_source_records` doit lire `catalogue-par-scope`** comme quatrième autorité
   de fait de source. L'ADR l'autorise, l'autorité est scellée
   (`ec5ccbf7a30fec01…`), le raccordement n'est pas écrit.

**L'ingestion n'a pas eu lieu.** Je n'ai donc ni documents ingérés, ni chunks, ni
durée, ni latence post-ingestion, ni point de rupture sur corpus élargi.

## Dettes ouvertes par ce lot

| # | Dette |
|---|---|
| 30 | Extraction des thèmes de programme par **structure éditoriale** — le balayage linéaire plafonné retient le préambule, pas les entrées |
| 31 | Renommer `expected_topics`, ou y porter les vrais thèmes |
| 32 | Acquisition Éduscol bloquée en **403**, hors filtrage `User-Agent` |
| 33 | Le champ `level` du catalogue est faux sur **72,3 %** des documents où l'éditeur s'est prononcé — corriger la source amont |
