# Rapport Codex — Lot 14B : réintégration des garde-fous AGENTS

## Objectif

Corriger le point bloquant du rapport d'audit lot 14 : la nouvelle version de
`AGENTS.md` avait remplacé l'ancien contenu au lieu de conserver les garde-fous
historiques.

## Problème corrigé

`AGENTS.md` conserve maintenant les apports agent-ready du lot 14 tout en
réintégrant les règles historiques sur les schémas, taxonomies, documents
sources, idempotence, ledger, scraping, droits, visibilité, LLM et livraison de
module.

## Fichiers modifiés

- `AGENTS.md`
- `docs/contracts/invariants.yml`
- `tests/unit/test_project_contracts.py`
- `data/reports/codex_lot_14B_agents_guardrails_fix.md`

## Garde-fous réintégrés

- `schema/document.py` ne doit pas être modifié sans tâche dédiée.
- Le schéma documentaire ne doit pas être dupliqué.
- Les évolutions de schéma exigent tests et compatibilité ou migration.
- Les taxonomies officielles déjà validées ne doivent pas être modifiées à la main.
- Les notions inconnues doivent aller en proposition.
- Les documents sources et `data/raw/` sont immuables.
- Le retraitement dépend des hashes.
- Les doublons vectoriels pour un même `chunk_id` sont interdits.
- Le ledger reste la source de vérité de l'état pipeline.
- Scraping massif, non limité ou contournant `robots.txt` et authentification interdit.
- `rights`, `visibility`, `rights=unknown` et ressources propriétaires sont encadrés.
- Le LLM n'est pas une source de vérité finale et ses sorties critiques doivent être validées.
- Les modules livrés doivent avoir tests, logs structurés, gestion d'erreur, reprise, rapport et documentation lorsque pertinent.

## Tests ajoutés ou modifiés

- `tests/unit/test_project_contracts.py`
  - vérifie les garde-fous historiques dans `AGENTS.md` ;
  - vérifie les invariants critiques dans `docs/contracts/invariants.yml`.

## Tests exécutés

- `python3 -m pytest tests/unit/test_project_contracts.py -q`
- `make doctor`
- `make project-doctor`
- `make test`
- `git diff --stat HEAD`
- `git diff --name-status HEAD`
- `git status --short --branch`
- recherche de fichiers sensibles par `find`

## Résultats

- Tests ciblés : 9 passed.
- `make doctor` : OK.
- `make project-doctor` : OK.
- `make test` : 276 passed.
- Recherche de fichiers sensibles : aucun résultat.

## Risques restants

- Aucun risque bloquant identifié sur le micro-lot 14B.
- Le lot 14 reste globalement à valider par les commandes finales complètes.

## Verdict

COMMIT_RECOMMANDÉ
