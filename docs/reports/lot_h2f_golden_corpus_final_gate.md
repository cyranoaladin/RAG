# Lot H2-F — final gate du corpus golden

## Objet

Ce lot ferme les constats de revue de PR #95 sans modifier les conditions
d'autorité LOT41A-V2 ni activer l'ingestion. Le final gate golden accepte
uniquement un catalogue `REAL_SEALED_CORPUS` et exécute ses contrôles sur les
2 584 objets physiques gouvernés.

## Doctrine exécutable

- Le schéma final est explicite : `physical_objects` et `content_sha256`.
  Aucun auto-détecteur de schéma historique n'est admis dans le final gate.
- Un contrôle positif distingue l'éligibilité locale de base de la
  disposition finale. La currentness `actuel` ne remplace jamais un gate
  d'autorité absent.
- Les contrôles de frontière et négatifs évaluent toutes leurs
  correspondances et exigent leur population exacte. Une absence est un
  échec sur le catalogue scellé.
- La couverture de décision et la validation golden sont deux résultats
  distincts. `H2_COVERAGE_GATE_PASS` exige les deux, plus les invariants de
  sécurité d'un éventuel ensemble `INGEST`.
- Les assertions documentaires sont marquées non autoritatives ; seuls les
  contrôles réellement exécutés entrent dans le décompte golden.

## Périmètre golden réel

La spécification H2-F contient six positifs base-éligibles mais encore
`REVIEW_REQUIRED` faute d'autorité de production, trois frontières complètes
et quatre contrôles négatifs exhaustifs. Les populations historiques
attendues sont vérifiées contre le catalogue réel, jamais ajustées
automatiquement :

- `80_A_VERIFIER` : 805 objets ;
- `20_TRANSITION_OU_ACTUEL` : 49 objets ;
- `90_ARCHIVE_CATALOGUE` : 19 objets ;
- ressources GeoGebra : 37 objets.

## Preuves

Le rapport de validation conserve les SHA-256 complets du catalogue et de la
spécification, le digest du manifeste scellé, le HEAD Git complet, la version
du validateur, les décomptes par type et le nombre total d'objets évalués.
Une mutation H2-F séparée neutralise la consommation du verdict golden par le
rapport de couverture ; elle doit rendre rouge un test ciblé puis restaurer
exactement les octets et le test vert.

Les preuves d'exécution finales sont générées hors Git, sans contenu brut ni
PII, sur le HEAD figé de PR #95. Toute modification ultérieure du HEAD rend
ces preuves et l'audit caducs.

## Sécurité et activation

Ce lot ne touche aucune base de production, n'active aucun writer public ou
caché, ne câble pas le pipeline LOT42 en production et ne modifie pas PR #96.
L'autorité réelle reste différée après la fusion de PR #95, conformément à la
séquence LOT41A-V2.
