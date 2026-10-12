# ADR-0074 — Readiness signée pour les consommateurs C/A2

## Contexte

Le signataire de publication peut rejouer les autorités externes C (GitHub,
CAS privé, cible et base) avant de signer la readiness. Le wrapper Docker et
l'API ne disposent pas tous deux de ces accès. Les quatre digests A/C/pin du
manifeste V2 ne portaient ni la fin de validité du verdict C ni le binding
exact de la revue LOT42 nécessaire au contrôle des 377 attestations en base.
Les consommateurs restaient donc fermés malgré une signature valide.
L'heure d'émission du manifeste est prise avant le rejeu live ; elle ne peut
pas dater rétroactivement les observations recueillies ensuite.

## Décision

Le contrat `nexus-contracts` passe de `0.27.0` à `0.28.0`. Pour le seul
successeur public, la readiness V2 signée exige trois champs additionnels :

- `public_successor_c_expires_at_utc`, repris de l'échéance du verdict C live ;
- `public_successor_c_verified_at_utc`, heure observée à la fin du rejeu C ;
- `public_successor_lot42_review_binding`, le tuple exact
  `(base_sha, head_sha, tree_sha, review_id, challenge, reviewer)` obtenu par
  le rejeu de la revue GitHub.

Le signataire les prend exclusivement du verdict typé produit après le rejeu
live. Ils ne proviennent ni d'une option CLI ni du bundle C déclaratif. Le
contrat impose tous les champs du successeur ensemble, une heure de rejeu UTC
entre l'émission et l'échéance (écart maximal d'une heure) et la forme exacte
du binding. Les manifests V2
historiques gardent leurs octets canoniques.

Au déploiement et dans l'API, les consommateurs revérifient la signature
Ed25519 avec l'ancre de readiness, les digests A/C/pin, l'échéance C et le
binding. Le lecteur C rejoue les pièces statiques à l'heure C signée :
c'est le moment où les captures C étaient fraîches. Il refuse si l'échéance
signée dépasse A2, le pin, les autorisations ou LOT42. La base, ses
révocations et les attestations LOT42 restent contrôlées à l'exécution ; le
cache API ne supprime pas ces lectures par requête.

## Limites et conséquences

Une signature ne constitue pas une observation live future. Après échéance,
le candidat refuse jusqu'à nouveau rejeu et nouvelle signature. Le chemin
générique `load_release_expectation` et le lecteur C sans preuve restent
fail-closed. Aucun ancien manifest V2 ne devient une autorité de publication
par compatibilité implicite. Aucun changement de scope, droits, contenu ou
population n'est autorisé par cette ADR.
