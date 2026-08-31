# LOT 1.2 — divergence brute entre les matrices amont et les populations mesurées

> Publiée **avant** toute rectification. La divergence est le diagnostic.
> Autorité : `rag_artifact_placements` de la base servie, 2026-09-01.

## Les trois nombres

| | matrices du 25 août | autorité en base |
|---|---:|---:|
| collections | **18** | **11** |
| contenus distincts | **26** | **319** |
| couples (collection, contenu) | **26** | **486** |

## Le recouvrement, dans les deux sens

```
CONTENUS
   communs ...................... 13 / 26
   déclarés et INEXISTANTS ...... 13
   présents et NON DÉCLARÉS ..... 306

COUPLES (collection, contenu)
   communs ......................  11
   déclarés et INEXISTANTS ......  15
   présents et NON DÉCLARÉS ..... 475

COLLECTIONS
   communes .....................   8
   déclarées seulement ..........  10
   en base seulement ............   3   hggsp ×2, hlp_terminale
```

## Ce que cela établit

**Les matrices du 25 août et la base ne décrivent pas la même livraison.** Ce n'est pas une
dérive : sur vingt-six couples déclarés, **onze seulement existent**. Quinze désignent un
document dans une collection où il n'est pas. Et quatre cent soixante-quinze placements
réels ne sont déclarés nulle part dans ces matrices.

Les dix collections déclarées et absentes sont exactement celles que
`lot_1_audit_coherence_taxonomique.md` a mesurées sans un seul chunk — français, maths, pc,
philo. Les trois présentes et non déclarées — `hggsp` ×2, `hlp_terminale` — sont exactement
celles que `ffc1bae` omettait.

**Les matrices portent le même défaut que `ffc1bae`, et pour cause : elles en sont l'amont.**

## Pourquoi la production de la release échoue

```
produce_release_scope_placement_from_git(...)
   ReleaseScopePlacementProducerError:
   UNACCEPTED_COLLECTION: 'rag_nexus_philo_terminale_tc' is not in release
```

Le producteur construit la projection depuis les matrices, puis exige que chaque collection
soit dans la release. `philo_terminale_tc` est dans la matrice et pas dans la release des
onze. **Le refus est correct : c'est l'amont qui déclare une collection que la release ne
connaît pas.**

## Ce qu'une rectification devra produire

Les matrices rectifiées doivent déclarer les **486 placements** et les **319 contenus** des
onze collections mesurées, et rien d'autre. Les vingt-six couples actuels ne sont pas un
sous-ensemble à compléter : **quinze d'entre eux sont à retirer**, car ils désignent des
placements qui n'existent pas.

## Périmètre

- `docs/reports/final_production_profile_matrix_20260825.json` — 18 entrées, 26 couples.
- `docs/reports/production_profile_accepted_placements_20260825.json` — 26 entrées.
- `docs/reports/verified_production_profiles_20260825.json` — 18 profils.
- Autorité : `rag_artifact_placements`, 486 lignes, base `ragdb`, 2026-09-01.

Aucun échantillon : chaque comparaison porte sur l'intégralité des deux ensembles, et dans
les deux sens.
