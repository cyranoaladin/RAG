# Lot 2026-10-12 — préadaptation C du successeur public A2

## Périmètre et résultat

Branche locale isolée `go-live/c-a2-main902e`, basée sur `origin/main=902e9d5c95d2d369f41a18324fa05038913499b4` (#327 fusionnée). Aucun push, aucune écriture staging/production ni écriture DB.

Le lecteur C distingue maintenant l'enveloppe historique V1 de `NEXUS_PUBLIC_SUCCESSOR_AUTHORITY_ENVELOPE_A2_V1`. V1 conserve son contrôle d'actualité A1. Le chemin A2 exige l'autorité A2 approuvée au SHA exact `5beccf115b3d23473dd310f20fdd6ce31cc8bc38e0cc23918d936300c1fec9b4`, une attestation d'émission, un pulse C distinct et postérieur couvrant les 253 sources et révocations, le paquet source #300, son approbation, un pin, un plan et un binding A2/pin/plan cohérents. Le vérificateur temporel existant impose au moins 24 heures résiduelles. Le set LOT41A du chemin A2 doit porter exactement les onze IDs `lot41a-student-public-*-v2` et les dates A2 ; les 377 liaisons et 253 contenus restent contrôlés par la projection A1.

Le refus final de `verify_public_successor_activation` **reste en place**. Les octets d'un bundle ne démontrent ni le rejeu des captures privées à C, ni les onze reviews signées de #327, ni l'état DB/LOT42, ni l'observation de cible live. `PUBLIC_SUCCESSOR_ACTIVATION_PASS=false` et `PUBLICATION_AUTHORIZED=false` dans ce lot. Le pin #327 expire le 2026-10-12 à 23:47:31.927082 UTC ; une opération ultérieure doit le renouveler si cette échéance est passée.

## Étapes restantes avant une levée gouvernée du refus

Le producteur d'enveloppe et le schéma de readiness n'acceptent encore que 21 autorités V1. Le signer PUBLICATION relance `verify_preissuance_authority` sur A1 et refuse après son expiration ; il inclut encore cette échéance A1 dans le minimum de validité. Il faut une enveloppe A2 versionnée à 26 champs, un rejeu privé indépendant du pulse C avec les 253 reçus, une validation complète des bindings de review LOT41A et des révocations, les contrôles live B/DB/transfert/LOT42, puis seulement la production d'un verdict typé C. Aucune preuve manquante n'est déduite de ce code.

## Vérification

Cycles TDD du delta initial : le test A2 expiré échouait sur `currentness expired` et le test d'attestation manquante échouait sur un autre champ avant l'adaptation ; ils passent maintenant. Le test des IDs V1 renouvelés échouait d'abord sur l'absence d'argument A2 ; il vérifie désormais le refus V1 et l'acceptation de structure V2, sans prétendre à des reviews réelles. Rejeu sur base `902e9d5` dans un venv propre dont les imports pointent vers ce worktree : `pytest packages/release-chain/tests -q` : 159 tests réussis. Ruff ciblé et `git diff --check` : verts. Mypy ciblé avec les imports externes non typés désactivés : aucune erreur.
