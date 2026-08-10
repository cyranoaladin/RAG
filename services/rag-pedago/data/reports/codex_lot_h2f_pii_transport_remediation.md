# Rapport Codex — Lot H2-F : transport PII et périmètre scellé

## Objectif

Cette remédiation ferme les quatre constats de la revue automatisée de PR #95
sur le gate PII, sans activer l'ingestion ni modifier l'autorité LOT41A-V2.
Le scanner H2-B de `rag-pedago` redevient une frontière locale sans transport
réseau : il reçoit un miroir borné, vérifie les octets, puis scanne uniquement
le périmètre PDF positif du manifest.

## Doctrine fail-closed

- Le transport Drive est une orchestration racine séparée ; le module du
  service n'importe ni `subprocess` ni client réseau.
- Le manifest local doit contenir les colonnes `path` et `sha256`, au moins un
  PDF, des chemins relatifs sûrs et des SHA-256 canoniques.
- Chaque fichier local doit exister et son SHA-256 observé doit égaler le SHA
  attendu avant l'extracteur. Un mismatch, un fichier absent ou un drift du
  scanner reste une erreur explicite et expurgée.
- Le CLI mono-fichier échoue sur PII ou extraction incomplète. Le CLI corpus
  échoue sans imprimer de chemin local lorsqu'un périmètre est invalide.
- Une preuve agrégée ne réussit que si le périmètre est non vide, entièrement
  scanné, sans erreur/review/mismatch, et si `CLEARED + QUARANTINED` égale le
  nombre scanné.

## Transport opérateur

`scripts/h2b_materialize_pii_mirror.py` accepte uniquement le remote canonique,
le SHA-256 exact du manifest et un répertoire vide `nexus-h2b-pii.*` de mode
`0700`, enfant de la racine fournie par `--scratch-root` ou
`NEXUS_H2_PII_SCRATCH_ROOT`. Le scanner utilise exactement la même racine.
Le matérialiseur exécute une seule copie `rclone`
lecture seule de la liste positive et ne publie qu'un reçu non sensible. Ce
reçu n'accorde aucune clearance : la décision demeure produite par le scan
local des octets vérifiés.

Le matérialiseur H2-E a également été déplacé sous `scripts/` à la racine afin
qu'aucun transport externe ne soit possédé par `services/rag-pedago/`.

## Vérifications

Les cycles TDD ont reproduit les échecs suivants avant correction : succès du
CLI après erreur d'extraction, périmètre vide accepté, SHA manifest mal formé,
octets locaux divergents remis à l'extracteur, transport `rclone` présent dans
le service et absence du matérialiseur racine.

Les vérifications ciblées, la CI complète, le corpus réel et les preuves H2-E
seront consignés sur le HEAD final. Aucun résultat d'un HEAD antérieur ne sera
présenté comme autorisant le nouveau code.

La revue automatisée suivante a fermé trois autres faux verts par TDD. Un PDF
dont toutes les pages sont dépourvues de texte extractible reste désormais en
échec explicite `PDF_TEXT_EXTRACTION_EMPTY`; une expression régulière invalide
rend toute la politique PII invalide au lieu d'être ignorée; enfin une ligne
qui se déclare Eduscol par sa famille ou son URL mais se trouve hors du préfixe
canonique est comptée dans le périmètre incomplet et bloque la currentness.

Le scan réel a été rejoué après ces changements sur les 64 PDF positifs
matérialisés en lecture seule. Le sceau
`1ea7655b4e390fa08916b3d4303a3424f3306e65a4149b9841c0f77aee773691`
conserve 64 objets scannés, 63 clairs, un en quarantaine et zéro échec
d'extraction, objet non scanné ou mismatch SHA-256.

Une revue ultérieure a supprimé le chemin temporaire absolu codé en dur. Des
tests prouvent qu'une racine approuvée non standard fonctionne pour le
matérialiseur comme pour le scanner, et qu'un miroir voisin mais hors racine
est refusé avant tout transport ou appel extracteur.

## Sécurité

Aucune base de production n'est visée. Aucun writer n'est activé. PR #96 reste
gelée et non approuvable. Aucun PDF réel, contenu PII, secret ou chemin absolu
machine-local n'est ajouté à Git.
