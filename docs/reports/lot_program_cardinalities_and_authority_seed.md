# Cardinalités fermées, autorité étendue — et le blocage se déplace

## 1. Chaque nombre avec son unité

Trois dénominateurs étaient mélangés. Séparés :

```
BINDING_CAPABLE_REFERENCE_OCCURRENCES=142
SCOPE_MATCH_REFERENCE_OCCURRENCES=0
SCOPE_MISMATCH_REFERENCE_OCCURRENCES=22
SCOPE_UNKNOWN_REFERENCE_OCCURRENCES=120
                                        0 + 22 + 120 = 142

BINDING_CAPABLE_DISTINCT_REFERENCES=4
SCOPE_MATCH_DISTINCT_REFERENCES=0
SCOPE_MISMATCH_DISTINCT_REFERENCES=2
SCOPE_UNKNOWN_DISTINCT_REFERENCES=4
SCOPE_UNKNOWN_DISTINCT_REFERENCES_SHA256=3d72affb23bc5a2dd443d0fcc94a9c82010ea9385ae6ec270873eb8eb9c4af10
```

Les ensembles de références distinctes **se chevauchent** — union 4,
intersections 2 : une même référence est attribuable pour un artefact et pas
pour un autre. Ils ne somment donc pas, et c'est correct.

**Mon texte précédent écrivait « SCOPE_UNKNOWN=43 » sans unité.** C'était un
compte d'occurrences dans une répartition intermédiaire ; le compte de
références distinctes est **4**. Vous aviez raison d'exiger l'unité : le même
symbole désignait deux choses.

## 2. Le 124 rattaché à son vrai dénominateur

```
PRE_KIND_UNIQUE_ARTIFACT_BINDINGS=76
POST_KIND_VALID_UNIQUE_ARTIFACT_BINDINGS=10
POST_KIND_REJECTED_UNIQUE_ARTIFACT_BINDINGS=66
POST_KIND_AMBIGUOUS_UNIQUE_ARTIFACT_BINDINGS=0
POST_KIND_ARTIFACT_BINDING_UNACCOUNTED=0
                                        10 + 66 + 0 = 76
```

Et séparément :

```
POST_KIND_REJECTED_REFERENCE_OCCURRENCES=142
POST_KIND_REJECTED_DISTINCT_REFERENCES=4
POST_KIND_REJECTED_DISTINCT_ARTIFACTS=125
```

Le **124** publié était un compte d'**artefacts touchés par au moins un rejet de
scope** — pas un sous-ensemble des 76. Sous ce dénominateur, la somme était
impossible. Il vaut 125 après affinage des verdicts.

## 3. Autorité étendue — deux niveaux séparés

`RegulatoryProgramAuthority` dit « ce texte est un programme officiel » ;
`CurrentApplicabilityAuthority` dit « ce programme s'applique à ce scope, cette
année ». Les fondre ferait croire qu'une page Éduscol remplace juridiquement un
BO, ou qu'un vieux BO reste courant au seul motif qu'il existe.

```
CURRENT_PROGRAM_AUTHORITIES_PRE=6           CURRENT_PROGRAM_AUTHORITIES_POST=11
CURRENT_PROGRAM_SCOPES_COVERED_PRE=26       CURRENT_PROGRAM_SCOPES_COVERED_POST=56
```

Le seed respecte les distinctions imposées : `niveau_exact` obligatoire quand le
calendrier varie par classe (5e français et mathématiques basculent, pas 4e/3e) ;
`LVE ≠ LVR` ; `EPS_COMMUN_GT ≠ EPS_OPTION_GT ≠ EPPCS_SPECIALITE` ;
`LCA ≠ LLCA` ; `LVE_COMMUN ≠ LVE_OPTION ≠ LLCER_SPECIALITE` ; et un programme
limitatif (`LIMITATIVE_PROGRAM`) ne remplace jamais un programme d'enseignement.

Les scopes dont l'autorité n'a pas été relevée — 4e/3e LVE, LVR, LLCER, les arts
au lycée — portent `PENDING_AUTHORITY_LOOKUP`. Je ne les ai pas extrapolés
depuis la cinquième : c'est précisément le calendrier progressif qui l'interdit.

**Statut de preuve.** Ces applicabilités sont `DECLARED_BY_COMMANDITAIRE`, pas
`VERIFIED`. Cette session ne peut pas les vérifier : la campagne 422356d3 a
mesuré 110 refus HTTP 403 sur 111 URL institutionnelles. Les présenter comme
vérifiées leur donnerait un niveau de preuve qu'elles n'ont pas.

## 4. Rejeu du resolver seul

Aucune ré-extraction, aucun OCR, aucun découpage, aucun scan PII. Le texte
canonique et les 312 références sont gelés ; seule la couverture d'autorité a
changé.

```
PRE_AUTHORITY_SCOPE_MATCH_OCCURRENCES=0
PRE_AUTHORITY_SCOPE_MISMATCH_OCCURRENCES=22
PRE_AUTHORITY_SCOPE_UNKNOWN_OCCURRENCES=120

POST_AUTHORITY_SCOPE_MATCH_OCCURRENCES=0
POST_AUTHORITY_SCOPE_MISMATCH_OCCURRENCES=23
POST_AUTHORITY_SCOPE_UNKNOWN_OCCURRENCES=125
                                        0 + 23 + 125 = 148
```

Le total passe de 142 à 148 : cinq références du seed deviennent liantes, donc
entrent dans le dénominateur.

`SCOPE_UNKNOWN` au sens strict tombe de 43 à **29** occurrences — toutes
`BOEN_special_11_2015-11-26`. Mais `SCOPE_NOT_ATTRIBUTABLE` monte de 77 à 96, et
le gain net est nul.

## 5. Le blocage n'est pas là où nous le cherchions

```
occurrences liantes                   148
  sur artefact TRANSVERSAL            124   (83 %)
  sur artefact à placement CONCRET     24
     dont SCOPE_MATCH                   0
     dont MISMATCH                     23
```

**Quatre-vingt-trois pour cent des occurrences portent sur un artefact dont le
placement est transversal** — `transversal_multi_niveaux` (84) ou
`cycle_4_transversal` (39). Aucune extension d'autorité ne peut y produire un
`MATCH` : conformément à votre §15, un artefact transversal exige une preuve
supplémentaire reliant la référence à l'un de ses placements réels.

Et sur les 24 artefacts à placement concret, **aucun** ne correspond : 23
mismatches — théâtre, LSF, HGGSP, arts plastiques citant des BO qui ne les
couvrent pas ; français et physique-chimie citant le BO du mauvais niveau.

Le levier a donc changé de nature : ce n'est plus la **couverture d'autorité**,
c'est la **granularité du placement**. Continuer à ajouter des autorités
produira des verdicts pour 24 artefacts au plus.

## 6. Les 12 ambigus rejoués

```
AMBIGUOUS_PRE=12
AMBIGUOUS_RESOLVED_TO_MULTI_SCOPE=0
AMBIGUOUS_RESOLVED_TO_SCOPE_MATCH=0
AMBIGUOUS_RESOLVED_TO_SCOPE_MISMATCH=1
AMBIGUOUS_REMAINING=11
                                        somme = 12
```

Un seul est devenu tranchable. Les onze autres sont transversaux : l'autorité
ne les concerne pas.

## 7. Partition inchangée

```
PROGRAM_COMPATIBILITY_PROVEN=10
PROGRAM_INCOMPATIBILITY_PROVEN=0
PROGRAM_COMPATIBILITY_UNKNOWN=2441
PROGRAM_PARTITION_UNACCOUNTED=0

PROGRAM_COMPATIBLE_SHA_SET_SHA256=2caa5baf09142b8438fe29eb2791afb9e8090dbb921797cd009b65d91330bdf6
```

## 8. Ce que je recommande

Ajouter les autorités manquantes reste utile — cela remplacera de l'`UNKNOWN`
par du verdict prouvé, ce qui est l'objectif que vous avez fixé. Mais le gain
plafonne à 24 artefacts.

Le vrai gisement est ailleurs : **rendre attribuables les 124 occurrences
transversales**. Cela demande une preuve reliant une citation à un placement
précis — par exemple la section du document où la citation apparaît, ou une
déclaration de placement par niveau dans le manifeste de release. C'est un
travail sur la granularité du placement, pas sur l'autorité de programme.

```
PROGRAM_HUMAN_REVIEW_STARTED=false
CURRENTNESS_POLICY_APPLIED=false
```
