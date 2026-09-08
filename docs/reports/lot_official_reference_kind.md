# Nature du texte officiel — et le retrait des 66 liaisons

## 1. Le défaut : `BOEN_*` traité comme synonyme de « programme »

Le BO spécial n° 2 du 13 février 2020 porte les **modalités d'épreuves** du
baccalauréat 2021 — spécialités artistiques, philosophie, Grand oral.
**Dix-sept** documents le citent. En déduire leur version de programme ferait
dériver une autorité pédagogique d'un règlement d'examen.

Enum fermée, sept natures. Seules `PROGRAM` et `PROGRAM_MODIFICATION` peuvent
alimenter une autorité ou une liaison.

```
EXPLICIT_REFERENCES_TOTAL=312

REFERENCE_KIND_PROGRAM=128
REFERENCE_KIND_PROGRAM_MODIFICATION=14
REFERENCE_KIND_EXAM_REGULATION=17
REFERENCE_KIND_ASSESSMENT_REGULATION=0
REFERENCE_KIND_CURRICULUM_GUIDANCE=0
REFERENCE_KIND_OTHER_OFFICIAL_TEXT=0
REFERENCE_KIND_UNKNOWN_OFFICIAL_KIND=153
REFERENCE_KIND_UNACCOUNTED=0
```

## 2. `special` fait partie de l'identité

Le 26 novembre 2015 ont paru **un BO spécial n° 11 et un BO hebdomadaire
n° 44**. Perdre le qualificatif fait désigner deux textes différents par le même
identifiant.

Le parseur rend désormais une structure — `bulletin_series`,
`bulletin_number`, `bulletin_date` — et non une chaîne où `special` serait un
détail perdable au premier refactor.

`BOEN_11_2015-11-26` reste tel quel :
`resolution_status=POSSIBLE_MISSING_SPECIAL_QUALIFIER`, `auto_alias=false`.
Corriger silencieusement un texte officiel cité par une source, ce serait
réécrire sa citation.

## 3. Le contrôle de scope, et ce qu'il révèle

Pipeline désormais : `parse → résoudre le texte → classer sa nature →
résoudre son scope → comparer au placement → seulement alors, lier.`

Sur les 142 références de nature liante :

```
PROGRAM_REFERENCES_SCOPE_MATCH=0
PROGRAM_REFERENCES_SCOPE_MISMATCH=22        (16 matière, 6 niveau)
PROGRAM_REFERENCES_SCOPE_UNKNOWN=120        (77 non attribuables, 43 scope inconnu)
```

**Zéro.** Pas une seule référence de programme résolue ne couvre le placement du
document qui la cite.

Un exemple qui le rend concret : un document
`transversal_multi_niveaux / arts_plastiques` cite le BO spécial n° 1 du
22 janvier 2019, dont le scope gouverné est `(première, français)`,
`(première, HLP)`, `(première, NSI)`… Les arts plastiques n'y figurent pas.

J'ai d'abord classé les 77 placements transversaux en `MISMATCH`. C'était trop
grossier : un placement transversal ne **contredit** pas la référence, il ne
permet pas de l'**attribuer**. Ils sont désormais `SCOPE_NOT_ATTRIBUTABLE`.

## 4. Les 66 liaisons sont retirées

```
PRE_KIND_BINDINGS=76
POST_KIND_VALID_BINDINGS=10
POST_KIND_REJECTED_BINDINGS=124
POST_KIND_AMBIGUOUS_BINDINGS=0

motifs : SCOPE_NOT_ATTRIBUTABLE=65  SCOPE_UNKNOWN=43
         SCOPE_MISMATCH_SUBJECT=14  SCOPE_MISMATCH_LEVEL=2
```

Mes 66 liaisons reposaient sur « le document cite une référence résolue ». Il
manquait le contrôle que le scope de cette référence couvre le document. Le
document cite bien le texte — souvent parce qu'il s'y réfère, le commente ou
l'accompagne — mais citer un programme n'est pas relever de ce programme.

**C'est une correction de preuve, pas une régression.** Les 66 n'étaient pas des
liaisons prouvées ; elles étaient des citations non attribuées.

Seules survivent les **10** liaisons portées par un manifeste gouverné, où le
scope est déclaré par l'autorité elle-même.

## 5. Partition corrigée

```
PROGRAM_COMPATIBILITY_PROVEN=10
PROGRAM_INCOMPATIBILITY_PROVEN=0
PROGRAM_COMPATIBILITY_UNKNOWN=2441
PROGRAM_PARTITION_UNACCOUNTED=0

PROGRAM_COMPATIBLE_SHA_SET_SHA256=2caa5baf09142b8438fe29eb2791afb9e8090dbb921797cd009b65d91330bdf6
PROGRAM_UNKNOWN_SHA_SET_SHA256=723454413764d0d9d870601e3b93fbb5335cb76013af2a9097db99b44f17a714
```

## 6. Ce que cela dit du levier

Le blocage n'est pas la découverte de citations — le corpus en porte 312. C'est
que **l'autorité courante ne couvre que 18 scopes** : ni les arts plastiques, ni
la danse, ni la musique, ni le théâtre, ni le cinéma, ni l'histoire des arts, ni
les LCA, ni les langues vivantes, ni l'EPS, ni le collège au-delà de la
quatrième.

`SCOPE_UNKNOWN=43` mesure directement ce manque : 43 références liantes dont on
ignore le scope faute d'autorité déclarée.

Étendre `CurrentProgramAuthorityV1` reste le seul levier — et il agit
maintenant sur deux fronts à la fois : il résout des références inconnues **et**
il rend attribuables des citations déjà trouvées.

## 7. Rien n'est appliqué

```
PROGRAM_HUMAN_REVIEW_STARTED=false
CURRENTNESS_POLICY_APPLIED=false
ARTIFACT_PROGRAM_BINDING_APPLIED=false
```
