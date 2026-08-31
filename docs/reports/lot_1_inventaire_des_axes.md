# LOT 1 — inventaire des axes par table, et revue des constats mesurés sur `rag_chunks`

> Ordonné après que quatre constats sont tombés pour une cause unique : avoir interrogé
> `rag_chunks` là où l'autorité est `rag_artifact_placements`.

## Où vit chaque axe

Treize axes existent **dans les deux tables**. Pour chacun, la divergence est mesurée sur
les 12 403 couples de la jointure.

| axe | chunks | artifacts | PLACEMENTS | divergents / 12 403 |
|---|:--:|:--:|:--:|---:|
| `collection` | oui | — | **oui** | **4 079** |
| `tenant` | oui | — | **oui** | **4 079** |
| `niveau` | oui | — | **oui** | **4 079** |
| `audience` | oui | — | **oui** | **12 403** |
| `visibility` | oui | — | **oui** | **12 403** |
| `voie` | oui | — | oui | 0 |
| `matiere` | oui | — | oui | 0 |
| `statut_enseignement` | oui | — | oui | 0 |
| `candidat` | oui | — | oui | 0 |
| `school_year` | oui | — | oui | 0 |
| `programme_version` | oui | — | oui | 0 |
| `review_status` | oui | — | oui | 0 |
| `rights` | oui | **oui** | — | non mesuré |
| `notions` | **oui** | — | — | — |

**Cinq colonnes de `rag_chunks` sont périmées**, non deux :

- `collection`, `tenant`, `niveau` divergent sur 4 079 — exactement les seconds placements,
  que la copie ne peut pas porter ;
- `audience` et `visibility` divergent sur **la totalité** : la copie dit
  `{libre,tous}` / `internal`, l'autorité dit `{aefe,libre}` / `public`.

`notions` n'existe **que** dans `rag_chunks` : aucune autre table ne porte cet axe.

## Revue des trois constats taxonomiques

| constat | mesuré sur | confronté à l'autorité | verdict |
|---|---|---|---|
| notions : 0 rattachement sur 8 324 | `rag_chunks.notions` | aucune autre table ne porte l'axe | **TIENT** |
| niveaux : 2 sur 5 déclarés | `rag_chunks.niveau` | `placements` : `premiere` 235, `terminale` 251 | **TIENT** |
| matières : 6 sur 24 déclarées | `rag_chunks.matiere` | `placements` : dgemc, hggsp, hlp, nsi, ses, svt | **TIENT** |

Les trois constats du tableau taxonomique **survivent** à la confrontation. `niveau`
diverge bien sur 4 079 couples, mais les **valeurs distinctes** sont les mêmes des deux
côtés : deux niveaux, pas cinq.

## Ce qu'un élève atteint — prédicat complet, pas une colonne

Le prédicat de placement exécuté **entièrement**, avec les listes dérivées par le dépôt
pour le rôle `student` (`allowed_visibilities_for_role`, `allowed_rights_for_role`) :

```
rag_nexus_dgemc_terminale_option ..........   368
rag_nexus_hggsp_premiere_specialite ....... 1 858
rag_nexus_hggsp_terminale_specialite ...... 1 874
rag_nexus_hlp_premiere_specialite ......... 1 997
rag_nexus_hlp_terminale_specialite ........ 1 612
rag_nexus_nsi_premiere_specialite .........   483
rag_nexus_nsi_terminale_specialite ........   904
rag_nexus_ses_premiere_specialite .........   726
rag_nexus_ses_terminale_specialite ........   804
rag_nexus_svt_premiere_specialite .........   681
rag_nexus_svt_terminale_specialite ........ 1 096
                                            ------
TOTAL atteignable par un ÉLÈVE ............ 12 403
```

Chaque garde dépendante du rôle passe :

```
visibility   placement `public` × 486        · student autorise ('public',)        → passe
rights       artifact `officiel_public` ×319 · student autorise officiel_public    → passe
audience     placement {aefe,libre}          · requête ('libre','tous')            → recouvre `libre`
candidat     placement `libre` × 486         · liste de rôle contient `libre`      → passe
```

**Un élève atteint la totalité du corpus déclaré.** C'est l'exact inverse du constat publié
la veille, qui comptait `rag_chunks.visibility`.

## Ce que cette mesure n'est pas

Ce n'est pas une requête traversant l'API avec un jeton réel. C'est le **prédicat du dépôt,
exécuté avec les listes que le dépôt dérive pour le rôle**, la portée de chaque requête
étant celle que la collection déclare.

Restent non mesurés : la construction de la portée depuis un jeton, les gardes situées en
amont du prédicat, et le classement des résultats. **Le prédicat de portée ne bloque pas un
élève ; ce qui se trouve avant lui n'a pas été éprouvé.**
