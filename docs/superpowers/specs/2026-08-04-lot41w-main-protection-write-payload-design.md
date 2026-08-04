# LOT41W — Sérialisation d'écriture de la protection de `main`

## Statut et objectif

Cette spécification formalise le correctif approuvé après l'application de
LOT41V. Le contrôleur versionné relit correctement la protection GitHub, mais
son mode `--apply` envoie le document canonique sans l'adapter au schéma
d'écriture de l'API. GitHub a rejeté ce payload en HTTP 422 parce que
`required_status_checks` contenait à la fois `contexts: []` et `checks`.

Le rejet n'a produit aucune mutation partielle. Les quatre règles de review ont
ensuite été appliquées par l'endpoint étroit et le mode `--check` a confirmé que
la protection live correspond exactement à la politique LOT41V.

LOT41W rend uniquement le chemin d'application global reproductible. Il ne
change aucune règle de protection, aucun reviewer, aucun check requis et aucun
verrou métier. Le verdict global reste `GO_LIVE: NO_GO`.

## Décision

La politique JSON reste la représentation canonique de l'état attendu en
lecture. Elle conserve `contexts: []` pour affirmer explicitement qu'aucun
contexte historique non lié à une application n'est autorisé, ainsi que les six
objets `checks` liés à l'application GitHub Actions.

Une fonction pure construit une copie destinée à l'endpoint d'écriture. Lorsque
`checks` est utilisé, elle retire uniquement la clé `contexts` de
`required_status_checks`. Tous les autres champs sont transmis sans changement.
Le document chargé depuis disque n'est jamais muté.

`apply_policy()` utilise cette copie pour le `PUT`, puis conserve la relecture
globale existante et compare la réponse distante au document canonique complet.
Le SHA exact de `main` et la confirmation `repository@SHA` restent obligatoires
avant toute écriture.

## Alternatives écartées

1. Retirer `contexts` de la politique canonique aurait affaibli l'invariant
   explicite interdisant les contextes legacy et élargi le changement aux
   chemins de normalisation et de readback.
2. Remplacer définitivement le `PUT` global par plusieurs endpoints `PATCH`
   aurait fragmenté l'application, augmenté le risque d'état partiel et laissé
   plusieurs chemins d'écriture à maintenir.
3. Réessayer le même payload ou contourner la validation GitHub n'est pas
   acceptable : l'erreur documente une union exclusive de représentations.

## Erreurs et sûreté

La construction du payload échoue avant réseau si la politique est invalide.
Une erreur GitHub reste fail-closed et interdit toute déclaration de succès.
Après un `PUT` accepté, une relecture complète est toujours obligatoire ; toute
dérive provoque un échec non nul.

La réparation n'introduit ni shell, ni secret, ni permission supplémentaire.
Elle n'autorise pas de nouvelle valeur et ne modifie pas la protection live par
effet de bord pendant les tests.

## Tests exigés

Le développement suit RED → GREEN → REFACTOR. Les tests doivent démontrer que :

- le payload d'écriture contient `strict` et les six `checks`, mais aucune clé
  `contexts` ;
- la politique canonique conserve `contexts: []` après sérialisation ;
- les autres champs du document sont inchangés ;
- `apply_policy()` transmet exactement le payload adapté ;
- la relecture et la comparaison globales restent exécutées ;
- les gardes SHA et confirmation restent fail-closed ;
- les 34 tests préexistants et la CI locale ne régressent pas.

## Livraison et preuve

Le lot est livré par une branche et une PR dédiées avec un rapport
`docs/reports/lot_41w_*.md`. La PR doit obtenir les six checks requis et une
review Code Owner formelle de `abenrhouma` sur son head final.

Après fusion, le run `push` du SHA exact de `main` doit être vert. Une exécution
réelle de `main_protection.py --apply`, liée à ce SHA par la variable de
confirmation, doit alors réussir, puis `--check` et une relecture API
indépendante doivent confirmer l'état complet.
