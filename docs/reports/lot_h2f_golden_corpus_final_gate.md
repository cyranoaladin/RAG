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
La preuve PII scellée `1ea7655b4e390fa08916b3d4303a3424f3306e65a4149b9841c0f77aee773691`
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
répertoire borné `nexus-h2b-pii.*` de mode `0700`, sous la racine approuvée par
`--scratch-root` ou `NEXUS_H2_PII_SCRATCH_ROOT`. Son reçu non sensible ne
constitue pas une attestation PII : seul le scanner local, après vérification de
chaque contenu, peut produire la preuve. Les fichiers pré-matérialisés ne sont
jamais supprimés par le plan de contrôle ; leur cycle de vie reste à
l'orchestrateur hors service.

Le code de sortie de la preuve agrégée vérifie aussi que les comptes `CLEARED`
et `QUARANTINED` forment exactement le périmètre scanné. Aucun résumé
auto-déclaré incohérent ne peut donc rendre le gate vert.

La preuve historique a ensuite été régénérée avec ce scanner corrigé, sur un
miroir local borné dérivé des 64 chemins PDF autorisés par le manifeste. Le
nouveau sceau
`1ea7655b4e390fa08916b3d4303a3424f3306e65a4149b9841c0f77aee773691`
lie le manifeste canonique, le scanner `pii_scanner_h2b_v2` et la politique
PII. Le résultat réel reste 64/64 : 63 objets clairs, un objet en quarantaine,
zéro review, zéro échec d'extraction, zéro objet non scanné et zéro mismatch
SHA. Les liaisons H2-E et la readiness produit utilisent exclusivement ce
nouveau sceau ; l'ancienne preuve n'autorise plus la répétition finale.

La matérialisation Drive H2-E conserve `--immutable` et ajoute des retries
bornés ainsi qu'un timeout total de 1 800 secondes. Cette correction est
nécessaire parce que le téléchargement réel du manifeste dépassait la limite
historique de 300 secondes ; elle n'ajoute aucune opération d'écriture
distante et chaque objet reste vérifié par SHA-256 avant consommation.

## Revue automatisée du troisième correctif H2-F

La revue Codex sur `48378d3e862fb8615959629e80f1ce67103b8623` a
identifié trois succès silencieux. Le scanner refuse désormais un PDF
ouvert correctement mais sans aucun texte extractible, et il refuse toute la
politique si une regex configurée est invalide. Le gate de currentness compte
également comme erreur de périmètre une identité Eduscol déclarée par famille
ou URL mais placée hors du préfixe `01_EDUSCOL_OFFICIEL/`.

Ces corrections ont été éprouvées par des tests rouges puis verts. La preuve
PII réelle a été régénérée sur les 64 octets PDF vérifiés : son sceau est
`1ea7655b4e390fa08916b3d4303a3424f3306e65a4149b9841c0f77aee773691`,
avec 63 objets clairs, un en quarantaine et aucune extraction vide ou échouée
dans le périmètre autorisable.

## Revue automatisée du quatrième correctif H2-F

La revue Codex sur `60b9edd81766e3b58129cef5772c66bee78b40b5` a fermé
deux écarts supplémentaires. La transition produit 004 injecte désormais,
dans la même transaction que le schéma et son registre, une projection
rejouable des rôles runtime. Un volume existant à HEAD 003 reçoit donc les
droits `SELECT` du rôle de retrieval et les seuls droits `SELECT, INSERT` du
publisher sur les nouvelles relations ; aucun secret ne figure dans la ligne
de commande Docker. Le runner PostgreSQL réel construit un état 003 avec
rôles préexistants, applique 004, vérifie ces privilèges, puis rejoue tous les
cycles de rollback et de migration.

Le miroir PII ne dépend plus d'une racine absolue codée dans le programme. Le
scanner local et le matérialiseur opérateur partagent la même configuration
`NEXUS_H2_PII_SCRATCH_ROOT`, avec `--scratch-root` explicite et le répertoire
temporaire du système comme repli. Un miroir hors de cette racine est rejeté
avant transport ou lecture ; le répertoire dédié conserve son mode `0700` et
  sa garde de vacuité.

## Revue automatisée du cinquième correctif H2-F

La revue Codex sur `30801f3118f31b77f2a247c78d8a8154e805a42e` a
identifié trois écarts P2. Le compilateur applique désormais réellement les
`explicit_exclusions` du routage canonique, de façon prioritaire et avec leur
motif gouverné, au lieu de laisser ces règles déclaratives sans effet. Les
audiences des placements sont triées une seule fois pour l'identité canonique
comme pour leur projection PostgreSQL : une répétition avec le même ensemble
d'audiences dans un ordre différent reste donc idempotente.

Enfin, la répétition H2-E ne dépend plus de la chaîne littérale `/tmp`. Sa
racine est fournie par `--scratch-root` ou `NEXUS_H2E_SCRATCH_ROOT`, avec le
répertoire temporaire du système comme repli portable. Les contrôles existants
restent obligatoires : racine existante, enfant direct dédié, propriétaire
courant, mode `0700`, refus des liens symboliques et absence d'écrasement.

## Revue automatisée du sixième correctif H2-F

La revue Codex sur `f348ff84c929263a21781d14573c7d517368e709` a fermé
deux nouveaux périmètres vacuaires. Le scanner PII ne considère plus un PDF
mixte comme inspecté lorsqu'une seule page fournit du texte : toute page sans
texte extractible produit désormais l'échec explicite
`PDF_PAGE_TEXT_EXTRACTION_EMPTY`, avant toute décision `CLEARED`. Cette règle
reste distincte de l'échec d'un document entièrement vide.

Le validateur golden refuse aussi une spécification dont les trois listes de
contrôles sont vides, même lorsque son résumé déclare correctement zéro. Le
gate final exige donc au moins un contrôle exécutable avant de calculer un
verdict vert.

Le scan réel des 64 candidats a confirmé 61 objets clairs, un objet en
quarantaine et deux échecs page par page, tous deux hors du slice philosophie
approuvé. Son nouveau sceau est
`3db37e916250300f0a0d538fd924802f222ce3a8880b595971f3cf4ab2b29b87`.
Les liaisons H2-E et readiness utilisent ce sceau ; les deux objets non
inspectables restent `REVIEW_REQUIRED`.
