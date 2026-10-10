# Suite d'acceptation retrieval des dérivés publics — préparation du 10 octobre 2026

## Verdict et autorité des données

Préparé à **2026-10-10T14:06:26Z** depuis un worktree propre de `origin/main=fc6b7da6254eb67e7a2b26ec555b5edf17316a96` (arbre `93e9f382fb12bd49ee3489056e0536f4d66c1976`). Le candidat #312 a été lu en local, sans déploiement ni accès en écriture à staging ou production.

`PUBLIC_DERIVATIVE_ACCEPTANCE_SUITE=PREPARED` et **`QUALITY_PASS=false`**. Le manifeste #312 `eb39f6cd0423e184e0932196770ee7ffeb24d1aecb915a526ccad67206a11d17` décrit 253 dérivés, 377 placements et 11 collections, mais reste `PRE_REVIEW_NOT_PROMOTABLE`. Le manifeste préparatoire observé en lecture seule sur la branche candidate #313 (`fd40f452c3cba3138c8fa0a6578a1ec8a06de1b3`) a le SHA `28bd14dd114d8369e8c6520774bfbd1e8ba966b85aeaaf2d58e27b2c23d9fcfc`, 3 975 chunks et `promotion_status=NOT_PROMOTABLE`. Il **n'est pas** lié comme release finale dans la suite.

La fixture [public_derivative_acceptance_prepared_20261010.json](../../services/rag-engine/tests/fixtures/public_derivative_acceptance_prepared_20261010.json) a le SHA-256 `c87783c3a43fbfe57248ba3b8db21fe078ac55c489172c31b217ed0ea06d84e5`. Ses 11 sources attendues sont des `derivative_content_sha256`, jamais les SHA des PDF sources. Les 11 identités figurent dans le candidat #312 et, au moment de la lecture, dans le registre candidat #313 avec au moins un chunk chacune. Les questions restent un **oracle préparé**, sans résultat HTTP mesuré sur le successeur.

## Choix de suite et seuils fixés avant mesure

Chaque collection possède trois requêtes positives (`factual`, `no_accent`, `notion`), une requête frontière empruntée à une autre collection, une requête sans réponse attendue et un refus de scope mal apparié. Les cas positifs doivent être rejoués pour les identités signées `student` **et** `teacher`. Le cas frontière peut être vide mais ne peut jamais rendre une autre collection. Une sonde dense exhaustive doit rendre les comptes d'overflow ANN visibles sur les 11 collections; un tie overflow comptabilisé n'est pas maquillé en miss.

| Mesure finale | Seuil figé |
| --- | ---: |
| Positifs non vides, teacher | 33/33 |
| Positifs non vides, student | 33/33 |
| Hits de la source dérivée attendue, par rôle | ≥26/33 et ≥2/3 par collection |
| Zéros attendus, deux rôles | 22/22 |
| Frontières sans résultat hors scope, deux rôles | 22/22 |
| Refus des scopes mal appariés, deux rôles | 22/22 HTTP 403 |
| Résultats hors scope, citations manquantes, misses denses | 0 chacun |
| Collections avec compte explicite de tie overflow | 11/11 |

L'oracle de citation impose `source_uri`, `source_label`, `source_updated_at`, `licensor`, `licence_id` et `derivative_notice`, ainsi que la page et le `content_sha256` du dérivé dans la réponse finale. La fixture référence ces six champs depuis le candidat #312; le contrôle HTTP et DB de la page sera exécuté uniquement sur la release finale. Les seuils seront conservés pour cette mesure : tout échec ouvrira un diagnostic, pas une révision rétrospective du budget.

Les 11 thèmes positifs sont : place de l'Union européenne (DGEMC), puissance et conflits (HGGSP), rhétorique et servitude volontaire (HLP), dictionnaires et graphes (NSI), marché concurrentiel et chômage (SES), information génétique et domestication des plantes (SVT). DGEMC remplace l'ancienne requête sur la Constitution, dont le PDF attendu n'est pas dans le corpus dérivé; HLP terminale évite d'utiliser comme oracle un extrait tiers d'Hannah Arendt. Ces questions sont opposables par le SHA dérivé et la citation de la fixture, **sous réserve** de la mesure sur les passages finaux : la présence de la source dans le registre ne prouve pas encore que le passage attendu sera remonté.

## Garde-fou et preuves locales

Le vérificateur [public_derivative_retrieval_suite.py](../../scripts/go_live/public_derivative_retrieval_suite.py) refuse une collection manquante, un ancien SHA PDF à la place d'un dérivé, un digest #312 divergent, une citation incomplète, une requête `no_accent` accentuée ou un seuil modifié. Il refuse aussi une promotion déclarative avec un registre d'artefacts substitué. Le contrôle de sonde dense exige l'identité du manifeste final, le checkout exact, une fraîcheur de six heures au plus, tous les chunks de chaque scope, zéro miss et une équation `rappel_a_5 + manques + refus_egalite = chunks` par collection. Les tests ont été exécutés en TDD : test absent d'abord rouge, puis **12 tests verts** après implémentation; `ruff check` vert.

```bash
python -m pytest -q scripts/tests/test_public_derivative_retrieval_suite.py
python -m ruff check scripts/go_live/public_derivative_retrieval_suite.py scripts/tests/test_public_derivative_retrieval_suite.py
python scripts/go_live/public_derivative_retrieval_suite.py
python scripts/go_live/public_derivative_retrieval_suite.py --assert-bound  # exit 1 attendu actuellement
```

La suite V4/V5 `final_v4_v5_acceptance.json` et son runner `final_retrieval_acceptance.py` ne peuvent être repris tels quels : ils exigent deux manifests **internal**, les SHA des PDF, les citations `officiel_public` et 11 refus `student=403`. Leur architecture de contrôle (identité de contenu, chunks/pages, citations, sonde dense et rapprochement SQL en lecture seule) est la référence à adapter pour le successeur public; aucune sortie verte de cette ancienne suite ne vaut `QUALITY_PASS` pour les dérivés.

## Blocage volontaire avant qualification finale

Les cinq liaisons finales de la fixture restent `null` : chemin et SHA du manifeste successeur **promu**, chemin et SHA du registre de scopes publics, SHA du checkout final. `--assert-bound` échoue donc. Le contrôle de liaison existant reste structurel; il ne produit aucun verdict de qualité HTTP. Il faudra d'abord resceller la release gouvernée avec autorisations `public`, revoir les identités de scope finales et les digests, puis adapter l'exécuteur HTTP/DB du harnais historique pour vérifier les deux rôles, les six champs de citation et la page réelle. Ensuite seulement : sonde dense complète sur la même base, recherche directe et BFF sur les 11 collections, zéros/frontières/refus, et calcul des seuils ci-dessus. L'absence de ces preuves maintient `QUALITY_PASS=false` et `STAGING_FINAL_PASS=false`.
