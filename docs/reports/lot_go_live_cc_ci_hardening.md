# Lot CC — La CI exécute enfin les épreuves de refus des vérificateurs

- Lot : `LOT_GO_LIVE_FINAL_CC_CI_HARDENING_RUN_ALL_SCRIPT_TESTS`
- Branche : `go-live/ci-run-all-script-tests`
- Décision : `GO_LIVE_CC_CI_HARDENING_PR_OPEN`
- Aucun compteur modifié, aucun blocker fermé, aucun garde-fou retiré : un garde-fou **ajouté**.

## L'écart

La CI GitHub nommait ses épreuves `scripts/tests/` une à une et n'en retenait qu'une
(`test_readiness_artifacts_coherence.py`). Tout le reste ne tournait qu'en local : les tests de refus des vérificateurs
de blocages (`test_qualification_blockers_producer.py` — C2 à C6, ROLLBACK, COCKPIT_E2E, CONCURRENCE, SYNC_INCREMENTALE,
STAGING_EXTERNE), le gate de readiness (`test_go_live_readiness.py`), les dispositions de PR, le dossier et la feuille de
décision PII. Une PR pouvait donc affaiblir un vérificateur fail-closed sans qu'aucun check ne rougisse.

## Le correctif

- Nouveau job CI `scripts/tests` : `python -m pytest -q scripts/tests/`, Python 3.11, sans secret, sans Docker, sans réseau.
  Dépendances : `pytest`, `PyYAML`, `psycopg[binary]`, et les trois paquets locaux.
- `fetch-depth: 0` : `test_open_pr_dispositions` vérifie qu'un SHA cité existe dans l'historique ; en clone superficiel il
  échouait **à tort**. L'épreuve n'est pas affaiblie, c'est le clone qui est complété.
- `pytest -q scripts/qualification/tests` est conservé tel quel, de même que l'épreuve nommée du job `repository controls`.
- Même cible ajoutée à `scripts/ci-local.sh` (`script-tests`), pour que CI locale et CI GitHub disent la même chose.

## Preuve avant de pousser

Simulation de l'environnement GitHub : `git clone --depth 1`, venv neuf, dépendances ci-dessus →
`1 failed, 536 passed, 7 skipped` ; l'unique échec est celui que `fetch-depth: 0` corrige (objet git absent du clone
superficiel). Dans le dépôt complet : tout vert. Gardes de topologie rejoués et verts : `test-ci-local-topology.sh`,
`test-ci-local-failsafe.sh`, `test-main-protection-policy.py`, `test-trusted-human-review-workflow.py`.

## Limite à connaître

Le job existe et rougit une PR fautive, mais il ne devient **bloquant au merge** que s'il est ajouté aux checks requis de
la protection de `main` — réglage du dépôt, hors de ce lot et de ma portée.

## Readiness

Inchangé : `GO_LIVE_READY=false`, `--assert-ready=1`, `go_live_qualification_blockers=4`, `pii_undecided=149`,
`release_promoted_refused_contents=26`, `current_switch=0`, `production_db_writes=0`, `production_deployments=0`.
