# Pin indépendant de la cible staging publique — lot #325

État au 2026-10-10 : **préparé, non approuvé, non activable**. La branche de
développement part de `origin/main` `b08c4def985af1a5d471402f80537387a661106d`.
Aucune cible staging, base ou production n'a été modifiée. Aucun pin de cible
réelle ni digest d'autorité n'a été émis.

`scripts/go_live/independent_staging_target_pin.py` sépare trois opérations :

1. `capture` observe en lecture seule l'hôte, son machine-id haché, un conteneur
   Docker courant, le `system_identifier` et le nom de la base PostgreSQL
   atteinte, ainsi que le realpath de destination. Une adresse PostgreSQL native
   de l'hôte, une socket ou un autre conteneur sont refusés. La capture produit
   un JSON canonique de validité maximale 24 h, explicitement **non approuvé**.
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
son indisponibilité laisse le pin refusé. La revue après merge devra utiliser
un reçu historique validé par le protocole de la PR, car le vérificateur
canonique live exige une PR ouverte. Cela doit être traité avant une signature
ou activation post-merge.

Vérification locale sur fixtures synthétiques : 20 tests passent, `ruff` passe.
Les sabotages couvrent digest, ancre A, hôte, machine-id, conteneur, base,
chemin, symlink, expiration, review/HEAD/base/challenge et blob substitué. Ce
résultat ne vaut pas qualification d'une cible réelle.

Prochaines conditions factuelles : cible staging finale créée et identifiée,
DSN read-only vers son PostgreSQL conteneurisé disponible par variable
d'environnement, pin capturé sur cet hôte, blob commité, review exacte validée
sur GitHub, puis vérification live avant V1/V2 et signature. Aucune identité
observée historique ne doit être réutilisée.
