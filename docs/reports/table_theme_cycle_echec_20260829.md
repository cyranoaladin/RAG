# Table thème → cycle — trois tentatives, trois défauts, arrêt

*29 août 2026. La table ne contient aucune des quatre entrées canoniques du
programme de français du cycle 4. Je ne l'exploite pas.*

## Le principe était juste

Une table dont chaque entrée est adossée à un programme du corpus, avec extrait,
vaut mieux qu'un pourcentage mesuré contre une référence fausse. La mesure
« 100 % des entrées sourcées » a été produite deux fois.

**Elle était vraie et sans valeur.** Chaque entrée avait bien une source ; la
source n'établissait pas ce pour quoi elle était citée. C'est exactement le
défaut de cette semaine — un sceau qui atteste une liste sans vérifier qu'elle
couvre ce qu'elle prétend — reproduit par moi, dans le contrôle censé le prévenir.

## Les trois défauts, dans l'ordre où ils sont apparus

### 1. Fenêtre de vingt pages

L'extracteur lisait `pages[:20]` d'un programme de **138 pages**. Les quatre
entrées du français cycle 4 sont **page 27**. Le thème le plus canonique du
corpus était hors d'atteinte de la table censée le contenir.

*Corrigé : lecture intégrale, 138 pages, 431 933 caractères, 7,2 s.*

### 2. Portée lue dans le corps du texte

`portee_du_programme` prenait la première mention de niveau dans le corps. Or le
programme de spécialité **de première et terminale** contient « les enseignements
scientifiques communs **en classe de seconde** » — un prérequis. Résultat :
**1 377 thèmes attribués à `seconde`**, dont ceux de programmes de terminale.

C'est le défaut de prérequis que j'avais diagnostiqué pour P1, puis réintroduit
ici de ma main.

*Corrigé : la portée se lit dans le TITRE — déclaration de l'éditeur, sans
prérequis. Distribution redevenue plausible : première 786, terminale 592,
seconde 333.*

### 3. Plafond de quarante lignes — non corrigé

`themes_du_programme` retient les **40 premières lignes candidates** et s'arrête.
Dans un document de 138 pages, ces 40 lignes sont la page de titre et le
préambule. Les thèmes réels viennent après.

Ce que la table contient donc, sous l'étiquette « thème » :

```
· En outre, un enseignement d'informatique, est dispensé à la fois dans le c…
· Domaine du socle : 4
· En continuité de l'éducation scientifique et technologique des cycles préc…
```

**Ce sont des phrases de préambule, pas des entrées de programme.**

## La contre-épreuve, échouée deux fois

Les quatre entrées du programme de français du cycle 4 — « Se chercher, se
construire », « Vivre en société, participer à la société », « Regarder le monde,
inventer des mondes », « Agir sur le monde » — sont **absentes des deux versions
de la table**.

Le programme de cycle 4 (138 pages) contribue **zéro entrée**, alors que son titre
passe la détection de portée et que sa lecture réussit.

## Pourquoi je m'arrête ici

Écrire cette table dans une release scellée reviendrait à affirmer « voici les
thèmes du programme » à propos de phrases de préambule. Les entrées sont
techniquement sourcées ; **elles n'établissent pas ce qu'on leur fait dire.**

C'est la condition d'arrêt : *une entrée de table que je serais tenté d'écrire
quand même*.

Le défaut restant est identifié et cernable — il faut extraire les thèmes par
leur **structure éditoriale** (titres de section, niveaux de plan, table des
matières du document) plutôt que par un balayage linéaire plafonné. Ce n'est pas
hors de portée ; ce n'est pas fait, et je ne livre pas une table qui échoue sa
propre contre-épreuve.

## Ce qui reste acquis de cette nuit

| Acquis | Valeur |
|---|---|
| Bandeau éditeur P0 | **1 027 documents**, 41,9 % |
| dont niveau exact | 759 |
| dont cycle | 232 |
| dont transversal lycée | 36 |
| **Catalogue corrigé par l'éditeur** | **549 / 759 = 72,3 %** |
| dont non classés désormais résolus | 446 |
| dont erreurs franches corrigées | 103 |
| Documents hors périmètre détectés | 51 |

Ces acquis-là sont mesurés et sourcés, et ils tiennent.
