# Rapport — Lot 11.5 : Clôture extraction (références biblio)

## Résidu corrigé

2/16 fichiers gardaient des références bibliographiques en fin (`convexite`: ISBN..., `suites`: Ellipses...). Cause : le retrait structurel décomposait le TITRE « Bibliographie » mais laissait le CONTENU quand les références n'étaient pas des siblings directs (DOM imbriqué).

## Correctif

- `find_all_next()` au lieu de `find_next_siblings()` : traverse tout le DOM après le heading terminal
- Classes élargies : `ouvrage`, `bibliographie`
- Filet textuel bibliographique : tronque au premier `ISBN`/`lire en ligne`/`coll.`/`éd.)` dans le dernier quart
- Détecteur : `lire en ligne` ajouté aux chrome_markers

## Preuve indépendante : 0/16 sur référentiel EXHAUSTIF

Référentiel de 22 marqueurs (16 queue + 6 tête) défini indépendamment du correctif :

```
grand_oral/grand_oral_expression_orale.json      len=  1234 CLEAN
grand_oral/grand_oral_transversalite.json        len=  3388 CLEAN
mathematiques/mathematiques_continuite.json      len= 20033 CLEAN
mathematiques/mathematiques_convexite.json       len= 45445 CLEAN
mathematiques/mathematiques_derivation.json      len= 34368 CLEAN
mathematiques/mathematiques_limites.json         len= 25902 CLEAN
mathematiques/mathematiques_suites.json          len= 20775 CLEAN
nsi/nsi_arbres.json                              len=  5156 CLEAN
nsi/nsi_files.json                               len=  5437 CLEAN
nsi/nsi_graphes.json                             len= 42650 CLEAN
nsi/nsi_listes.json                              len=  4579 CLEAN
nsi/nsi_piles.json                               len=  7049 CLEAN
philosophie/philosophie_droit.json                len=  8248 CLEAN
philosophie/philosophie_etat.json                 len= 55214 CLEAN
philosophie/philosophie_justice.json              len= 50796 CLEAN
philosophie/philosophie_liberte.json              len= 26024 CLEAN

CLEAN: 16/16
```

Pas de sur-troncature : convexité 45K, état 55K, justice 50K (longueurs saines).

## Couverture substantielle : 16/30 (53%) — confirmé

## CI locale : 7/7 PASS
