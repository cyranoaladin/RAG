# Lot 2026-10-10 — reçu de l'approbation exacte du candidat #312

## Portée

La PR #312 a été fusionnée dans `main` à `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`. Son HEAD approuvé est `6eab012c0c763fe73302c3a40e9646c42b5d213f`, tree `93e9f382fb12bd49ee3489056e0536f4d66c1976`, sur la base `2b1f3b04cf84defc7f828da6f3362df7677e8ca3`. La review `APPROVED` de `abenrhouma` porte l'identifiant `5479062236` et a été soumise le 10 octobre 2026 à 13:11:44 UTC. Le statut `trusted-human-review/head-pinned=success` du HEAD a été créé à 13:12:57 UTC, avant la fusion à 13:13:43 UTC.

Le reçu `pr312_candidate_approval.json` lie ces identités aux SHA-256 des 17 fichiers versionnés du candidat : agrégat, registre d'artefacts, registre de release, trois registres de proposition et onze subjects. Le vérificateur relit GitHub et le workflow officiel, sa tentative `pull_request_target` réussie, le HEAD et les blobs Git de chaque fichier approuvé. Une modification ultérieure des octets ne peut pas emprunter l'approbation #312 en recalculant simplement le reçu.

La release liée reste `student-public-20261010-v1-eb39f6cd0423e184`, avec 11 collections, 253 artefacts textuels, 377 placements et 3 975 chunks. Son agrégat a le SHA-256 `28bd14dd114d8369e8c6520774bfbd1e8ba966b85aeaaf2d58e27b2c23d9fcfc`. Le reçu confirme `candidate`, `NOT_PROMOTABLE`, `NO_PRODUCTION_ACTIVATION` et `PRE_REVIEW` ; il n'autorise aucune publication.

## Preuves du lot

Le worktree isolé provient du `main` frais `fc6b7da6254eb67e7a2b26ec555b5edf17316a96`. La suite de référence #300 était verte au départ : `12 passed`. Les nouveaux tests ont d'abord échoué sur le vérificateur absent, puis sur le contrôle absent des blobs du HEAD approuvé. Ils couvrent les écarts de HEAD, reviewer, challenge, statut, horaires, tree, merge, digests, population et substitution postérieure d'un fichier dans un vrai dépôt Git jetable.

Après implémentation, `python -m pytest -q scripts/tests/test_pr312_authority_receipt.py scripts/tests/test_pr300_authority_receipt.py` rend `37 passed`. L'appel live `check_pr312_authority(Path.cwd())` sur ce checkout rend `PR312_AUTHORITY_APPROVAL_PASS=true`, `CANDIDATE_ACTIVATION_ALLOWED=false` et les comptes 11/253/377/3975. Le contrôle ne dépend ni de `audit.md`, ni d'un environnement staging ou production. Aucun déploiement ni écriture hors du worktree de ce lot n'a été effectué.

## Limite

Ce reçu prouve l'approbation exacte du **candidat #312**. Il ne transforme pas ses registres `CANDIDATE_NOT_AUTHORIZED` en autorisations LOT41A, ne produit pas de nouveaux profils ou scopes publics opérationnels et ne satisfait pas la revue batch LOT42 d'une future release successeur.
