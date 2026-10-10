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
