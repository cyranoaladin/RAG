# ADR-0028 — Scheduler/worker CLI, propagation de job_id, câblage best-effort `/ingest/v2` (LOT44e)

- **Statut** : Accepté
- **Date** : 2026-08-04
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0025 (plan de contrôle PostgreSQL, LOT44b), ADR-0026 (profils et validation déterministe, LOT44c — « Contrat d'interface pour LOT44d et LOT44e »), ADR-0027 (stages déterministes, LOT44d)
- **Chronologie réelle de ce document** : rédigé après implémentation (jobs.py étendu, ingestion_worker/ créé, huit stages LOT44d propagent job_id, ingest_v2_endpoint.py câblé en best-effort), tous vérifiés verts (156 tests LOT44d/44e au total, unitaires et intégration réelle) avant rédaction.

## Contexte

LOT44e Phase 1 a livré `ingestion_control.jobs` (migration 004) et fermé la dette FK `workflow_events.job_id` (ADR-0026). Cette passe (« Phase 2 ») livre la partie active : propagation réelle de `job_id` dans les huit stages LOT44d, un scheduler/worker CLI déterministe, la protection contre un worker périmé, et le câblage best-effort de `/ingest/v2` — sans jamais activer la production (verdicts LOT44c inchangés, aucun profil/manifest/fingerprint créé).

## Décision 1 — `job_id` devient un paramètre optionnel de `apply_resource_transition`

`ingestion_agents/transitions.py::apply_resource_transition` et les six stages qui transitionnent (`Scout`, `Fetcher`, `Extractor`, `Classifier`, `RightsAgent`, `QualityAgent`) acceptent désormais `job_id: UUID | None = None`, transmis tel quel à `cas_transition` — jamais généré, jamais deviné. `Planner` et `CoverageAgent` n'écrivent aucune transition/événement : aucun paramètre `job_id` n'existe sur ces deux stages (rien à leur attacher). Rétrocompatible : un appelant qui omet `job_id` obtient exactement le comportement LOT44d original (`NULL`).

## Décision 2 — Protection contre un worker périmé : `record_job_retry` exige désormais un `lease_token`

Faille identifiée et corrigée avant toute mise en service : la version Phase 1 de `record_job_retry` mettait à jour un job **par `job_id` seul**, sans vérifier le bail — un worker A dont le bail a expiré (repris par un worker B après passage du reaper) aurait pu, en cas d'échec de son propre traitement, écraser silencieusement le job désormais détenu par B (le repasser à `queued`/`dead_letter` alors que B le croit toujours `running`).

**Correctif** : `record_job_retry` exige désormais `lease_token` et applique la même garde CAS que `complete_job` (`WHERE job_id = %s AND lease_token = %s AND status = 'running'`) — échec explicite (`JobLeaseConflictError`) si le bail ne correspond plus, jamais un écrasement silencieux. Prouvé par deux tests d'intégration PostgreSQL réels dédiés (`test_lot44e_jobs_control.py::test_stale_worker_cannot_record_retry_after_lease_reclaimed` et `::test_stale_worker_cannot_complete_after_lease_reclaimed`) qui rejouent le scénario complet : claim A → expiration → reap → claim B → tentative de A sur son ancien bail → rejet, job de B intact.

`run_worker_iteration` (``ingestion_worker/runner.py``) distingue explicitement trois issues : succès (`complete_job` réussit), échec métier normal (`record_job_retry` réussit, statut `retried`/`dead_letter`), et bail perdu (`JobLeaseConflictError` sur l'une ou l'autre — statut `lease_lost`, **aucune écriture supplémentaire tentée**).

## Décision 3 — Une itération de worker = un job = une chaîne complète

`run_worker_iteration` réclame **un** job (`claim_job`), et si `resource_id` est absent (soumission fraîche), crée la ressource (`ingestion_control/provisioning.py::create_resource`, nouveau fichier additif) puis exécute Scout → Fetcher → Extractor → Classifier → RightsAgent → QualityAgent dans une seule exécution continue, en propageant le **même** `job_id` à chaque transition — jamais une reprise par étapes séparées entre plusieurs claims (LOT44d n'a jamais persisté `ResourceCandidate`/`ArtifactRecord` dans `resource_candidates`/`artifacts`, seulement des transitions ; une reprise multi-claims aurait nécessité cette persistance, explicitement hors périmètre de cette passe).

Le moteur de validation LOT44c (`select_profile`/`validate_scope_against_profile`) est appelé **sans contournement** avant toute progression — un `profile_version` inconnu ou absent fait échouer le job explicitement (retry puis `dead_letter`), jamais une sélection silencieuse de secours.

`QUALITY_CHECKED -> ROUTED` reste non activée (héritage direct d'ADR-0027, Décision 3 — non rouvert ici).

## Décision 4 — `pii_detected`/`duplicate_detected` restent `False` en dur dans le worker

Aucun détecteur réel n'existe dans ce dépôt (cf. ADR-0027, Décision 5) : le worker ne fabrique aucune détection, il transmet toujours `False` — documenté explicitement dans `runner.py`, pas une omission silencieuse.

## Décision 5 — Câblage best-effort `/ingest/v2` : scope reconstruit à partir des defaults de déploiement déjà réels

`ingest_v2_endpoint.py` (LOT43, touché pour la première fois par ce lot) appelle, après chaque ingestion synchrone réussie (`/upload-files` et `/urls`), une fonction `_best_effort_track_job` qui délègue à `ingestion_worker/ingest_v2_bridge.py::best_effort_create_ingest_job` (nouveau module). Cette fonction :

- reconstruit `ResourceScope` à partir des champs réellement fournis par la requête (`collection`, `niveau`, `voie`, `matiere`, `audience`) et des **mêmes** valeurs par défaut de déploiement déjà utilisées par le pipeline v2 existant pour ses propres écritures réelles (`ingest_v2.py::_get_default_scope()` — `NEXUS_DEFAULT_TENANT`/`CANDIDAT`/`VISIBILITY`/`SCHOOL_YEAR`/`PROGRAMME_VERSION`) — jamais une valeur inventée pour ce pont ;
- échoue explicitement (retourne `None`, ne lève jamais) si le scope ne valide pas — réserve documentée : le vocabulaire libre de `voie` côté v2 (ex. `"gen"`) ne correspond pas toujours aux valeurs strictement énumérées de `nexus_contracts.document.Voie`, auquel cas aucun job n'est créé pour cette requête ;
- tague chaque job avec `profile_version = "unspecified_legacy_ingest_v2"` — un repère qui fera **toujours** échouer `select_profile` (LOT44c) si un jour un worker réclame ce job, tant qu'aucune convention réelle de `profile_version` n'existe pour le chemin `/ingest/v2` — jamais un profil fabriqué qui laisserait croire qu'une validation LOT44c a eu lieu ;
- ne crée **jamais** de `resource_id` à ce stade (seul le worker en crée une, lors d'un traitement réel — évite une double création si le job est un jour réclamé) ;
- est protégée par un double niveau de `try/except Exception` (import du pont + exécution), avec log structuré (`logger.warning(..., exc_info=True)`) à chaque échec — jamais une exception qui remonte à l'appelant HTTP.

**Comportement externe strictement préservé** — prouvé, pas seulement affirmé : `tests/integration/test_lot44e_ingest_v2_bridge.py::TestIngestV2HttpEndpointCreatesJobWithoutChangingResponse` appelle réellement `/ingest/v2/upload-files` via `TestClient`, vérifie `response.status_code == 200`, la forme exacte du corps de réponse (aucune clé `job_id` ajoutée), **et** qu'un job a réellement été créé dans PostgreSQL en parallèle. Les 43 tests LOT43 préexistants sur ce fichier (`test_ingest_v2.py`, `test_lot43_ingest_limits.py`, `test_ingestion_embedding_path_audit_contract.py`) passent inchangés — y compris un test HTTP réel qui exerce désormais silencieusement le nouveau chemin best-effort (sans DSN configuré dans cet environnement, il échoue et logue, sans toucher à la réponse).

## Décision 6 — Scheduler CLI volontairement simple, jamais lancé automatiquement

`python -m ingestor.ingestion_worker.cli` (`--profiles-dir`, `--artifact-store-dir`, `--owner`, `--once`/`--max-iterations`, `--poll-interval-s`) est un point d'entrée autonome. Le déterminisme réel réside dans `run_worker_iteration`, pas dans la boucle CLI elle-même (`time.sleep` entre itérations vides, jamais testée comme boucle infinie — seul `--once` est exercé). Aucune référence à ce module dans `api.py`/`docker-compose.v2.yml`/`Dockerfile.ingestor-v2` (vérifié) : ce worker n'est câblé à aucun déploiement réel par ce lot.

## Périmètre couvert

- Propagation `job_id` : 6 stages transitionnants + `apply_resource_transition`, 9 tests unitaires dédiés (un ou deux par stage), tous verts.
- `ingestion_control/jobs.py` étendu (`record_job_retry` avec garde de bail), `ingestion_control/provisioning.py` (nouveau : `create_ingestion_run`, `create_resource`).
- `ingestion_worker/` (nouveau package) : `storage.py` (stockage fichier réel), `runner.py` (itération déterministe), `cli.py` (point d'entrée autonome), `ingest_v2_bridge.py` (pont best-effort).
- 15 tests d'intégration PostgreSQL réels sur `jobs.py` (dont 2 scénarios de concurrence explicites worker-périmé), 4 tests E2E réels (`test_lot44e_worker_e2e.py` : chaîne complète + job_id cohérent sur tous les événements + retry/backoff réel + aucun job disponible), 5 tests unitaires + 2 tests d'intégration sur le pont `/ingest/v2` (dont 1 HTTP réel).
- `ingest_v2_endpoint.py` (LOT43) : 2 points d'appel ajoutés (`/upload-files`, `/urls`), aucune autre ligne modifiée ; `/drive` non câblé dans cette passe (hors périmètre explicite, à traiter par un lot ultérieur si besoin).

## Hors périmètre de cette passe (réserves explicites)

- `/drive` (`ingest_v2_endpoint.py`) non câblé au pont best-effort.
- Aucune reprise multi-claims d'un job partiellement traité (`ResourceCandidate`/`ArtifactRecord` non persistés en base par LOT44d) — une itération de worker traite un job du début à la fin ou échoue entièrement (retry complet).
- Aucun déploiement du worker CLI dans `docker-compose.v2.yml`/Kubernetes — reste un outil invocable manuellement.
- `QUALITY_CHECKED -> ROUTED` toujours non activée.
- Aucun profil/manifest/fingerprint de production — le registre LOT44c n'est chargé que depuis des répertoires temporaires dans tous les tests de ce lot.

## Verdicts LOT44c — republiés inchangés (non rouverts par ce lot)

```
LOT44C_BLOCKED_MISSING_APPROVED_PRODUCTION_PROFILE_MATRIX
LOT44C_BLOCKED
PRODUCTION_BLOCKED_NO_PRODUCTION_PROFILES
GATE_NOT_CONNECTED_TO_PRODUCTION_ENTRYPOINT
NOT_READY_FOR_PRODUCTION
```

La production reste strictement bloquée — un job créé par le pont best-effort `/ingest/v2` ne peut, par construction, jamais franchir la sélection de profil LOT44c (`profile_version` toujours `"unspecified_legacy_ingest_v2"`, jamais résolu par aucun registre réel).

## Conséquences

### Positives
- `job_id` traçable de bout en bout : un seul identifiant sur toutes les lignes `workflow_events` d'une exécution, prouvé par test E2E réel.
- Faille de concurrence réelle trouvée et corrigée (Décision 2) avant toute mise en service, pas après.
- Comportement externe de `/ingest/v2` prouvé inchangé par un test HTTP réel, pas seulement par relecture de code.

### Négatives
- Le worker traite un job de bout en bout en une seule exécution continue — pas de reprise fine par étape en cas de crash du process worker lui-même (distinct d'un bail expiré, couvert) ; nécessiterait la persistance `resource_candidates`/`artifacts`, hors périmètre.
- `profile_version` du pont `/ingest/v2` est un repère non résolu par construction — aucun job issu de ce chemin ne peut aujourd'hui être traité par un worker jusqu'au bout, cohérent avec le blocage LOT44c mais à lever explicitement le jour où une convention réelle existera.
- Le CLI worker n'a pas de mécanisme d'arrêt propre (signal handling) au-delà de `--max-iterations`/`--once` — suffisant pour du développement/test, pas pour un déploiement réel (hors périmètre, cf. « Hors périmètre »).
