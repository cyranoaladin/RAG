# Lot Cockpit — Recherche étudiante mono-matière

Date UTC : 2026-10-10. Base de travail : `origin/main` `84c05e0041b17e59f2b0f99a69193352a8d9dab0`, arbre `070bd8f8a5f875df16d2db487833538c3e505d98`. Worktree et `npm ci` isolés.

## Décision et résultat

Le produit V1 est la recherche pédagogique avec passages cités. Le verrou `answer_generation_allowed=false` reste en place (ADR-0012, ADR-0037, ADR-0069). Une requête `role=student` à `POST /api/search` doit contenir exactement une collection, même si l'identité signée porte plusieurs matières. Le BFF ne réécrit ni la portée signée ni le contrat canonique : il refuse une requête à deux collections avant la readiness et avant tout appel moteur. Les autres rôles conservent le comportement multi-collections existant ; l'interface choisit le sélecteur simple ou multiple selon la capacité calculée par le BFF à partir du rôle signé. La valeur par défaut de cette capacité est `false`.

Le BFF vérifie que chaque hit renvoyé appartient à la collection demandée pour son appel moteur. Un hit sans collection ou attribué à une autre collection entraîne `502 invalid_upstream_response`, sans exposition du passage. `GET /api/collections` ne présente que l'intersection entre le catalogue moteur et les collections autorisées par l'identité signée, et renvoie `multiCollectionAllowed=false` pour l'étudiant, `true` pour l'enseignant. `POST /api/chat` reste authentifié et contrôle le scope, puis renvoie `503 answer_generation_disabled` sans appel `/chat` au moteur. Le bouton conversationnel a été retiré ; le sélecteur multiple reste disponible pour les rôles non étudiants. Aucun endpoint de writer ou d'ingestion n'a été ajouté.

Ces contrôles BFF sont une défense supplémentaire. Ils ne substituent pas les scopes serveur, la visibilité `public` gouvernée, le contrôle de droits ou l'acceptance E2E sur le corpus final.

## Cycle de vie des PR historiques

La PR #293 est un harnais E2E pour le BFF signé. Elle reste **OPEN** : son exécution live et son closure-check dépendent des scopes et placements publics finaux ainsi que du SHA du BFF réellement déployé. La fermer ou la fusionner sur ses anciens identifiants V4/V5 internes serait prématuré ; elle doit être réconciliée avec la release publique successeur et la présente route avant son test final. La PR #294 contient une projection ancienne de onze scopes V4/V5 `internal` et un changement Cockpit plus large. La présente PR n'autorise ni la fusion de #294 telle quelle ni sa fermeture mécanique : ses scopes et son protocole de signature doivent être rebâtis sur les subject SHA de la release publique finale. Le conflit technique éventuel sur `/api/chat` et l'UI sera résolu lors de ce rebase.

## Vérification locale

- Red TDD observé : refus multi-collections étudiant, refus hit hors collection, fermeture `/api/chat`, interface à sélection unique et catalogue borné ont échoué sur le code antérieur avant l'implémentation.
- `npm ci --no-audit --no-fund` : exit 0.
- `npm test -- --run` : 200 tests verts, 1 ignoré (24 fichiers verts, 1 ignoré).
- `npm run lint`, `npm run typecheck`, `npm run contracts:check`, `npm run build` : exit 0.
- `npm audit --omit=dev --json` : high=0, critical=0, moderate=0, exit 0 au moment du contrôle.

La première CI du HEAD `0677a19d9e33b4b1921ce7a356908a1bd39d392c` a échoué dans `scripts/tests` : 1 échec, 990 succès et 47 tests ignorés. L'échec est préexistant à ce lot (fixture introduit par le commit `2b1f3b04`) et indépendant du BFF : deux reçus de SHA distincts ont partagé le même préfixe CAS à deux caractères, puis le test a tenté `mkdir` une seconde fois sans `exist_ok`. Une exécution avec horloge figée au `2026-10-10T15:00:12Z` a reproduit exactement `FileExistsError` avant le correctif et a réussi après. Le seul correctif est `exist_ok=True` sur ce dossier de fixture ; le moteur de droits reste inchangé. Dans le venv Python propre avec racine privée volontairement absente comme en CI, `pytest -q scripts/tests/` donne 992 succès, 46 ignorés. Sur le HEAD corrigé `e58222137f27359f82e7f8ac16b0cab25f2ad9c7`, la CI standard distante a ensuite réussi ses 14 jobs ; seul `trusted-human-review/head-pinned` reste rouge faute de review sur le HEAD exact.

## Réconciliation après fusion de #313

`origin/main` a été relu à `829bc9acec1eeb17dc9800389c92102b6f2c2297` puis intégré sans réécriture de l'historique de #318. Le merge n'a créé aucun conflit. Le commentaire de revue sur la régression de l'interface enseignante a été reproduit par un test rouge, puis corrigé en conservant le sélecteur multiple des rôles non étudiants sur preuve du BFF. Sur ce socle, `npm test -- --run` confirme 202 tests verts et 1 ignoré ; `npm run lint`, `npm run typecheck`, `npm run contracts:check` et `npm run build` sortent à 0. Cette vérification reste locale jusqu'à la CI distante du nouveau HEAD ; elle ne constitue ni un E2E étudiant sur le staging final ni une autorisation de déploiement.

Aucun staging ni production n'a été muté. La preuve HTTP Cockpit → API v2 avec scope public final n'est pas produite dans ce lot ; le verdict `STUDENT_E2E_PASS` reste `false` jusqu'au staging final.
