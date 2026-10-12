# ADR-0075 — Preuve C signée pour Worker B public en staging

## Contexte

Le signataire staging de la phase `PUBLICATION` rejoue C contre les autorités
live avant de signer. La readiness staging ne conservait cependant que les
digests A, enveloppe et pin. Worker B appelait ensuite le vérificateur portable
C sans `live_verifier` et sans readiness signée ; ce chemin est volontairement
fail-closed. La publication du successeur public était donc impossible, même
après un rejeu C réussi au moment de la signature.

La readiness V2 de production porte déjà l'heure, l'échéance et la liaison de
revue LOT42 du rejeu C (ADR-0074). Son ancre ne peut pas servir au staging.

## Décision

`nexus-contracts` passe de `0.28.0` à `0.29.0`. Pour la seule phase staging
`PUBLICATION`, la readiness V1 exige et signe trois faits pris du verdict C
rejoué en direct : `public_successor_c_verified_at_utc`,
`public_successor_c_expires_at_utc` et
`public_successor_lot42_review_binding`. Le temps du rejeu doit suivre
l'émission de moins d'une heure et précéder l'échéance. L'échéance du manifeste
ne peut dépasser celle de C. La phase `INGESTION` et les manifests historiques
gardent leurs octets canoniques ; ils ne peuvent porter ces faits.

Worker B relit les octets et l'ancre de la readiness déjà contrôlée par son
gate. En staging il vérifie aussi le digest explicitement épinglé ; en
production il utilise l'ancre gouvernée de production. Il passe ces preuves
au vérificateur portable C, qui valide signature, type, phase, liens A/C/pin,
fenêtre et binding avant de poursuivre. Aucun vérificateur live fictif ni
mode C sans preuve n'est ajouté. La vérification de la base, des révocations et
des attestations LOT42 reste obligatoire au runtime.

## Conséquences

Une ancienne readiness staging `PUBLICATION` dépourvue de ces champs échoue
fermée et doit être régénérée par le signataire après rejeu live. Le lot ne
modifie ni corpus, ni droit, ni scope, ni base, ni déploiement. Une signature
expirée impose un nouveau rejeu et une nouvelle signature.
