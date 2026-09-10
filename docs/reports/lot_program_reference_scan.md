# Références réglementaires explicites — le corpus se nomme lui-même

## 1. Comptes de preuve, séparés des comptes d'objets

Une corroboration n'est pas un artefact lié de plus.

```
PROGRAM_BINDING_EVIDENCE_OCCURRENCES=644
PROGRAM_BINDING_EVIDENCE_ACCEPTED=20
PROGRAM_BINDING_EVIDENCE_REJECTED=624
PROGRAM_BINDING_EVIDENCE_UNACCOUNTED=0        (624 + 20 = 644)

UNIQUE_ARTIFACT_PROGRAM_BINDINGS=10           (avant ce lot)
BINDINGS_WITH_SINGLE_EVIDENCE=0
BINDINGS_WITH_MULTIPLE_EVIDENCE=10
```

Les dix liaisons initiales sont chacune **doublement** corroborée.

## 2. Textes officiels dans le périmètre

```
CATALOGUE_PROGRAM_TYPED_CONTENTS=645          (programme-officiel + programme-limitatif)
```

Ce sont des **candidats** pour `CurrentProgramAuthorityV1`. Leur
`programme_version` reste inconnue : elle ne se dérive pas du nom du fichier.
Le titre découvre le candidat ; le contenu établit l'autorité.

## 3. `NEXUS-OFFICIAL-PROGRAM-REFERENCE-PARSER-V1`

Une citation réglementaire explicite — « Bulletin officiel spécial n° 1 du
22 janvier 2019 » — n'est pas une inférence sémantique : le document **nomme**
le texte qu'il met en œuvre. C'est une preuve.

Formes reconnues : `bulletin officiel` / `BO` / `B.O.` / `BOEN`, avec ou sans
`spécial`, numéro, et date en toutes lettres ou numérique.

Formes refusées, éprouvées : `2026-2027`, `2026`, `EDUSCOL_CORPUS_20260808`,
`BOEN_`, `BOEN_special_1` (sans date), « voir le bulletin officiel » (sans
numéro ni date), « BO spécial du 25 juillet 2019 » (sans numéro), une date
impossible (`45-13-2019`).

**39 épreuves.** Le parseur est versionné : deux corpus analysés sous des
parseurs différents ne sont pas comparables.

### L'ambiguïté est réelle, et refusée

`BOEN_14_2026-04-02` est un préfixe de **deux** entrées de l'autorité
(`_MENE2602914A` et `_MENE2602917A`). Choisir la plus courte ou la première
ferait décider au parseur ce qui relève de l'autorité — une citation qui
désigne deux textes n'en désigne aucun. Verdict : `AMBIGUOUS`.

## 4. Rejeu sur les textes canoniques

Le texte lu est celui que le run V2 a produit — celui qui a alimenté le scanner
PII et le découpage. Aucune ré-extraction : lire autre chose ferait porter la
preuve sur un texte que rien n'a validé.

```
CANONICAL_TEXT_ARTIFACTS_SCANNED=2464
   dont cleared (chunks V2)      2315
   dont detected (entrée canonique) 149
NOT_ASSESSABLE_EXCLUDED=9

ARTIFACTS_WITH_EXPLICIT_PROGRAM_REFERENCE=232
EXPLICIT_REFERENCES_TOTAL=312

REFERENCES_RESOLVED=99      REFERENCES_AMBIGUOUS=0
REFERENCES_UNKNOWN=213      REFERENCES_INVALID=0
REFERENCE_SCAN_UNACCOUNTED=0
```

Les 9 non évaluables sont exclus : leur texte canonique est incomplet, et une
absence de citation y serait un artefact de la page que personne n'a lue.

Aucun contexte brut ne sort : la preuve est
`(content_sha256, référence normalisée, autorité résolue, empreinte)` — jamais
le paragraphe d'origine.

## 5. Nouvelle partition

```
NEW_UNIQUE_ARTIFACT_PROGRAM_BINDINGS=66
UNIQUE_ARTIFACT_PROGRAM_BINDINGS=76           (10 manifestes + 66 citations)

PROGRAM_COMPATIBILITY_PROVEN=76
PROGRAM_INCOMPATIBILITY_PROVEN=0
PROGRAM_COMPATIBILITY_UNKNOWN=2375
                                              somme = 2451

PROGRAM_PARTITION_INTERSECTION_COUNT=0
PROGRAM_PARTITION_UNACCOUNTED=0

PROGRAM_COMPATIBLE_SHA_SET_SHA256=f30c9196e7e353552dc960fb2b6a98df4ee8a581f2b9b950efa909ff78997dee
PROGRAM_UNKNOWN_SHA_SET_SHA256=c0a47c31ad63175b9d8e951524a6c997384778051ce63399420afe5dbbec7ab5
```

Le résidu passe de **2441 à 2375**. La citation explicite est la source la plus
productive rencontrée jusqu'ici : 66 liaisons contre 10 pour toutes les
autorités structurées réunies.

## 6. Pourquoi `INCOMPATIBILITY_PROVEN` reste à zéro

172 documents citent une référence **valide** hors de l'autorité déclarée —
`BOEN_special_11_2015-11-26`, `BOEN_31_2020-07-30`… Il serait tentant d'en
conclure qu'ils servent un programme périmé.

Ce serait faux. L'autorité courante ne couvre que **18 scopes** sur les 34
matières du catalogue : pour les autres, on ignore quel programme est en
vigueur. Un document citant un BO de 2015 peut parfaitement mettre en œuvre le
programme encore applicable à sa discipline.

`UNKNOWN` n'est pas `INCOMPATIBLE`. Déclarer l'incompatibilité exigerait de
connaître le programme courant **de son scope** — et de constater qu'il en
sert un autre.

## 7. Seize conflits, non arbitrés

```
PROGRAM_BINDING_CONFLICTS=16
```

Ces documents citent **deux** programmes résolus, typiquement
`BOEN_special_1_2019-01-22` (première) et `BOEN_special_8_2019-07-25`
(terminale) — plausiblement des ressources couvrant les deux années d'un cycle.

Aucun n'est arbitré : ils restent en `UNKNOWN`, avec leur ensemble de
références conservé. En choisir un ferait décider ici ce qui relève de
l'autorité.

## 8. Ce qui reste

Le levier suivant est l'**extension de `CurrentProgramAuthorityV1`** au-delà de
18 scopes. Elle transformerait une partie des 172 citations « hors autorité »
en verdicts réels — compatibles ou incompatibles — sans toucher au parseur.

Rien n'est appliqué : `CURRENTNESS_POLICY_APPLIED=false`,
`ARTIFACT_PROGRAM_BINDING_APPLIED=false`.
