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

## Revue automatisée après le premier correctif H2-F

La revue Codex exécutée sur `b4f8870d4b9e667fd7456214bf207333fcde5800`
a trouvé trois autres chemins de succès incomplets. Leur fermeture fait partie
du même lot et rend caduc le verdict H2-F attaché à ce SHA :

- le gate de droits exige désormais un `source_evidence` non vide dont la
  population est exactement celle déclarée dans `summary.total_zones` ;
- le gate de currentness valide ses en-têtes, chaque identité SHA/chemin et la
  concordance entre le périmètre Eduscol déclaré et les lignes effectivement
  classifiées ; un fichier vide, renommé, tronqué ou mal formé reste rouge ;
- le runner PII ne renvoie zéro que pour un périmètre non vide intégralement
  scanné, sans objet `REVIEW_REQUIRED`, échec d'extraction, objet non scanné ni
  mismatch SHA.

Sur les entrées réelles, le registre de droits conserve cinq zones et passe.
La preuve PII scellée `76e6ba3cd5b1c116c8647b611eb3fdeb2aba6b8c7fdfbad9e71048354956f311`
conserve 64 objets requis, 64 scannés, 63 clairs, un mis en quarantaine et zéro
objet non scanné. Le périmètre Eduscol physique dérivé du catalogue réel compte
2 451 lignes, toutes évaluées, sans ligne mal formée ou ignorée. Ses 1 513
documents encore non classés restent correctement bloqués/reviewables ; ils ne
sont pas transformés en éligibilité d'ingestion.

## Revue automatisée du deuxième correctif H2-F

La revue Codex exécutée sur `4d09148976e71c8bfa24e5377d1d42f90939e96e`
a rendu caducs la CI, les preuves et l'audit attachés à ce HEAD. Elle a
identifié quatre fermetures supplémentaires sur le gate PII :

- le transport Google Drive est sorti de `services/rag-pedago/`. Le scanner
  H2-B ne possède plus de dépendance réseau ou `rclone` et accepte uniquement
  un miroir local pré-matérialisé ;
- le CLI mono-PDF renvoie un échec si l'extraction n'a pas abouti, même en
  l'absence de détection PII ;
- le mode corpus refuse un manifest vide, sans PDF, mal formé ou incomplet. Un
  périmètre non vide et intégralement évalué est obligatoire avant toute
  attestation ;
- le SHA-256 des octets locaux est calculé et comparé au manifest avant tout
  appel d'extraction. Le SHA observé n'est jamais remplacé par une valeur
  déclarative.

Le transport opérateur est désormais un processus séparé à la racine du dépôt.
Il matérialise en lecture seule une liste positive dérivée du manifest dans un
répertoire borné `/tmp/nexus-h2b-pii.*` de mode `0700`. Son reçu non sensible ne
constitue pas une attestation PII : seul le scanner local, après vérification de
chaque contenu, peut produire la preuve. Les fichiers pré-matérialisés ne sont
jamais supprimés par le plan de contrôle ; leur cycle de vie reste à
l'orchestrateur hors service.

Le code de sortie de la preuve agrégée vérifie aussi que les comptes `CLEARED`
et `QUARANTINED` forment exactement le périmètre scanné. Aucun résumé
auto-déclaré incohérent ne peut donc rendre le gate vert.
