# Suite d'acceptation retrieval des dérivés publics — préparation du 10 octobre 2026

## Verdict et autorité des données

Préparé à **2026-10-10T14:06:26Z** depuis un worktree propre de `origin/main=fc6b7da6254eb67e7a2b26ec555b5edf17316a96` (arbre `93e9f382fb12bd49ee3489056e0536f4d66c1976`). Le candidat #312 a été lu en local, sans déploiement ni accès en écriture à staging ou production.

`PUBLIC_DERIVATIVE_ACCEPTANCE_SUITE=PREPARED` et **`QUALITY_PASS=false`**. Le manifeste #312 `eb39f6cd0423e184e0932196770ee7ffeb24d1aecb915a526ccad67206a11d17` décrit 253 dérivés, 377 placements et 11 collections, mais reste `PRE_REVIEW_NOT_PROMOTABLE`. Le manifeste préparatoire observé en lecture seule sur la branche candidate #313 (`fd40f452c3cba3138c8fa0a6578a1ec8a06de1b3`) a le SHA `28bd14dd114d8369e8c6520774bfbd1e8ba966b85aeaaf2d58e27b2c23d9fcfc`, 3 975 chunks et `promotion_status=NOT_PROMOTABLE`. Il **n'est pas** lié comme release finale dans la suite.

La fixture [public_derivative_acceptance_prepared_20261010.json](../../services/rag-engine/tests/fixtures/public_derivative_acceptance_prepared_20261010.json) a le SHA-256 `330413b3866bbc47caad5f3cc22e55079a73aaae01d9d551709fecdb6bfc5a79`. Ses 11 sources attendues sont des `derivative_content_sha256`, jamais les SHA des PDF sources. Les 11 identités figurent dans le candidat #312 et, au moment de la lecture, dans le registre candidat #313 avec au moins un chunk chacune. Les questions restent un **oracle préparé**, sans résultat HTTP mesuré sur le successeur.

## Choix de suite et seuils fixés avant mesure

Chaque collection possède trois requêtes positives (`factual`, `no_accent`, `notion`), une requête frontière empruntée à une autre collection, une requête sans réponse attendue et un refus de scope mal apparié. Les cas positifs sont réservés à l'identité signée `student` : la politique cible #313 est `target_policy.roles=[student]`, et le contrat V3 vérifie ce rôle. Une identité `teacher` doit donc recevoir HTTP 403 sur chacun de ces 11 scopes publics. Le cas frontière étudiant peut être vide mais ne peut jamais rendre une autre collection. Une sonde dense exhaustive doit rendre les comptes d'overflow ANN visibles sur les 11 collections; un tie overflow comptabilisé n'est pas maquillé en miss.

| Mesure finale | Seuil figé |
| --- | ---: |
| Positifs non vides, student | 33/33 |
| Hits de la source dérivée attendue, student | ≥26/33 et ≥2/3 par collection |
| Refus teacher sur les scopes student-only | 11/11 HTTP 403 |
| Zéros attendus, student | 11/11 |
| Frontières sans résultat hors scope, student | 11/11 |
| Refus des scopes mal appariés, student | 11/11 HTTP 403 |
| Résultats hors scope, citations manquantes, misses denses | 0 chacun |
| Collections avec compte explicite de tie overflow | 11/11 |

L'oracle de citation impose `source_uri`, `source_label`, `source_updated_at`, `licensor`, `licence_id` et `derivative_notice`, ainsi que la page et le `content_sha256` du dérivé dans la réponse finale. La fixture référence ces six champs depuis le candidat #312; le contrôle HTTP et DB de la page sera exécuté uniquement sur la release finale. Les seuils seront conservés pour cette mesure : tout échec ouvrira un diagnostic, pas une révision rétrospective du budget.

Les 11 thèmes positifs sont : place de l'Union européenne (DGEMC), puissance et conflits (HGGSP), rhétorique et servitude volontaire (HLP), dictionnaires et graphes (NSI), marché concurrentiel et chômage (SES), information génétique et domestication des plantes (SVT). DGEMC remplace l'ancienne requête sur la Constitution, dont le PDF attendu n'est pas dans le corpus dérivé; HLP terminale évite d'utiliser comme oracle un extrait tiers d'Hannah Arendt. Ces questions sont opposables par le SHA dérivé et la citation de la fixture, **sous réserve** de la mesure sur les passages finaux : la présence de la source dans le registre ne prouve pas encore que le passage attendu sera remonté.

## Garde-fou et preuves locales

Le vérificateur [public_derivative_retrieval_suite.py](../../scripts/go_live/public_derivative_retrieval_suite.py) refuse une collection manquante, un ancien SHA PDF à la place d'un dérivé, un digest #312 divergent, une citation incomplète, une requête `no_accent` accentuée, un accès enseignant positif ou un seuil modifié. Son contrôle de sonde dense exige l'identité du manifeste final, le checkout exact, une fraîcheur de six heures au plus, tous les chunks de chaque scope, zéro miss et une équation `rappel_a_5 + manques + refus_egalite = chunks` par collection. Ce contrôle de sonde est **une fonction préparatoire pure**, pas une mesure live. Les tests ont été exécutés en TDD, puis **17 tests verts** après correction du rôle et du gate de promotion; `ruff check` vert.

```bash
python -m pytest -q scripts/tests/test_public_derivative_retrieval_suite.py
python -m ruff check scripts/go_live/public_derivative_retrieval_suite.py scripts/tests/test_public_derivative_retrieval_suite.py
python scripts/go_live/public_derivative_retrieval_suite.py
python scripts/go_live/public_derivative_retrieval_suite.py --assert-bound  # exit 1 attendu actuellement
```

La suite V4/V5 `final_v4_v5_acceptance.json` et son runner `final_retrieval_acceptance.py` ne peuvent être repris tels quels : ils exigent deux manifests **internal**, les SHA des PDF, les citations `officiel_public` et 11 refus `student=403`. Leur architecture de contrôle (identité de contenu, chunks/pages, citations, sonde dense et rapprochement SQL en lecture seule) est la référence à adapter pour le successeur public; aucune sortie verte de cette ancienne suite ne vaut `QUALITY_PASS` pour les dérivés.

## Blocage volontaire avant qualification finale

Les cinq liaisons finales de la fixture restent `null` : chemin et SHA du manifeste successeur **promu**, chemin et SHA du registre de scopes publics, SHA du checkout final. `--assert-bound` échoue donc. Même si ces cinq champs étaient remplis, il **échouerait encore** : le vérificateur canonique `nexus_release_chain.release_readiness.load_release_expectation` accepte actuellement l'autorité publique #312 en mode `candidate`, pas une promotion par simple changement de statuts; aucune vérification canonique exacte des scopes, du checkout, des reviews et de l'état DB/HTTP n'est intégrée ici. La fonction `require_final_binding` refuse par construction toute affirmation finale, au lieu de traiter des hashes et statuts auto-déclarés comme des preuves.

La revue P1 a montré que l'ancien contrôle structurel acceptait un registre de scopes `{}`, un placement DGEMC vers un artefact d'une autre collection et un `final_checkout_sha` au bon format mais non vérifié. Trois tests de sabotage avec release synthétique complète ont reproduit ces acceptations avant correction; ils échouent désormais fermement au gate d'autorité. Il faudra d'abord resceller la release gouvernée avec autorisations `public`, mettre à jour le vérificateur canonique pour son successeur promu, vérifier les identités exactes de scopes et de checkout, puis adapter l'exécuteur HTTP/DB du harnais historique pour vérifier le succès étudiant, le refus enseignant, les six champs de citation et la page réelle. Ensuite seulement : sonde dense complète sur la même base, recherche directe et BFF sur les 11 collections, zéros/frontières/refus, et calcul des seuils ci-dessus. L'absence de ces preuves maintient `QUALITY_PASS=false` et `STAGING_FINAL_PASS=false`.

Un **E2E enseignant positif** reste une exigence distincte du go-live initial, mais il ne peut être exécuté sur les scopes `student` de #313. Il réclame une autorité de scope et un déploiement distincts qui incluent explicitement `teacher` dans `target_policy.roles`, suivis des mêmes contrôles de citation et de refus. Cette autorité n'est pas présumée par le présent lot; `TEACHER_POSITIVE_E2E_PASS` reste non établi.

## Avancement de #315 après intégration de #313 et #316

À **2026-10-10T15:54:54Z**, la branche de #315 a fusionné sans réécriture le `origin/main=b93c83a0031946fae72e0d519ef42a10befa2fea` courant. Le commit de fusion local est `6290c87c5acc7300e24916eefd310f4a65c47fd8` (arbre `885e9b9abea8c8b8a5e19e735e8bd8cbef5ea7b5`). Le venv du worktree n'installe en éditable que `packages/contracts` de ce même checkout.

Le runner préparatoire vérifie désormais, dans deux fonctions pures, une réponse `RetrievalResponse` publique contre un index **à fournir après vérification indépendante** du manifeste final, puis ses lignes SQL de lecture seule. Sur chaque hit, il exige la collection, le SHA du dérivé distinct du PDF, le placement, le chunk et sa page, la revue, le type textuel, les six champs d'attribution exacts, le droit de citation et la concordance de l'oracle préparé. Le rapprochement DB exige le même couple chunk/placement, la visibilité `public`, l'état actif/revu, l'actualité et `is_text_derivative=true`; il refuse les lignes absentes, dupliquées ou excédentaires. Ces fonctions ne créent aucune preuve de cible réelle et n'exécutent aucune requête HTTP ou SQL.

Le test TDD a d'abord échoué sur l'absence du validateur, puis sur la nouvelle liaison de l'oracle, une citation d'index malformée et la filiation PDF manquante d'un second résultat. Après implémentation, **31 tests** ciblés et Ruff passent. Les sabotages couvrent notamment identité PDF, scope étranger, chunk inconnu, citation absente ou modifiée, source PDF de l'oracle changée, type PDF et visibilité DB `internal`. `--assert-bound` reste volontairement rouge : l'autorité externe de la release promue, le registre de scopes final, la preuve DB/HTTP, la sonde dense et les seuils de qualité des 11 collections ne sont pas établis. Il serait incorrect de publier `QUALITY_PASS=true` à partir de ces tests de logique.

## Vérification réelle des manifests préparatoires après #318

Après synchronisation normale avec `origin/main=8b82b7c233a42762becf8080423e52efa844a635`, une lecture locale a appelé `nexus_release_chain.release_readiness.load_release_expectation` sur le manifeste préparatoire #313, lié de l'extérieur au SHA-256 `abb563fbd2623bc8dc3c73597a68c313fa9dc0291bcc335b7d18ec06e133bd44`. L'index préparatoire lu possède le SHA-256 `34bbf66ef8f2196ad66a84a4bee6bdf43ec232cd6bddcc29c146b97cf536f9e9`; le registre d'artefacts concorde avec le digest scellé de cet index. Les 11 identités attendues par la suite #315 existent chacune dans les placements de leur collection, et leurs SHA source PDF, type textuel, six champs de citation et pages concordent avec le registre d'artefacts. Le paquet lu contient 11 collections, 253 artefacts, 377 placements et 3 975 chunks.

Cette preuve concerne **uniquement les fichiers préparatoires immuables**. Le même manifeste déclare `promotion_status=NOT_PROMOTABLE`, `activation_status=NO_PRODUCTION_ACTIVATION`, et les 11 scopes proposés restent `NOT_ISSUED`. Aucune mesure HTTP, DB ou sonde dense sur une release publique finale n'existe dans ce contrôle ; `QUALITY_PASS=false` et `--assert-bound` demeure rouge. La CI standard du HEAD publié `50026c8609ca581c420ff284f7348cbbde3b7545` était encore en cours au moment de cette lecture (autres jobs verts, `services/rag-engine` en cours). Le commit de synchronisation et cette précision documentaire nécessitent une nouvelle CI avant toute conclusion de branche.

## Rejeu sur le paquet successeur V2 #323

À **2026-10-10T20:35:20Z**, la branche a intégré le `origin/main=b08c4def985af1a5d471402f80537387a661106d` courant, puis relu le paquet #323 depuis ce checkout. La suite reste `PREPARED_UNBOUND` ; ses seuils ci-dessus sont inchangés. Elle est maintenant liée à l'index V2 `bd1f714594ca17dbbe7d3cfdf255c8c270003c63bd4d267971a17b2afdb08ca4` et au manifeste successeur `b79246ff356b919aeb3dcb7f640a1a554e338899128a7c5acdcfaa9b7bcb1c78` de `student-public-successor-20261010-fcc84331e7700042`, ainsi qu'à la population exacte **11 collections / 253 artefacts / 377 placements / 3 975 chunks**. Le SHA-256 de la fixture mise à jour est `3d876dde1a14afd316131ad6de3fef22f3142d6f9b84061666f02ba8b8bd23df`.

Le validateur lit en totalité l'index, le manifeste, le registre de 253 artefacts, les 11 manifests matière et les 11 profils. Il vérifie leurs empreintes liées, l'état `PREPARATION_ONLY_NOT_ACTIVABLE`, les 11 scopes `NOT_ISSUED`, les 377 placements et 3 975 chunks déclarés. Pour **chacun des 33 cas positifs**, il trouve le SHA du dérivé dans le registre et dans la collection prévue, avec la filiation au PDF source, le type textuel, au moins un chunk et les six champs de citation attendus. Une substitution de manifeste #313, un digest d'index ou de manifeste changé, un nombre de chunks altéré, un artefact d'une autre collection, et la modification physique de l'index, du registre, d'un manifeste matière ou d'un profil rendent le contrôle rouge.

Dans un venv neuf n'installant `nexus-contracts` en éditable que depuis ce worktree, **40 tests ciblés** passent et Ruff 0.6.9 est vert. La commande préparatoire donne `PUBLIC_DERIVATIVE_ACCEPTANCE_SUITE=PREPARED QUALITY_PASS=false FINAL_BINDING=false`; `--assert-bound` retourne le code 1 attendu. Le manifeste #323 demeure `NOT_PROMOTABLE`, `PRE_REVIEW`, `NO_PRODUCTION_ACTIVATION`. Les scopes publics définitifs, la release C, le staging final, les réponses HTTP/DB et la sonde dense live sont absents de cette mesure. Aucune qualité retrieval finale, aucun résultat student/teacher et aucun `QUALITY_PASS=true` ne sont revendiqués.

## Corrections de revue de la recette préparée

À **2026-10-10T20:42:56Z**, une revue indépendante a relevé que le contrôle HTTP réclamait à tort `citation.rights=officiel_public`, droit de l'ancien corpus PDF. Le contrôle des dérivés #323 attend désormais strictement `public_allowed` ; les tests refusent explicitement `officiel_public`, `usage_interne` et une valeur inconnue. Le rapprochement DB conserve ce droit exact dans les enregistrements comparés.

Le SHA-256 de la fixture d'oracle `3d876dde1a14afd316131ad6de3fef22f3142d6f9b84061666f02ba8b8bd23df` est maintenant une constante vérifiée **avant** de lire ses 33 questions. Les sabotages d'un octet blanc et d'une question montrent que `load_draft_suite` devient rouge même lorsque le JSON reste valide et que la population #323 ne change pas. Toute future mesure finale devra lier son rapport à cette même empreinte ou faire approuver un nouvel oracle avant mesure. Les seuils sont inchangés et `QUALITY_PASS=false` demeure le verdict de ce lot.
