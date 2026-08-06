# Rapport de lot — LOT44f réconciliation : worker d'ingestion gouvernée isolé sur runtime v2

- **Branche** : `reconcile/lot44-governed-ingestion-on-main`
- **Base** : `origin/main` @ `858c2c186ec4a712c476ecdd1d6a8d3efec60579`
- **ADR associé** : `docs/adr/ADR-0031-reconciliation-lot44-worker-isole-sur-runtime-v2.md` — **Statut : Proposé, non Accepté**
- **Date** : 2026-08-05

## 1. Contexte et mandat

Ce lot fait suite à une mission d'audit et d'adaptation de la plateforme RAG à la production Hetzner réelle (`root@88.99.254.59`, `rag-ui.nexusreussite.academy` / `rag-api.nexusreussite.academy`). L'inspection en lecture seule de cette production, réalisée plus tôt dans cette même session sous autorisation explicite du propriétaire du dépôt, a confirmé que le runtime réellement déployé est `api_v2:app` — cohérent avec `origin/main` (ADR-0024, ADR-0025), pas avec la branche `feat/rag-go-live-20260804` sur laquelle le pipeline LOT44a-f avait été développé indépendamment.

Le propriétaire du dépôt a explicitement tranché ce conflit architectural : `origin/main`/`api_v2:app`/ADR-0024/ADR-0025 sont l'architecture et la gouvernance canoniques ; `feat/rag-go-live-20260804` n'est pas déployé tel quel ; le pipeline LOT44 doit être réconcilié sur la base d'`origin/main`, jamais fusionné aveuglément. Le travail de `feat/rag-go-live-20260804` a été préservé intact via le tag `lot44f-prototype-20260805` avant toute réconciliation.

Ce rapport documente le résultat de cette réconciliation, conformément au point d'arrêt obligatoire fixé par le propriétaire du dépôt : cette branche est prête à être poussée et proposée en pull request, **mais aucune écriture de production n'a été effectuée, et ne le sera pas avant review humaine formelle**.

## 2. Constat d'inspection production (rappel)

- Runtime réellement déployé : `api_v2:app` (lecture + revue uniquement), cohérent avec ADR-0024.
- Aucune trace de worker d'ingestion, de LOT41A ou de LOT42 sur le serveur inspecté.
- Le détail complet de cette inspection (sorties de commandes SSH en lecture seule) a été communiqué au propriétaire du dépôt directement dans cette session au moment de sa réalisation ; il n'est pas retranscrit intégralement ici pour éviter toute reconstruction approximative a posteriori — seul le constat qui gouverne la décision de ce lot (runtime = `api_v2:app`) est repris, car c'est le seul fait sur lequel repose la décision de réconciliation.

## 3. Travail réalisé

### 3.1 Renumérotation ADR (collision résolue)

Les cinq ADR LOT44a-e, numérotés indépendamment ADR-0024 à ADR-0028 sur `feat/rag-go-live-20260804`, entraient en collision avec ADR-0024/ADR-0025 déjà acceptés sur `origin/main`. Renumérotés ADR-0026 à ADR-0030 (mapping single-pass, sans double-substitution en cascade), contenu technique inchangé, toutes les références croisées (ADR + docstrings/commentaires du code source LOT44) mises à jour.

### 3.2 Portage du pipeline LOT44 (additions pures)

Portés depuis le tag `lot44f-prototype-20260805`, sans modification de fond sauf mention contraire :
- `packages/contracts/src/nexus_contracts/{ingestion,resource_state}.py` + entrées `__init__.py`/version `0.6.0`.
- `services/rag-engine/src/ingestor/{ingestion_control,ingestion_agents,ingestion_profiles,ingestion_worker}/` (`ingest_v2_bridge.py` **exclu** : `api_v2.py` ne possède aucun endpoint d'écriture à pontuer).
- `services/rag-engine/infra/postgres/ingestion_control/{migrations,rollbacks}/` (6 migrations + 6 rollbacks + `HEAD`).
- `services/rag-engine/infra/scripts/{bootstrap_ingestion_control_schema,provision_ingestion_control_roles,provision_and_bootstrap_ingestion_control}.sh`.

### 3.3 Isolation du worker (ADR-0031, Décision 1)

- `Dockerfile.ingestion-worker` (nouveau) : allowlist COPY dédiée, `requirements.ingestion-worker.txt` minimal audité contre les imports réels (psycopg, httpx, PyYAML, pydantic — ni FastAPI ni modèle d'embedding).
- `docker-compose.v2.yml` : deux services ajoutés en pure addition (`migrator-ingestion-control`, `ingestion-worker`) — `git diff origin/main` ne montre aucune ligne supprimée sur ce fichier. `ingestion-worker` ne déclare aucun bloc `ports:`.
- `ingestion_worker/create_job_cli.py` (nouveau) : remplace le rôle de `/ingest/v2` — création de job strictement par `docker exec`, jamais par une route réseau.

### 3.4 Correctif LOT43 (ADR-0031, Décision 2)

`ssrf_guard.safe_fetch` reconstruisait une réponse déjà décodée (`iter_bytes()`) en conservant l'en-tête `Content-Encoding` d'origine, provoquant une double tentative de décompression (`zlib.error`) sur toute réponse HTTPS compressée. Corrigé en retirant les en-têtes `content-encoding`/`content-length`/`transfer-encoding` désormais caducs avant reconstruction. Toutes les protections SSRF existantes (DNS, IP privées, redirections, taille) inchangées. 7 nouveaux tests (gzip/deflate valides, corps malformé, bombe de décompression, redirection + compression, non-régression).

### 3.5 Couche d'autorité minimale (ADR-0031, Décision 3)

`ingestion_profiles/manifest.py` exige désormais `approved_by`/`approved_at` (non vides, `approved_at` ISO 8601 valide) sur chaque entrée de manifest, au même niveau d'exigence que `fingerprint`. Confirmé par recherche explicite : LOT41A/LOT42 n'existent nulle part dans ce dépôt (code, ADR, trace serveur) — cette couche ne les implémente pas, elle garantit seulement qu'aucune entrée de manifest ne peut être acceptée sans autorité humaine nommée et attribuable. Le worker et l'outil de création de job consignent cette autorité au démarrage/à la création (`WORKER_STARTUP_AUTHORITY`, `JOB_CREATION_AUTHORITY`).

## 4. Validation réelle exécutée

### 4.1 Qualité statique

```
ruff check .        → All checks passed!
mypy src             → Success: no issues found in 84 source files
```

### 4.2 Tests unitaires (PYTHONPATH=src, environnement venv complet)

Suite complète `services/rag-engine/tests` (hors `integration/`) : **verte, code de sortie 0**. Un seul test préexistant a nécessité une mise à jour délibérée et documentée (`test_v2_compose_contains_only_the_read_review_stack`, qui asserait un ensemble fermé de 3 services — mis à jour en sur-ensemble `<=` plus une nouvelle assertion dédiée qui vérifie explicitement que les deux services ajoutés restent non exposés et non permanents). Aucun autre test vert n'est passé au rouge.

### 4.3 Tests d'intégration (PostgreSQL jetable réel, via Docker)

```
tests/integration/test_lot44c_profile_validation_events.py   26 passed
tests/integration/test_lot44d_chain_wiring.py                 1 passed
tests/integration/test_lot44e_jobs_control.py                15 passed
tests/integration/test_lot44e_worker_e2e.py                   4 passed
tests/integration/test_lot44f_migration_rollback_rehearsal.py 1 passed
tests/integration/test_lot44f_worker_resume.py                 4 passed
                                                    TOTAL:    51 passed
```

Le rollback rehearsal (001→006 puis 006→001 puis 001→006 à nouveau) est un test réel, pas une simulation.

### 4.4 Preuve Docker réelle de bout en bout (stack isolée, jamais la production)

Réseau/volumes/conteneurs dédiés (`lot44frecon_*`, sous-réseau `10.244.9.0/24`, jamais en collision avec les déploiements existants sur cette machine) :

1. `pgvector` démarre sain.
2. `migrator-ingestion-control` applique les 6 migrations, provisionne les 2 rôles PostgreSQL dédiés, sort en code 0.
3. `ingestion-worker` démarre, healthcheck vert (heartbeat).
4. Un job soumis via `create_job_cli.py` (dans le conteneur, via `docker exec`) traverse réellement DISCOVERED → CANDIDATE → FETCHED → STORED → EXTRACTED → CLASSIFIED → RIGHTS_CHECKED → QUALITY_CHECKED, `job_id` unique propagé sur les 7 transitions dans `workflow_events`, artefact réel récupéré depuis `https://example.com/` (559 octets, `text/html` détecté) — preuve que le correctif SSRF fonctionne dans le runtime construit.
5. `docker port lot44frecon_ingestion_worker` : aucune sortie — confirmé sans port exposé.
6. Un worker démarré sans profil/manifest valide refuse explicitement de démarrer (`WORKER_STARTUP_GATE_FAILED`, code de sortie 1) — fail-closed prouvé.
7. Stack entièrement détruite après preuve (`down -v`), aucune trace laissée.

## 5. Plan de migration et de rollback (schéma `ingestion_control`, pour une future activation)

- **Aller** : `migrator-ingestion-control` applique séquentiellement les migrations 001 à 006 (schéma + tables `ingestion_runs`/`resources`/`resource_candidates`/`artifacts`/`workflow_events`/`jobs`), puis `provision_ingestion_control_roles.sh` crée `ingestion_control_migrator`/`ingestion_control_app` avec privilèges minimaux table par table (`workflow_events` : `INSERT`/`SELECT` uniquement, jamais `UPDATE`/`DELETE` — append-only appliqué au niveau SQL).
- **Retour** : rollbacks `.down.sql` existent pour les 6 migrations, rejoués et vérifiés (section 4.3) dans les deux sens sur une base jetable.
- **Portée** : schéma logique séparé sur la même instance PostgreSQL que `pgvector` — aucune table `rag_chunks`/`public` touchée, aucune donnée de retrieval affectée dans un sens comme dans l'autre.
- **Non exécuté sur la production** : ce plan n'a été rejoué que sur des instances PostgreSQL jetables locales, jamais contre le serveur Hetzner.

## 6. Liste précise des changements qui seraient apportés à la production si ce lot était approuvé et déployé

**Aucun de ces changements n'a été effectué.** Liste exhaustive de ce qu'impliquerait un déploiement futur, séparément autorisé :

1. Construire et déployer l'image `Dockerfile.ingestion-worker` (nouvelle image, n'affecte pas l'image `ingestor` existante).
2. Ajouter les deux services `migrator-ingestion-control`/`ingestion-worker` à la stack Compose de production (addition pure — aucun service existant modifié, redémarré ou recréé).
3. Exécuter `migrator-ingestion-control` une fois (applique les migrations 001-006 sur le schéma `ingestion_control`, crée deux rôles PostgreSQL) — n'affecte aucune table existante.
4. Fournir de nouvelles variables d'environnement (`PG_INGESTION_CONTROL_DSN`, `INGESTION_CONTROL_MIGRATOR_PASSWORD`, `INGESTION_CONTROL_APP_PASSWORD`, `RAG_INGESTION_PROFILES_HOST_DIR`, `RAG_INGESTION_MANIFEST_HOST_PATH`, `INGESTION_WORKER_OWNER`) — aucune variable existante modifiée.
5. **Ne démarrerait toujours pas** de traitement réel : `ingestion-worker` resterait fail-closed tant qu'aucun manifest réel, approuvé par une autorité humaine nommée, n'est fourni — ce que ce lot ne fait pas.

Aucune activation de `real_documents_allowed`/`curated_ingestion_allowed` n'est incluse ni requise par cette liste.

## 6bis. Remédiation de la revue PR#90 (Codex, Cubic, GitGuardian)

Après ouverture de la PR sur le HEAD `9306f1cb4f92037c09a2edb63b78665be0afcc79`, le propriétaire du dépôt a explicitement refusé d'approuver ce HEAD, signalé que les revues automatisées avaient fait remonter des problèmes de sécurité/concurrence/intégrité/migration/exploitation, et mandaté leur traitement complet avant toute nouvelle demande de review. Traité intégralement : 40 signalements Cubic, 5 signalements Codex (dont recoupements documentés avec Cubic), 5 occurrences GitGuardian (1 seul incident logique). Matrice complète, signalement par signalement (diagnostic réel avant correction, jamais mécanique) : `docs/reports/pr90_review_remediation_matrix.md`.

**Changements les plus significatifs** (liste complète dans la matrice et dans ADR-0031, Décision 5) :

- Plan de contrôle d'ingestion déplacé dans un fichier Compose séparé, strictement opt-in (`docker-compose.ingestion.yml`) — `docker-compose.v2.yml` restauré à l'état exact d'`origin/main`.
- Le worker garde en mémoire l'exact `ProfileRegistry` vérifié au démarrage pour toute sa durée de vie — plus de rechargement disque par job.
- `niveau_conformity`/`voie_conformity`/`programme_conformity` valent désormais `False` ("non vérifié") — `QUALITY_CHECKED -> ROUTED` devient structurellement inatteignable tant qu'aucun classifieur réel de contenu n'existe (changement intentionnel).
- Identité de dédoublonnage unifiée (job ↔ Scout, dérivée de `canonical_url`) ; nouvelle primitive `find_or_create_job` atomique sous concurrence (verrou advisory PostgreSQL), prouvée par un test à deux connexions réelles concurrentes.
- Sémantique de bail stricte sur toutes les primitives de concurrence (expiration vérifiée, pas seulement le jeton).
- SSRF : RFC 6598 désormais bloqué. Provisioning PostgreSQL : mots de passe hors ligne de commande (`\getenv`, prouvé par inspection `ps` réelle), collision de rôles rejetée, attributs réalignés sur rôle préexistant.
- Migrations/rollbacks rendus concurrency-safe (`LOCK TABLE ACCESS EXCLUSIVE`) et upgrade-safe (backfill `claimed`, garde explicite sur table peuplée, `ADD CONSTRAINT` idempotent).

**Non corrigé, hors périmètre documenté** : `planner.py::plan_search_core` n'applique toujours pas `max_queries_per_run` (Cubic P2, non trivial sans revoir la logique de couverture existante — signalé pour un lot LOT44d dédié).

**Validation après remédiation** (commandes exactes, HEAD remédié) :

```
ruff check .        → All checks passed!
mypy src             → Success: no issues found in 84 source files
pytest (unitaire, hors integration)   → exit 0
pytest tests/integration/ (PostgreSQL réel) → exit 0, y compris :
  - un test de concurrence réel (2 threads, 2 connexions PostgreSQL distinctes,
    synchronisées par threading.Barrier) prouvant l'atomicité de find_or_create_job
  - un test d'inspection de processus réel (ps -eo args) prouvant l'absence de
    mot de passe dans la ligne de commande psql
  - le rollback rehearsal complet (001↔006) rejoué avec les nouveaux LOCK TABLE
  - deux nouveaux scénarios d'upgrade sur base peuplée (jobs.status='claimed'
    préexistant réconcilié ; migration 006 bloquée explicitement sur table non vide)
```

GitGuardian : 5 occurrences, un seul incident logique, triage complet dans la matrice — confirmées valeurs de test factices (mots de passe PostgreSQL pour des conteneurs Docker jetables créés et détruits dans le même processus de test), aucune correspondance avec un secret réel, aucune rotation nécessaire, aucune exclusion globale créée.

## 7. Verdicts

- **`PRODUCTION_INFRASTRUCTURE_STATUS`** : `api_v2:app` confirmé comme runtime de production réel (inspection lecture seule antérieure dans cette session) — cohérent avec `origin/main`, gouvernance ADR-0024/ADR-0025 non modifiée.
- **`INGESTION_GO_LIVE_STATUS`** : `NOT_ACTIVATED` — le pipeline d'ingestion gouvernée est techniquement prêt et isolé (ce lot), mais reste désactivé : aucun manifest réel approuvé, aucune activation de gouvernance, ADR-0031 non Accepté.
- **`FULL_RAG_GO_LIVE_STATUS`** : le retrieval/review existant (`api_v2:app`) n'est touché par aucun changement de ce lot ; ce lot n'affecte que la disponibilité future, non activée, d'une ingestion gouvernée séparée.

## 8. Point d'arrêt (conformément au mandat)

Ce lot s'arrête ici. Avant toute écriture de production :

- Ce PR doit être ouvert sur `origin/main`.
- ADR-0031 doit recevoir une review `APPROVED` du Code Owner `@abenrhouma` dont `commit_id` égale le HEAD exact de cette branche au moment de la review (ADR-0025).
- Un manifest réel, portant un `approved_by`/`approved_at` d'une autorité humaine réellement habilitée, doit être créé séparément — hors périmètre de ce lot.
- Le déploiement effectif (section 6) doit être explicitement autorisé, séparément de l'acceptation de cet ADR.

Le SHA final exact de cette branche est celui du commit qui inclut ce rapport — voir le message de la pull request associée pour sa valeur littérale au moment de l'ouverture.
