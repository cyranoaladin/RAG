# Classification automatique des niveaux — mesures

*29 août 2026. Le classifieur est validé au-dessus du seuil. Sa couverture ne
transfère pas au corpus difficile, et c'est le résultat qui décide.*

## Validation à l'aveugle sur les 1 505 niveaux connus

Trois passes, chaque amélioration dictée par le diagnostic de la précédente :

| Passe | Correctif | Accord global |
|---|---|---|
| 1 | cascade initiale, texte en tête | **59,0 %** |
| 2 | cycle 4 unifié, dominance par occurrences, URL en tête, 4 pages | **68,2 %** |
| 3 | repliement du collège appliqué **aussi** à la vérité de référence | **93,0 %** (paliers décidants) |

### Deux corrections venues de la mesure, non de l'intuition

**142 des 214 désaccords initiaux** étaient des documents cycle 4 classés « 3e »
ou « 4e ». Ce n'étaient pas des erreurs : le programme de référence d'un élève de
3e **est** celui du cycle 4. Le classifieur avait raison, la grille avait tort.

**Le repliement doit s'appliquer aux deux côtés.** La vérité de référence dit
« 3e » là où le corpus dit « cycle 4 » ; ne replier que la prédiction pénalisait
des réponses justes. 22 des 25 dernières erreurs de P2 étaient exactement cela.

### L'ordre de la cascade est mesuré, pas supposé

| Palier | Décisions | Accord |
|---|---|---|
| **P2 — `url_source`** | 694 | **96,4 %** *(99,6 % après repliement)* |
| P3 — référence B.O. | 20 | **100 %** |
| P5 — titre | 4 | **100 %** |
| P1 — texte du document | 424 | **81,8 %** |

**Le texte du document est le palier le plus faible, pas le plus fort.** Une
ressource pédagogique cite des niveaux de *prérequis* — « la notion de marché
étudiée en classe de seconde » dans un document de première. L'URL Éduscol, elle,
exprime le placement canonique. La première version plaçait le texte en tête.

## Règle fail-closed retenue

**N'accepter que les décisions de palier fort (P2, P3, P5).**

| | Documents | Accord |
|---|---|---|
| Acceptés | **718 / 1 505** (47,7 %) | **99,58 %** |
| Écartés en COVERAGE_GAP | 787 | — |

**99,58 % > 98 %.** Le seuil est atteint. P1 seul plafonne à 81,8 % et n'est pas
retenu comme décisif : mieux vaut un périmètre plus étroit et sûr.

## Le résultat qui décide — la couverture ne transfère pas

Appliqué aux **946 documents que le catalogue amont n'a pas su classer** :

| | Ensemble connu | Ensemble difficile |
|---|---|---|
| Documents | 1 505 | 946 |
| Décidés par palier fort | **718 (47,7 %)** | **35 (3,7 %)** |
| COVERAGE_GAP | 787 | **911** |

**Le taux de couverture s'effondre de 47,7 % à 3,7 %.**

La raison est structurelle, et rétrospectivement évidente : les 946 sont
précisément les documents que le catalogue n'a pas pu classer, et il ne l'a pas
pu parce que **leur URL ne porte pas de niveau**. Le palier fort est exactement
celui qui leur manque.

**Un taux d'accord mesuré sur l'ensemble facile ne prédit pas la couverture sur
l'ensemble difficile.** Les deux ensembles ne sont pas comparables : l'un est
défini par la présence du signal, l'autre par son absence.

C'est un biais de sélection, et il aurait été invisible sans cette seconde
mesure. La validation sur 1 505 cas était la bonne méthode ; elle a produit un
chiffre juste sur une population qui n'est pas celle qu'on veut classer.

### Détail des 946

| Statut brut | Documents |
|---|---|
| `CLASSE` | 294 |
| `MULTI_NIVEAUX` | 237 |
| `CONFLIT` | 8 |
| `NON_CLASSE` | 407 |

Après la règle fail-closed : **35 acceptés** (33 terminale, 1 cycle 4, 1 première),
**911 en COVERAGE_GAP**.

Les 294 `CLASSE` et 237 `MULTI_NIVEAUX` le sont par **P1 seul** — le palier à
81,8 %. Les retenir ajouterait 531 documents à un taux d'erreur de près d'un sur
cinq, dans un corpus scellé. **On ne devine pas pour combler.**

## Arithmétique finale

```
2 451  corpus
1 504  ingérables par le sous-ensemble conforme (release à produire)
   35  récupérés par classification automatique
  911  COVERAGE_GAP — aucune preuve forte
    1  conforme mais exclu (cycle4 × DGEMC, à reclasser)
─────
2 451                                                        ✓
```

**Le gain de l'automatisation est de 35 documents, pas de 946.**

## Ce que cela signifie

L'automatisation fonctionne et porte sa preuve — chaque décision cite son palier,
sa source et son extrait. Mais elle ne remplace pas la revue sur ce corpus-ci :
elle récupère 3,7 % de l'ensemble difficile.

Les 911 restants n'ont pas de signal exploitable **dans les données**. Les
classer exige la connaissance du domaine — ce que le mandat appelait, à juste
titre, un chantier pédagogique et non technique.

Le classifieur reste utile : il traitera les corpus futurs dont les URL portent
le niveau, et il documente ce qui manque sur celui-ci.


## Les deux arbitrages, résolus par le signal

### « Propositions pédagogiques pour la catégorie 2 (cycle 4) »

Première page du document, extraite :

> « À partir de la rentrée 2026, le nouveau programme **d'enseignement moral et
> civique (EMC – 2024) en 3e** s'intitule "Faire vivre la démocratie" »

**Classement : `cycle4 × EMC`**, palier P1, extrait cité. Ce n'était pas un
arbitrage : le document se nomme lui-même. Même confusion DGEMC/EMC que le
vademecum — deux occurrences du même défaut de catalogue.

### 51 documents hors périmètre assumé, dont 50 invisibles jusqu'ici

Le palier P1 appliqué aux 1 504 documents du périmètre :

| Série | Documents |
|---|---|
| ST2S | 20 |
| STL | 13 |
| STI2D | 7 |
| STD2A | 6 |
| S2TMD | 4 |
| Seconde STHR | 1 |
| **Total** | **51** |

Ils se cachaient sous des couples **génériques** — l'essentiel sous
`seconde × PHYSIQUE_CHIMIE (générale)` : « Le rôle du foie dans le stockage des
glucides », « Fruits secs et semi-marathon », « Quel menu choisir au petit
déjeuner ? » sont des ressources **ST2S**, pas de la physique-chimie de seconde
générale.

**Ce ne sont pas des documents mal classés : ce sont des documents valides d'une
voie que le mandat ne sert pas.** La nuance décide de leur sort — ils sortent en
HORS_PERIMETRE_ASSUME, ils ne sont pas corrigés.

Détail complet, avec palier et extrait par document :
`docs/reports/hors_perimetre_voies_20260829.json`.

**Le rendement de cette vérification est de 51, pas de 1.** Ma mesure initiale
n'avait vu que le document STHR, repéré par son titre. Les 50 autres n'étaient
lisibles que dans le texte — le palier que je n'exploitais pas.

## expected_topics — les B.O. consolidés

Un même arrêté couvre plusieurs disciplines, parfois plusieurs niveaux :

| Document consolidé | Pages | Portée |
|---|---|---|
| Programme du cycle des approfondissements (cycle 4) | 138 | toutes disciplines du cycle |
| Spécialité arts en première **et terminale** de la voie générale | 60 | 7 disciplines, **2 niveaux** |
| Option arts en seconde générale et technologique | 47 | disciplines artistiques |

Le second est de surcroît un cas de **multi-placement** : un artefact, deux
niveaux.

| | Avant | Après |
|---|---|---|
| Collections avec thèmes dérivés | 47 | **50** |
| Sans programme extractible | 27 | **24** |

Les 24 restantes partent **sans thèmes**, jamais avec de l'inventé. Elles sont
dominées par LLCER (50 documents), les langues vivantes (14) et l'EPS (8) —
disciplines dont les programmes sont publiés par langue ou par activité, hors du
corpus téléchargé.

## Périmètre final

```
2 451  corpus
1 489  SERVABLE   = 1 504 − 51 hors périmètre + 35 récupérés + 1 reclassé
  911  COVERAGE_GAP — aucune preuve forte
   51  HORS_PERIMETRE_ASSUME — voie valide, non servie par le mandat
─────
2 451                                                              ✓
```

Les 35 documents récupérés par classification et le document reclassé en
`cycle4 × EMC` **tombent dans des collections du découpage** : ils sont servables,
et les compter à part faisait lire 1 453 là où le chiffre est **1 489**.


## P1 réessayé comme une lecture — résultat négatif, rapporté tel quel

Le diagnostic était juste : 81,8 % n'était pas la précision d'une lecture mais
celle d'un appariement de motifs, et un document de terminale qui mentionne
« vu en première » trompe une expression régulière sans tromper un lecteur.

**J'ai donc encodé la distinction.** `p1_lecture_du_document` pèse chaque mention
de niveau par son contexte immédiat et sa position :

- un contexte de **renvoi** — « vu en », « étudié en », « prérequis », « rappel »,
  « réinvestir », « au cycle précédent » — **annule** le niveau qu'il cite ;
- un contexte de **déclaration** — « programme de », « spécialité », « option »,
  « attendus de fin d'année » — **double** son poids ;
- une mention dans les 300 premiers caractères pèse cinq fois une mention tardive :
  un document se présente en tête et cite plus loin.

### La mesure

| Version de P1 | Décisions | Accord |
|---|---|---|
| appariement de motifs | 424 | **81,8 %** |
| **lecture pondérée** | 381 | **80,3 %** |

**−1,5 point. L'approximation de la lecture n'a pas battu le motif.**

C'est un résultat négatif et je le rapporte tel quel plutôt que de le présenter
comme un progrès. La raison en est simple, et elle était prévisible : la
distinction que j'ai encodée reste **un motif sur le contexte d'un motif**. Elle
ne lit pas. Comprendre que « Le rôle du foie dans le stockage des glucides » est
une ressource ST2S ne s'obtient pas d'une fenêtre de soixante caractères autour
d'un mot-clé — cela demande de comprendre le document.

Le palier fort reste inchangé à **99,58 %** : la tentative n'a rien dégradé, elle
n'a rien apporté.

### Ce qu'une vraie lecture exigerait

Lire 2 450 premières pages est un travail de compréhension, document par
document. Ce n'est pas hors de portée — c'est hors de portée **d'une seule
passe séquentielle**. Il faudrait le distribuer, et cette parallélisation n'a pas
été autorisée.

Je ne l'ai donc pas fait, et je ne prétends pas l'avoir fait. Ce qui est mesuré
ici est une heuristique enrichie, honnêtement inférieure à celle qu'elle
remplaçait.
