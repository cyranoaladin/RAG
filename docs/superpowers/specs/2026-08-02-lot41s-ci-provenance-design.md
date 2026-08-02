# LOT41S — Provenance non ambiguë des checks CI

## Contexte

La protection de `main` exige six contextes GitHub Actions par leur nom. Le
workflow courant produit ces mêmes noms lors des événements `push` et
`pull_request` sur les branches `lot-*`. Deux suites concurrentes peuvent donc
publier les mêmes contextes pour le même SHA. La preuve versionnée sait isoler
un run `pull_request`, mais la protection GitHub ne sait pas imposer cette
provenance à partir du seul nom du contexte.

Le rapport LOT37R a déjà corrigé une seconde ambiguïté : sa preuve distante
versionnée porte explicitement sur une tête de code antérieure au commit
documentaire final et ne prétend pas certifier celui-ci. Le plan historique
LOT37R contient toutefois encore l'instruction initiale contradictoire.

## Décision

Le workflow GitHub Actions conserve une seule exécution possible par type de
référence :

- `push` s'exécute uniquement sur `main`, afin de revalider le squash fusionné ;
- `pull_request` s'exécute uniquement pour les PR dont la base est `main` ;
- aucune exécution `push` n'est lancée sur les branches de lot ;
- ce workflow n'accepte aucun autre événement, notamment `workflow_dispatch`,
  `workflow_call`, `schedule` ou `merge_group` ;
- les six noms de jobs protégés restent inchangés : `packages/contracts`,
  `services/rag-pedago`, `services/rag-engine`, `services/cockpit`,
  `governance locks guard` et `repository controls`.

Cette topologie garantit qu'avant fusion les contextes protégés d'un SHA de
branche proviennent uniquement du run `pull_request`. Après fusion, le nouveau
SHA de squash de `main` est contrôlé par un run `push` distinct. Elle évite une
migration simultanée des noms de checks et de la politique GitHub.

## Tests et garde-fous

Le test comportemental du workflow doit exiger exactement :

- `on.push.branches == [main]` ;
- `on.pull_request.branches == [main]` ;
- l'ensemble des événements du workflow CI est exactement
  `{push, pull_request}` ;
- les branches `lot-*` et `lot-*/**` sont absentes de `push` ;
- `pull_request.branches` est traité comme un filtre sur la branche de base,
  jamais sur la branche source ;
- les jobs Cockpit restent stricts et les six contextes protégés sont présents
  exactement une fois ;
- aucun autre workflow sous `.github/workflows/` ne déclare un job portant l'un
  de ces six noms protégés.

Les tests de mutation doivent échouer si une branche de lot est réintroduite
dans `push`, si `main` disparaît d'un déclencheur ou si un déclencheur devient
plus large que le contrat exact. Ils doivent aussi refuser un événement
supplémentaire et un second workflow qui republie un nom protégé. La politique
de protection de `main` reste inchangée et son readback live doit demeurer vert.

## Preuves documentaires

Le plan LOT37R est annoté comme historique et corrigé sur deux points :

1. la preuve `pr-required-checks.json` certifie le SHA qu'elle nomme, jamais un
   commit ultérieur qui l'ajoute au dépôt ;
2. la suppression du run `push` sur les branches de lot rend désormais la
   provenance `pull_request` non ambiguë pour les checks pré-fusion.

Le rapport LOT41S consigne la reproduction initiale, les tests RED/GREEN, le
readback de protection et le verdict global `GO_LIVE: NO_GO`. Aucun verrou de
gouvernance, contrat métier ou runtime n'est modifié.

## Livraison

LOT41S est livré sur une branche et une PR dédiées. Après CI et revue finales,
la PR est fusionnée par squash sans bypass administrateur. Les deux fils de
revue historiques de la PR #79 seront ensuite documentés, répondus et résolus.
