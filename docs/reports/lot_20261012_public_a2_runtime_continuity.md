# LOT — Continuité A2 aux frontières de readiness et workers publics

Base de travail : `origin/main` à `902e9d5c95d2d369f41a18324fa05038913499b4` ; worktree et environnement Python isolés. Ce lot ne modifie ni droits, ni scopes, ni corpus, ni base de données. Il ne signe aucune readiness et ne lance aucun worker.

## Changement

La release publique 40b a une ancre A1 immuable dont l'actualité a expiré. Le reçu A2 approuvé conserve la population A1 mais renouvelle son autorité temporelle. La readiness INGESTION rejoue toujours l'ancre, le reçu de préémission, le CAS privé et les revues ; elle exige désormais A2 pour cette ancre et scelle son SHA dans `public_successor_phase_authority_digest`. Worker A relit les octets A2 exacts avant toute opération en base et refuse leur absence, leur substitution, un chemin symbolique ou leur expiration. Les anciennes releases gardent leur vérification A1.

Le signer PUBLICATION rejoue A2 avec le même contrôle CAS et la chaîne C, et borne sa validité à l'expiration A2. Worker B n'accepte le remplacement de la date A1 expirée que sous un verdict C typé, dont l'enveloppe vérifiée nomme le SHA exact d'A2. Les contrôles de population, droits, PII, placement, transfert et révocation de C restent requis. L'expiration de l'autorité de droits chargée est le minimum de C et d'A2.

## Vérification locale

- Rouge TDD observé pour l'absence d'A2 aux phases INGESTION et PUBLICATION, pour Worker B après A1, puis pour l'acceptation d'un lien symbolique au signer ; vert après correction.
- `pytest` ciblé sur les deux suites de préémission/scopes et cinq modules de signer, Worker A, Worker B et A2 : **69 tests passés**.
- `ruff check` sur les huit fichiers Python modifiés : **vert**.
- `mypy services/rag-engine/src` : **7 erreurs** dans `pedagogical_chunker.py`, `retrieval_scope_v2.py`, `backend/deps.py`, `embedding_provider.py` et `ingestor/api.py`, tous non modifiés par ce lot ; aucune erreur signalée dans les fichiers modifiés. La commande globale reste rouge.
- `git diff --check` : **vert**.

## Prérequis d'exécution distincts

Ce correctif ne vaut pas autorisation de transfert ni de publication. Avant INGESTION, la cible DB et les 253 dérivés transférés doivent être vérifiés, puis la readiness doit être signée sur le commit `main` exact et une image Worker A disponible par digest. Le contrôle `propose-release-batch-review` de LOT42 lit encore les anciens chemins de sidecars et ne sait pas construire la revue des 377 placements de cette release publique ; il exige une adaptation ciblée séparée. Le vérificateur C doit être finalisé pour l'enveloppe A2 et le rejeu sémantique complet avant le signer PUBLICATION et Worker B. Une image Worker B par digest et une revue LOT42 valide restent obligatoires. Aucun de ces gates n'a été déclaré vert par ce lot.

## Fournisseur C live — complément du même lot

Le signer PUBLICATION reçoit désormais des racines privées explicites pour le pulse C et les 11 bindings LOT41A, puis rejoue les 253 reçus source, les pièces signées de chaque autorisation, la revue exacte LOT42 sur PR ouverte, le pin et le transfert sur la cible, ainsi que les 11 autorisations et 377 attestations de la DB en lecture seule. Le fournisseur ne retourne au vérificateur C que les identités et comptes réellement relus. La commande de signature de production expose les mêmes entrées privées ; aucun chemin local n'est versionné dans le code ou le manifeste. Le contrôle DB distingue désormais le tree SHA de la PR et le blob SHA des octets de la revue LOT42.

Les tests signer/DB/production ciblés comptent **166 passes** et les tests C/LOT41A **78 passes** sur ce checkout. Ruff et `git diff --check` sont verts pour les fichiers modifiés. Le lot reste non déployé et non signé. La preuve C complète reste fermée avant une PR LOT42 revue sur son HEAD exact, l'enregistrement des 377 attestations et l'intégration du contrat de readiness C signé ; aucun résultat de ces opérations n'est simulé par les tests.

Après fusion éventuelle de LOT42, le signer n'accepte pas un simple SHA ni une review devenue invisible sur PR fermée. Le routage dépend de l'état GitHub observé : PR ouverte et review HEAD exacte, ou PR fusionnée avec reçu historique canonique. Ce reçu est généré seulement après merge, puis rejoue GitHub, le challenge, le statut et le run trusted antérieurs à la fusion, le tree Git, le blob revu et le même blob sur `main`. Dans les deux cas, le fournisseur C compare ensuite les 377 attestations et les faits DB à A2 et au reçu batch. Aucun reçu réel n'a été généré par ce lot.
