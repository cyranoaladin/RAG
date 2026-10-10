# Pin indépendant de la cible staging publique — lot #325

État au 2026-10-10 : **préparé, non approuvé, non activable**. La branche de
développement part de `origin/main` `b08c4def985af1a5d471402f80537387a661106d`.
Aucune cible staging, base ou production n'a été modifiée. Aucun pin de cible
réelle ni digest d'autorité n'a été émis.

`scripts/go_live/independent_staging_target_pin.py` sépare trois opérations :

1. `capture` observe en lecture seule l'hôte, son machine-id haché, un conteneur
   Docker courant, le `system_identifier` et le nom de la base PostgreSQL
   atteinte, ainsi que le realpath, le device et l'inode de destination.
   Une adresse PostgreSQL native
   de l'hôte, une socket ou un autre conteneur sont refusés. La capture produit
   un JSON canonique de validité maximale 24 h, explicitement **non approuvé**.
   Le parent de sortie doit exister, sans symlink ; la création utilise
   `O_NOFOLLOW|O_EXCL` et refuse aussi un symlink cassé.
2. Le JSON doit être commité sous `governance/staging_target_pins/*.json` dans
   une PR soumise à la review GitHub canonique `trusted_human_review_github`.
   La review `abenrhouma` doit porter sur le base/head/challenge exacts et son
   HEAD doit contenir les octets du pin. La capture ou le bundle C/V2 ne peuvent
   s'auto-approuver.
3. `verify` relit la cible live, le blob Git du HEAD et la review GitHub. Il ne
   sort `EXPECTED_TARGET_PIN_SHA256` qu'après l'ensemble des contrôles. Ce
   digest est l'entrée attendue du signer avant émission d'une clé ou signature
   staging. Le transfert V1 doit être observé après `pinned_at_utc`; cette garde
   relève du module V2/C et n'est pas contournée ici.

La fenêtre courte implique un nouveau pin, un nouveau HEAD et une nouvelle
review si elle expire. Une approbation d'un ancien HEAD ou d'un autre chemin
de destination n'est pas réutilisable. La vérification dépend de GitHub live ;
son indisponibilité laisse le pin refusé. Après fusion,
`historical_staging_target_pin_receipt.py` construit puis rejoue un reçu
historique. Il reconstitue uniquement le statut OPEN et le `base_sha` de
l'exécution trusted pré-fusion pour appliquer le vérificateur canonique ; le
reste provient de GitHub actuel. La review, son ID, son challenge, le statut
trusted réussi avant merge, le run et sa tentative, le tree
approuvé/fusionné, le blob du pin au HEAD approuvé et dans le `main` actuel
sont tous relus. Le parent du squash merge doit être le `base_sha` historique
qui portait le challenge : une avancée B2 de `main`, même vide et sans changement
de tree, invalide donc le reçu. Le `main` du checkout doit coïncider avec le
`main` GitHub live et descendre du merge. La cible hôte/Docker/PostgreSQL et
son device/inode sont relus enfin, y compris après les appels GitHub avant
émission du digest. Les fonctions d'identité SQL sont qualifiées par
`pg_catalog` et la connexion force un search_path sûr.
Le reçu seul reste explicitement hors autorité de publication.

Vérification locale sur fixtures synthétiques : 100 tests ciblés passent,
`ruff` passe.
Les sabotages couvrent digest, ancre A, hôte, machine-id, conteneur, base,
chemin, symlink, expiration, review/HEAD/base/challenge et blob substitué. Ce
résultat ne vaut pas qualification d'une cible réelle. Le test d'intégration
Git crée une histoire approuvée→fusionnée→main avancé ; le rejeu conserve le
`base_sha` historique lié au run même si l'API PR expose une base ultérieure.
Les cinq sabotages de la contre-revue initiale sont couverts : expiration
après GitHub, search_path usurpé, squash merge avec B2 vide, remplacement de
répertoire au même realpath et symlink cassé sur la sortie.

Compatibilité à intégrer dans #325 avant usage : le pin V1 n'a jamais été émis,
mais son schéma gagne `destination_device` et `destination_inode`. Le parseur
du transfert qualifié V2 et la vérification C doivent accepter et comparer
ces champs ; l'ancien parseur doit rester rouge tant que cette mise à jour
n'est pas fusionnée. `target_identity=docker:<64hex>` ne change pas.

Prochaines conditions factuelles : cible staging finale créée et identifiée,
DSN read-only vers son PostgreSQL conteneurisé disponible par variable
d'environnement, pin capturé sur cet hôte, blob commité, review exacte validée
sur GitHub, puis vérification live avant V1/V2 et signature. Aucune identité
observée historique ne doit être réutilisée.
