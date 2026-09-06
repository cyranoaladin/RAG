# LOT « registre des URL sources » — dettes constatées

Échecs constatés pendant le lot, **non causés par lui**, antériorité démontrée
par mesure.

## 107 échecs `services/rag-pedago`, tous antérieurs

```
baseline (origin/glr/url-registry, checkout vierge)  107 failed, 3012 passed, 4 skipped
arbre de travail (registre de fraîcheur ajouté)      107 failed, 3024 passed, 4 skipped

REGRESSIONS = 0        (échecs présents au HEAD et absents en baseline)
REPARES     = 0        (échecs présents en baseline et absents au HEAD)
```

Les deux ensembles d'échecs sont **identiques nom par nom** — comparés par
`comm` sur les listes triées, pas par leur cardinalité, qu'une compensation
aurait pu rendre trompeuse. L'écart de `+12 passed` est exactement le nombre
d'épreuves ajoutées par ce lot.

Protocole : même interpréteur, même `PYTHONPATH`, deux arbres — l'un vierge
depuis `origin/glr/url-registry`, l'autre l'arbre de travail.

### Cause

```
57  tests/test_build_production_profile_release.py
31  tests/test_build_release_pii_projection.py
10  tests/test_release_lineage.py
 5  tests/test_model_snapshot_completeness.py
 4  tests/test_pii_review_projection.py
```

`glr/url-registry` est basée sur un `main` **antérieur** à PR #142 et #147 :
ses copies de ces bancs éprouvent des données et des contrats que `main` a
depuis fait évoluer. Le lot ne touche aucun de ces fichiers.

### Ce qui les fermera

Un rebase de la branche sur le `main` courant, une fois #149 puis #148
entrés — pas une correction de ces bancs, qui sont déjà corrigés en amont.
Aucune initiative prise ici : rebaser maintenant mêlerait à ce lot des
changements qui ne lui appartiennent pas.
