# Lecture par agents — la validation échoue, et la référence est en cause

*29 août 2026. Seuil non atteint : 93,33 % contre 98 % exigés. Arrêt, comme convenu.*

## Le protocole

200 documents tirés au hasard parmi les 1 504 de niveau connu, **graine fixe**
(20260829) pour que le tirage soit rejouable. Huit agents lecteurs, 25 documents
chacun, **sans jamais voir l'étiquette de référence**. Chaque classement devait
citer la phrase littérale qui décide, et déclarer `certitude: insuffisante` plutôt
que de choisir par défaut.

## Le résultat brut

| | |
|---|---|
| Documents lus | **200 / 200** |
| Décidés | 180 |
| Fail-closed, non déterminables | **20** |
| **Accord sur les décidés** | **168 / 180 = 93,33 %** |
| Seuil exigé | 98 % — **NON ATTEINT** |

Le fail-closed a été respecté : 20 documents rendus vides, avec des motifs
explicites — un témoignage d'artiste sans mention de niveau, une déclaration
ministérielle européenne, un livret « second degré » sans niveau déclaré.

## Pourquoi je n'applique pas — et pourquoi ce n'est pas la lecture qui a échoué

**Sur les 12 désaccords, 10 sont des erreurs de la référence, pas de la lecture.**

Les documents portent leur niveau **dans leur propre bandeau d'en-tête**, et le
catalogue amont les étiquette autrement :

| Document | Bandeau du document | `niveau` du catalogue |
|---|---|---|
| De la plante sauvage à la plante domestiquée | `VOIE GÉNÉRALE Sciences de la vie et de la Terre **Tle**` | `seconde` |
| QCM 2 | `VOIE GÉNÉRALE Sciences de l'ingénieur **Tle**` | `seconde` |
| Analyse du sujet n°1 spécimen | « programmes de Biochimie… de **terminale STL** » | `seconde` |
| Se former à l'oral en spécialité BBB | `voie technologique Biochimie… **Tle**` | `seconde` |
| Guide Grand oral | épreuve **de terminale** par définition | `seconde` |
| Les transferts thermiques | `VOIE TECHNOLOGIQUE Physique-chimie pour la santé **1re**` | `seconde` |
| … | | |

**Deux désaccords seulement sont de vraies erreurs de lecture :**

- « Structures de données » — le texte extrait est illisible
  (`Numé����e �t S��e�c�� ��fo���t��u��`), une défaillance d'extraction PDF, et
  l'agent y a lu « T L E » dans du bruit. Erreur réelle.
- « Fiche professeur » — l'agent a lu « EXEMPLES D'EXERCICES SECONDE **VOIE
  PROFESSIONNELLE** », voie hors périmètre de toute façon.

**Taux d'accord réel de la lecture, si la référence était juste : 178/180, soit
98,9 %.** Mais je ne peux pas le revendiquer : établir que la référence est fausse
sur 10 cas ne prouve pas qu'elle est juste sur les 168 autres.

## La conséquence grave, qui dépasse cette mesure

Le champ `level` du catalogue amont **n'est pas une vérité de référence**. Cette
nuit en a produit quatre démonstrations indépendantes :

1. 8 documents mal classés (DGEMC ↔ EMC, HGGSP ↔ histoire-géographie) ;
2. 51 documents de séries technologiques rangés sous `seconde × PHYSIQUE_CHIMIE` ;
3. 10 documents de terminale étiquetés `seconde`, ici ;
4. un document CM2 rangé sous `cycle-4`.

**Et cela contamine rétroactivement le 99,58 % du palier P2.** L'URL source et le
champ `level` du catalogue dérivent tous deux de la même arborescence Éduscol :
leur accord mesure la cohérence interne d'une source, non l'exactitude d'un
classement. **Je ne peux plus affirmer que P2 classe juste à 99,58 % — je peux
seulement affirmer qu'il reproduit le catalogue à 99,58 %.**

C'est le défaut de cette maison, rencontré une fois de plus et cette fois dans ma
propre mesure : **un contrôle qui affirme plus qu'il n'a vérifié.**

## Ce qu'il faudrait pour trancher

Une vérité de référence indépendante du catalogue. Le bandeau d'en-tête des
documents Éduscol — `VOIE GÉNÉRALE / Sciences de la vie et de la Terre / Tle` —
en est une : il est apposé par l'éditeur du document, pas par le moissonneur.

Construire cette référence, puis rejouer les deux mesures contre elle, est le
travail qui rendrait ces chiffres interprétables. Il n'est pas fait ici.

## Acquisition Éduscol — bloquée

Les 24 pages de listing répondent **HTTP 403 Forbidden** à une requête programmée.
Éduscol refuse l'accès automatisé. Aucun document acquis, aucun scellé — et rien
d'inventé pour compenser.

Le script `scripts/acquerir_bo_eduscol.py` est en place, avec sa corroboration
croisée B.O. listing ↔ B.O. document et son refus de tout domaine autre que
`eduscol.education.gouv.fr` en TLS. Il fonctionnera le jour où l'accès sera
possible ; il ne contourne pas le refus.
