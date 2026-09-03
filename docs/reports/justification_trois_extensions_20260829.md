# Justification des trois extensions du périmètre contractuel

La release des 319 porte onze collections. Huit d'entre elles avaient déjà un
artefact de scope au registre — leur ré-émission est un **rescellement**. Trois
n'en ont jamais eu : `rag_nexus_hlp_terminale_specialite`,
`rag_nexus_hggsp_premiere_specialite`, `rag_nexus_hggsp_terminale_specialite`.
Les publier est une **extension du périmètre contractuel**, pas un rattrapage, et
chacune reçoit ici sa justification.

Deux éléments sont exigés : la collection est au périmètre commercial de Nexus,
et son texte fondateur est nommé.

## Élément commun — le périmètre commercial

**ADR-0048**, *Périmètre produit du GO-LIVE*, statut **Accepté**, décision
opérateur du 27/08/2026, pose :

```
GO_LIVE_REQUIRED_SCOPE = college + lycee_general + stmg
```

et détaille : « **Lycée général** — Seconde, Première, Terminale : enseignements
communs, **spécialités**, options, enseignements facultatifs… ». HLP et HGGSP sont
des spécialités du lycée général. **L'élément est acquis pour les trois, par un ADR
accepté**, sans interprétation.

## `rag_nexus_hlp_terminale_specialite` — corroboration directe

**Volume** : 90 documents, 1 612 chunks.

**Texte fondateur** : `BOEN_special_8_2019-07-25`.

**Corroboration directe.** Un document de la collection, typé `programme_officiel`,
l'énonce lui-même :

> « arrêté du 17 juillet 2019 paru au BOEN spécial n° 8 du 25 juillet 2019 »

La collection déclare donc son propre texte fondateur. Aucune inférence.

## Les deux HGGSP — corroboration indirecte, et sa faiblesse est nommée

**Volume** : `hggsp_premiere` 39 documents / 1 858 chunks ;
`hggsp_terminale` 35 documents / 1 874 chunks.

**Textes fondateurs** : `BOEN_special_1_2019-01-22` (première),
`BOEN_special_8_2019-07-25` (terminale).

### L'argument

La réforme de 2019 a publié les programmes de spécialité de **première** au
Bulletin officiel spécial n° 1 du 22 janvier 2019, et ceux de **terminale** au
spécial n° 8 du 25 juillet 2019. Le corpus **énonce ce motif deux fois**, dans des
documents `programme_officiel` d'autres collections :

- HLP première — « arrêté du 17-1-2019 publié au BO spécial n° 1 du 22 janvier 2019 » ;
- HLP terminale — « arrêté du 17 juillet 2019 paru au BOEN spécial n° 8 du 25 juillet 2019 ».

HGGSP déclare exactement ces deux valeurs. La justification ne repose donc pas sur
une déclaration isolée qui se citerait elle-même, mais sur la **cohérence avec un
motif structurel corroboré ailleurs dans le corpus**.

### Sa faiblesse, et ce qui la réfuterait

- **Corroboration indirecte.** Taux d'exception mesuré sur les 40 taxonomies du
  dépôt : **≈ 20 %**. Les exceptions sont nommées — `BOEN_special_2_2020-02-13`
  (deux spécialités par groupe), et les mathématiques republiées en 2026
  (`BOEN_14_2026-04-02`).
- **Le corpus ne contient pas le texte fondateur de HGGSP.** Recherche exhaustive :
  **0 occurrence** de « Bulletin officiel » ou « BOEN » sur 1 858 et 1 874 chunks.
  Les 5 documents typés `programme_officiel` de chaque niveau sont des **ressources
  d'accompagnement** issues de la page des programmes — 160 chunks, 184 470
  caractères, mais aucun arrêté. Le moissonnage a pris les ressources, pas le texte.
- **La source officielle est injoignable** : `education.gouv.fr` et
  `eduscol.education.gouv.fr` rendent **403** depuis la machine de production des
  releases.
- **Rien de servi ni de gravé n'en dépend.** Depuis ADR-0055 §6,
  `programme_version` porte `EDUSCOL_CORPUS_20260808` ; la référence BOEN n'entre
  dans aucun artefact et n'est rendue à aucun élève. Si elle se révélait fausse, la
  réparation serait **un ADR corrigé** — ni scope `_v3`, ni réémission, ni contenu
  changé.
- **Réfutable** le jour où la source officielle sera atteignable, ou lorsqu'un
  document HGGSP énonçant son arrêté sera moissonné.

C'est l'idiome que ce projet emploie déjà pour la fraîcheur
(`CURRENTNESS_UNVERIFIED_SOURCE_UNREACHABLE`) : **une lacune déclarée, bornée,
close.**

### Pourquoi les deux partent quand même

74 documents sur 319, soit **23 % des documents** — mais **3 732 chunks sur 8 324,
soit 45 % du contenu interrogeable**. La recherche rend des chunks, pas des
documents, et les documents HGGSP sont peu nombreux et volumineux.

> Retirer HGGSP retirerait près de la moitié du contenu interrogeable d'une
> première mise en service, sur un doute portant sur une référence documentaire qui
> n'est gravée nulle part et servie à personne. La disproportion tranche.

## Limite de domaine du motif employé — à lire avant de le réemployer

Le motif lexical de promulgation (« publié au », « paru au », « arrêté du ») est
**bruité par la matière qu'il interroge**. Sur HGGSP — histoire, géographie,
géopolitique — les neuf occurrences d'« arrêté » sont toutes de la prose historique :
*arrêtés de classement au patrimoine*, *arrêté municipal*, *elle est arrêtée*,
*les traités ont arrêté les violences*. Et « paru au » a rendu deux faux positifs :
*« parue au début des années 2010 »*, *« parus au total »*.

> Le même filtre est **fiable sur HLP et trompeur sur HGGSP**, sans que rien ne le
> signale. Un motif réglementaire appliqué à un corpus d'histoire doit être vérifié
> occurrence par occurrence avant d'en conclure quoi que ce soit.
