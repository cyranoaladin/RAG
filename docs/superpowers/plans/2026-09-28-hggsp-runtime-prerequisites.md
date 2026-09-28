# Plan — prérequis runtime HGGSP

Base imposée : `26062eb1a1d7e8645a9a213fbf3de42ba88383fa`.
La spécification détaillée et l’autorisation du lot sont celles du message
opérateur du 28 septembre 2026. Le brouillon d’activation reste dans son
worktree distinct, sans push.

1. Écrire les contre-épreuves PostgreSQL jetables pour la sélection V4/V5,
   l’attestation gouvernée, les payloads forgés et la concurrence.
2. Ajouter le prédicat relationnel de release à la transaction de claim,
   préserver le mode historique sans filtre, puis câbler la release de la
   readiness au Worker B et son journal de démarrage.
3. Dériver les deux autorités de scopes HGGSP de la lignée successeur, du
   manifeste scellé, du registre mixte, des programmes et des politiques.
   Vérifier les refus croisés V4/V5 et l’identité octet pour octet des neuf
   scopes V4.
4. Exécuter les suites ciblées, PostgreSQL jetable, Ruff, mypy, scripts de
   qualification et gardes de gouvernance. Corriger toute régression du lot.
5. Consigner les preuves et la frontière des images dans le rapport du lot,
   puis créer une PR des prérequis runtime. Aucun build de provenance et
   aucune opération serveur pendant ce lot.

Après fusion, l’action suivante sera un nouveau run
`.github/workflows/production-image-provenance.yml` sur le nouveau `main`.
