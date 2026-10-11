# Lot 2026-10-11 — nouvel ancrage de contenu étudiant A

## Portée et identité

Constat local au checkout propre issu de `origin/main` `25605df14773460c8cbed4d71150b50cc0939cec` (tree `d45d6af85c6a3ab93ec19f7f0b4b46af606f37fd`). Ce lot reconstruit un candidat **non activable** après expiration de l'actualité source de l'ancien ancrage. Il ne prolonge pas l'ancien A, n'émet aucun scope B, ne publie aucun PDF et ne modifie ni staging ni production. Les octets source, captures navigateur, reçus et PDF restent dans le CAS privé ; seuls les constats et manifests dérivés sont versionnés.

## Preuve fraîche

Le 11 octobre 2026, 15/15 pages de liste Éduscol ont été capturées par Chromium avec statut HTTP 200, sans capture manquante. Le contrôle de provenance a relu 315 identités et 383 URL PDF : 296 `EXACT_CURRENT_SOURCE` et 19 `SOURCE_UNPROVEN`. Les 253 sources effectivement incluses dans le candidat ont toutes une preuve d'identité exacte, d'actualité et de non-révocation. Le rapport [d'actualité](go_live/student_derivative_source_currentness_20261011.json) est daté `2026-10-11T14:05:36Z`, contient 253/253 `PASS` et possède le SHA-256 `76c68ea269f6031244d9f8824186abe0299f2810494e1d28b02e13cc4e2d912c`. Les 19 sources non prouvées ne sont pas incluses.

Le [constat d'inclusion](go_live/student_public_derivative_inclusions_20261011.json), SHA-256 `1f49b8d48fb40a979ec528d89bf46f711aeb7a71e1311d6fcc17869bc76b6edf`, relie 253 décisions, les 253 textes et PDF exacts, les reçus #300/#312, les captures fraîches, la revue PII et les preuves de source. Le CAS privé **nouveau et immuable** a un index SHA-256 `1ad82df91bfbc28a62a01f1c2dd5af45891d4035994206409e3d2ecee19c25d4` ; son emplacement est fourni hors Git par l'opérateur. Son contenu ne doit pas être remplacé sous cet index.

## Release préparatoire et pré-émission

La release `student-public-successor-20261010-40b956c6f5ec0c60` est dans `services/rag-pedago/data/releases/prerentree_2026_2027/profile_gate_student_public_successor_v1/release-40b956c6f5ec0c60/`. Le SHA-256 de son manifeste est `efc5c425189ec8ec83460aff2d3539401f3dbdba1dcde252187608276f65ec85`. Les comptes dérivés réels sont **11 collections, 253 artefacts textuels, 377 placements et 3 975 chunks**. Le manifeste garde `release_mode=candidate`, `promotion_status=NOT_PROMOTABLE` et `activation_status=NO_PRODUCTION_ACTIVATION` ; les onze scopes sont `NOT_ISSUED`.

L'[ancre A](go_live/student_public_successor_content_anchor_20261011.json) a le SHA-256 `1731e2a5690c4043dd21d02576d843f90dc90c7a2f7ec2cc736f7dd3563df7e0`. Le [checkpoint de pré-émission](go_live/student_public_successor_preissuance_checkpoint_20261011.json) a le SHA-256 `77bd2c0a3ce8c43148fa27315dfa2d37fb1f09917cdeef29f8ed2591a9a10f7e`. Son rejeu local a revérifié le CAS privé, les 253 inclusions, les autorités #300/#312 et les onze SHA de sujets : `preissuance_verified=true`, `publication_authorized=false`. **Expiration exacte : `2026-10-12T13:58:41.752000Z`**. À ou après cette heure, l'émetteur doit refuser ce candidat ; une nouvelle capture et un nouvel A seraient nécessaires.

## Vérification et suite gouvernée

Les quatre suites ciblées d'actualité, inclusion, construction de release et ancrage donnent **52 tests réussis**. Le test de rejeu historique a été isolé car son horloge réelle dépasse désormais l'expiration du candidat historique ; le correctif d'horloge appartient au lot technique #330. Le présent lot fixe aussi la sélection de ce test sur l'identité historique `release-fcc84331e7700042` pour éviter qu'une nouvelle release change le paquet testé. Ruff et `git diff --check` passent.

La politique et les noms de scope revus par #294 restent liés à l'ancien A. Ce nouveau contenu exige un **nouveau rebind versionné et une review exacte HEAD** avant toute émission B. Le merge d'A seul n'accorde ni visibilité élève ni autorisation de publication.
