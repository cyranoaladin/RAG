# Rapport de lot — LOT44e : jobs, scheduler/worker CLI, câblage best-effort `/ingest/v2`

- **Branche** : `lot-44d-ingestion-agents` (réutilisée, HEAD initial LOT44b `30fec2805e411a59e483ee3cb480ac55d6fc01a2`).
- **Commits locaux, aucun push** : `f444d94` (LOT44d, 23 fichiers), `7da6d3d` (LOT44e Phase 1, 7 fichiers), plus la présente passe (Phase 2, détaillée ci-dessous, non encore committée au moment de la rédaction — cf. section clôture).
- **Verdicts LOT44c** — republiés inchangés, non rouverts par ce lot :

```
LOT44C_BLOCKED_MISSING_APPROVED_PRODUCTION_PROFILE_MATRIX
LOT44C_BLOCKED
PRODUCTION_BLOCKED_NO_PRODUCTION_PROFILES
GATE_NOT_CONNECTED_TO_PRODUCTION_ENTRYPOINT
NOT_READY_FOR_PRODUCTION
```

La production reste strictement bloquée.

## Objet

Fermeture de la dette FK `workflow_events.job_id` (Phase 1), puis propagation réelle de `job_id` dans les huit stages LOT44d, scheduler/worker CLI déterministe, protection contre un worker périmé, et câblage best-effort de `/ingest/v2` (Phase 2). Détail des décisions : ADR-0027 (LOT44d, non modifié), ADR-0028 (cette passe).

## Phase 1 — jobs table et primitives (rappel, déjà acceptée comme livraison technique)

- Migration additive `004_jobs.sql` : table `ingestion_control.jobs` + FK `workflow_events.job_id_fkey`.
- `ingestion_control/jobs.py` (nouveau) : `create_job`, `claim_job`, `complete_job`, `record_job_retry`, `reap_expired_job_leases`.
- 3 modifications minimales de fichiers LOT44b existants (bootstrap, provisioning, suite de régression de concurrence).
- Commit local `7da6d3d`, 13 tests d'intégration PostgreSQL réels à l'époque.

## Phase 2 — propagation, scheduler/worker, câblage `/ingest/v2`

### Fichiers créés

```
services/rag-engine/src/ingestor/ingestion_control/provisioning.py
services/rag-engine/src/ingestor/ingestion_worker/__init__.py
services/rag-engine/src/ingestor/ingestion_worker/runner.py
services/rag-engine/src/ingestor/ingestion_worker/storage.py
services/rag-engine/src/ingestor/ingestion_worker/cli.py
services/rag-engine/src/ingestor/ingestion_worker/ingest_v2_bridge.py
services/rag-engine/tests/test_lot44e_ingest_v2_bridge.py
services/rag-engine/tests/integration/test_lot44e_worker_e2e.py
services/rag-engine/tests/integration/test_lot44e_ingest_v2_bridge.py
docs/adr/ADR-0028-scheduler-worker-et-cablage-ingest-v2-lot44e.md
docs/reports/lot_44e_scheduler_worker_ingest_v2.md
```

### Fichiers modifiés

```
services/rag-engine/src/ingestor/ingestion_agents/transitions.py     (job_id optionnel)
services/rag-engine/src/ingestor/ingestion_agents/scout.py           (job_id propagé)
services/rag-engine/src/ingestor/ingestion_agents/fetcher.py         (job_id propagé, 2 transitions)
services/rag-engine/src/ingestor/ingestion_agents/extractor.py       (job_id propagé)
services/rag-engine/src/ingestor/ingestion_agents/classifier.py      (job_id propagé)
services/rag-engine/src/ingestor/ingestion_agents/rights_agent.py    (job_id propagé)
services/rag-engine/src/ingestor/ingestion_agents/quality_agent.py   (job_id propagé)
services/rag-engine/src/ingestor/ingestion_control/jobs.py           (record_job_retry exige lease_token)
services/rag-engine/src/ingestor/ingest_v2_endpoint.py               (LOT43 — câblage best-effort, 2 points d'appel)
services/rag-engine/tests/test_lot44d_transitions.py                 (test job_id mis à jour)
services/rag-engine/tests/test_lot44d_scout.py                       (+ tests job_id)
services/rag-engine/tests/test_lot44d_fetcher.py                     (+ test job_id)
services/rag-engine/tests/test_lot44d_extractor.py                   (+ test job_id)
services/rag-engine/tests/test_lot44d_classifier.py                  (+ test job_id)
services/rag-engine/tests/test_lot44d_rights_agent.py                (+ test job_id)
services/rag-engine/tests/test_lot44d_quality_agent.py               (+ test job_id)
services/rag-engine/tests/integration/test_lot44e_jobs_control.py    (lease_token requis + 2 tests concurrence explicites)
```

**Les 12 fichiers LOT44c non suivis n'ont nécessité aucune modification dans cette passe.**

## Contraintes impératives — respectées

1. **PostgreSQL reste seul source de vérité** : aucun ledger SQLite créé ni touché par ce lot (recherche : aucune référence SQLite dans les fichiers de cette passe).
2. **`job_id` unique propagé de bout en bout** : preuve directe, `test_lot44e_worker_e2e.py::test_full_chain_reaches_quality_checked_with_consistent_job_id` — tous les événements `workflow_events` d'une exécution complète portent le même `job_id`.
3. **Aucun `job_id` artificiel** : jamais généré par `apply_resource_transition`/le worker — toujours celui de `claim_job`. Échec best-effort de `/ingest/v2` observable (log structuré `logger.warning(..., exc_info=True)`, jamais une prétention de suivi non réelle) — prouvé par 5 tests unitaires (`test_lot44e_ingest_v2_bridge.py`).
4. **Protection worker périmé, testée explicitement** : faille réelle trouvée (`record_job_retry` sans garde de bail en Phase 1) et corrigée ; 2 tests d'intégration rejouent le scénario complet claim A → expiration → reap → claim B → rejet de A.
5. **Transitions toujours validation puis CAS** : aucun stage n'écrit `resource_state` directement — inchangé depuis LOT44d, revérifié.
6. **`ROUTED` non inventé, non persisté** : inchangé depuis LOT44d (ADR-0027, Décision 3) — non rouvert.
7. **Aucun profil/manifest/fingerprint de production, aucun fallback** : le pont `/ingest/v2` tague chaque job d'un `profile_version` non résolu par construction (`unspecified_legacy_ingest_v2`) — jamais un profil réel ni un contournement.
8. **Gate LOT44c non contourné** : `select_profile`/`validate_scope_against_profile` appelés tels quels dans le worker, jamais enrobés.
9. **Comportement externe de `/ingest/v2` préservé** : prouvé par test HTTP réel (`TestIngestV2HttpEndpointCreatesJobWithoutChangingResponse`) — réponse identique, aucune clé ajoutée ; 43 tests LOT43 préexistants toujours verts inchangés.
10. **12 fichiers LOT44c non modifiés** : confirmé (aucun dans les listes ci-dessus).

## Tests — commandes exactes, comptes, codes de sortie

### Suite ciblée LOT44d/44e

```
$ cd /home/alaeddine/Bureau/RAG/services/rag-engine
$ PYTHONPATH=src .venv/bin/python -m pytest \
    tests/test_lot44d_*.py tests/test_lot44e_ingest_v2_bridge.py \
    tests/integration/test_lot44e_jobs_control.py tests/integration/test_lot44e_worker_e2e.py \
    tests/integration/test_lot44e_ingest_v2_bridge.py tests/integration/test_lot44d_chain_wiring.py \
    --collect-only -q
tests/integration/test_lot44d_chain_wiring.py: 1
tests/integration/test_lot44e_ingest_v2_bridge.py: 2
tests/integration/test_lot44e_jobs_control.py: 15
tests/integration/test_lot44e_worker_e2e.py: 4
tests/test_lot44d_classifier.py: 7
tests/test_lot44d_coverage_agent.py: 5
tests/test_lot44d_extractor.py: 8
tests/test_lot44d_fetcher.py: 5
tests/test_lot44d_planner.py: 7
tests/test_lot44d_quality_agent.py: 8
tests/test_lot44d_rights_agent.py: 8
tests/test_lot44d_scout.py: 8
tests/test_lot44d_transitions.py: 5
tests/test_lot44e_ingest_v2_bridge.py: 5
```
Total : 88 tests (62 LOT44d + 26 LOT44e), tous exécutés et verts (rejoué fichier par fichier pendant l'implémentation ; réexécution groupée ci-dessous).

### Régression complète non-intégration

```
$ PYTHONPATH=src .venv/bin/python -m pytest -q -m "not integration"
$ echo "EXIT=$?"
EXIT=0
```
Zéro `F`/`FAILED`/`ERROR` dans la sortie.

### Intégration complète (tout `tests/integration/`)

```
$ PYTHONPATH=src .venv/bin/python -m pytest tests/integration/ -v
...
================== 116 passed, 9 skipped, 1 warning in 56.56s ==================
```
9 skips pré-existants (modèles d'embedding non disponibles dans cet environnement, `test_pgvector.py`/`test_retrieval_script.py`) — sans lien avec ce lot.

### Lint et typecheck

```
$ .venv/bin/python -m ruff check .
All checks passed!
$ .venv/bin/python -m mypy src
Success: no issues found in 76 source files
```

## Réserves et hors périmètre (ADR-0028)

- `/drive` non câblé au pont best-effort.
- Aucune reprise multi-claims d'un job partiellement traité (pas de persistance `resource_candidates`/`artifacts`).
- Worker CLI non déployé (aucune référence dans `docker-compose.v2.yml`/`api.py`, vérifié).
- `profile_version` du pont `/ingest/v2` toujours non résolu par construction — cohérent avec le blocage LOT44c, pas un défaut à corriger silencieusement.

## Verdict

```
LOT44E_PHASE2_READY_FOR_REVIEW
```

Jobs, scheduler/worker CLI, propagation `job_id`, protection worker périmé et câblage best-effort `/ingest/v2` livrés et vérifiés (88 tests dédiés + 116 tests d'intégration globaux, lint/typecheck propres, comportement externe de `/ingest/v2` prouvé inchangé). Verdicts LOT44c ci-dessus inchangés — production toujours strictement bloquée. Aucun commit, push, PR, merge ou déploiement dans cette passe au-delà des sauvegardes locales déjà autorisées.
