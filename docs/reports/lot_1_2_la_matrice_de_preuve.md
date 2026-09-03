# LOT 1.2 — la matrice de preuve est un catalogue de candidats, et le filtre est traçable

> Mesure préalable à la production : 2 389 contenus dans la matrice, 319 en base. Catalogue
> de candidats, ou état visé arrêté en chemin ?

## La base est un sous-ensemble strict, sur les trois axes

```
matrice_preuve_v2_20260829.json ... 121 collections · 2 389 contenus · 5 265 couples
base .............................. 11 collections ·   319 contenus ·   486 couples

les 11 collections ⊂ les 121 ......... vrai   (11/11)
les 319 contenus ⊂ les 2 389 ......... vrai   (319/319)
les 486 couples ⊂ ceux de la matrice . vrai   (486/486)
```

**C'est un catalogue de candidats.** Aucun contenu, aucune collection, aucun couple de la
base n'est étranger à la matrice.

## L'écart résiduel, sur les onze collections retenues

```
la matrice déclare, pour ces 11 collections seulement : 321 contenus · 490 couples
la base en porte ...................................... 319 contenus · 486 couples
                                                        ----------------------------
écart ................................................. 2 contenus · 4 couples
```

Les quatre couples sont deux contenus, chacun placé dans une collection de première **et**
une de terminale :

```
3bc5ff233dc05e96…   hggsp_premiere + hggsp_terminale
8848f0732cc1a51a…   nsi_premiere   + nsi_terminale
```

## Pourquoi ils sont exclus — et c'est légitime

Rien dans la matrice ne les distingue : `profile_decision_required: False`, même
`partition_kind` que les autres. Ils ne figurent dans **aucun** artefact de release —
ni `candidate_inventory`, ni `currentness_evidence`, ni `pii_evidence`, ni `preflight`,
ni `catalog_delta`. L'exclusion est donc **antérieure** à la production de la release.

`docs/reports/evidence-index/content_ledger_20260814.jsonl` la porte :

```
EXTRACTABILITY ....... EXTRACTION_FAILED
PII .................. REVIEW_REQUIRED
FINAL_DISPOSITION .... REVIEW_REQUIRED
REASON_CODES ......... PII_EXTRACTION_FAILED:PDF_PAGE_TEXT_EXTRACTION_EMPTY, ROUTING_E…
RIGHTS ............... CLEARED_BY_HUMAN_DECISION
```

**Deux PDF dont l'extraction de texte rend une page vide.** Le balayage PII n'a donc pas pu
s'exercer, la disposition est `REVIEW_REQUIRED`, et le producteur les a écartés. **Le filtre
est traçable, motivé, et il a bien fonctionné.**

## Réponse à la question décisive

> La production depuis cette matrice rendra-t-elle 486 placements, ou davantage ?

**486, à condition que la porte de disposition s'applique** — et elle s'applique, puisque le
registre de contenus porte la disposition et que la production la lit. Produire depuis cette
matrice reproduit l'état existant ; cela n'en crée pas un nouveau.

**Et si le nombre rendu diffère de 486, ce sera un résultat**, non un échec : soit deux PDF
sont devenus extractibles, soit la porte ne s'est pas appliquée. Les deux se distinguent en
regardant lesquels des quatre couples apparaissent.

## Ce que cela laisse ouvert

- **2 070 contenus et 110 collections** de la matrice ne sont pas produits. Ce n'est pas un
  arrêt : ce sont des candidats dont la disposition n'autorise pas la publication, ou qui
  relèvent de collections non instanciées. **Le critère exact n'est pas mesuré ici.**
- **Ces deux PDF à extraction vide** rejoignent la famille déjà rencontrée dans cet audit.
  Ils sont écartés, pas perdus : le registre les nomme et dit pourquoi.
