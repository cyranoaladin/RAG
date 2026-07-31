# LOT 39 — Harnais d'évaluation du retrieval

Date : 2026-07-31
Branche : `lot-39-eval-harness`
Base : `main@00d7c39`
Statut de reprise : **candidat isolé et validé**

## Audit de reprise

Le harnais a été extrait d'un worktree qui mélangeait les lots 38 à 40. LOT38
étant bloqué par une transition de gouvernance incohérente, cette branche repart
de `main` : le code d'évaluation ne dépend pas du changement de contrat LOT38.

Les deux fichiers golden, la baseline et le garde de couverture retrouvés dans
le stash ne sont pas inclus dans ce lot. Leur état ne permet pas de reproduire
les affirmations historiques de 205 requêtes et de métriques de référence. Ils
appartiennent au LOT39bis, qui devra les reconstruire et les valider sur tout
leur périmètre avant toute publication de résultat.

## Périmètre exact

- `.gitignore`
- `services/rag-engine/Makefile`
- `services/rag-engine/eval/metrics.py`
- `services/rag-engine/eval/run_eval.py`
- `services/rag-engine/eval/golden/SCHEMA.md`
- `services/rag-engine/tests/test_eval_harness.py`
- `docs/reports/lot_39_eval_harness.md`

Aucun endpoint, golden actif, baseline ou garde CI n'est modifié dans LOT39.

## Comportement visé

- charger des requêtes dorées YAML conformes au schéma documenté ;
- calculer Recall@5/10/20, nDCG@10, MRR, taux de fuite, complétude des
  citations, taux de réponse vide et latences p50/p95 ;
- évaluer le chemin de retrieval v2 sans le modifier ;
- offrir un fallback lexical PostgreSQL explicite via `--offline-fallback` ;
- produire un rapport JSON et, sur demande explicite, une baseline ;
- exposer le harnais par `make eval`.

Les sorties `eval/*.json` sont des artefacts runtime ignorés par Git.

## Corrections validées par tests ciblés

- nDCG conserve la position des résultats non pertinents et des doublons ; un
  chunk répété reçoit un gain nul sans faire remonter les résultats suivants.
- Recall/MRR ignorent les grades non positifs ou non finis.
- Le loader YAML refuse les niveaux/collections incohérents, les fichiers vides,
  les grades invalides, les suites sans jugement et l'absence du champ négatif.
- Le gate refuse les tolérances et métriques non finies, ainsi que toute
  divergence de taille, configuration ou mode nominal/fallback.
- Une empreinte SHA-256 canonique couvre IDs, requêtes, collections, niveaux et
  jugements ; deux suites différentes de même taille ne partagent plus une
  baseline silencieusement.
- `top_k` est au minimum 20 lorsque Recall@20 est publié.
- Les deux chemins lexicaux PostgreSQL imposent un ordre total stable avant
  `LIMIT`, y compris à score FTS égal.
- Le mode de retrieval est sérialisé dans la configuration de résultat et de
  baseline, ce qui interdit une comparaison silencieuse nominal/fallback.
- La création d'une baseline valide les paramètres, les métriques et les
  invariants absolus avant toute écriture ; un résultat avec nDCG nul, fuite ou
  citation incomplète est refusé.
- `--sweep --offline-fallback` est refusé : le fallback lexical n'utilise pas le
  seuil de rerank et ne peut donc pas produire une calibration honnête.
- Les grades booléens YAML sont refusés comme non numériques.

Chaque correction comportementale ci-dessus a d'abord été reproduite par un
test rouge, puis vérifiée par le même test passé au vert.

## Vérifications

- Base `main` avant restauration : suite `pytest` non-intégration verte.
- Tests dédiés `tests/test_eval_harness.py` : `35 passed`.
- `PYTHONPATH=src:../../packages/contracts/src python -m pytest -o addopts='' -q -m 'not integration'` :
  `640 passed, 15 deselected`.
- `python -m ruff check .` : `All checks passed!`.
- `PYTHONPATH=src:../../packages/contracts/src python -m mypy src eval/metrics.py eval/run_eval.py` :
  `Success: no issues found in 42 source files`.
- `run_eval.py --help` : sortie CLI disponible sans accès PostgreSQL.
- `make help` expose la cible `eval`.
- `git check-ignore --no-index services/rag-engine/eval/probe.json` confirme
  l'exclusion des rapports JSON runtime.
- `detect-secrets scan` limité aux sept fichiers du lot : aucun résultat.
- `git diff --cached --check` : succès.
- Le périmètre ne contient aucun changement de `retrieval_v2_endpoint.py`.

## Limites assumées

- Aucune métrique retrieval ni mesure de latence n'est revendiquée dans LOT39 :
  PostgreSQL, les goldens actifs et la baseline relèvent de LOT39bis.
- Le fallback lexical sert à exécuter une évaluation sans modèle d'embedding ;
  ses résultats ne peuvent pas être présentés comme ceux du pipeline nominal.
- Le schéma fixe un objectif de 200 requêtes substantielles ou plus pour la suite
  complète, mais LOT39 ne prétend pas satisfaire cet objectif sans les données.

## Suite

- reconstruire ensuite LOT39bis séparément, avec goldens, baseline et garde
  exhaustif.
