# Runbook — Plan de contrôle d'ingestion gouvernée (LOT44b-f, ADR-0025/0029)

Ce runbook couvre exclusivement le sous-système `ingestion_control` /
`ingestion_worker` / `ingestion_profiles` (LOT44b-f) — pas le moteur de
retrieval pgvector (`docs/runbooks/rollback.md`, `docs/runbooks/go_live.md`
couvrent ce périmètre séparément).

**Statut au 2026-08-05** : ce sous-système est techniquement complet et
testé de bout en bout (voir `docs/reports/rag_project_global_state_2026-08-04.md`,
addendum LOT44f), mais **son activation en production réelle reste bloquée
par la gouvernance** — voir section « Blocages de gouvernance » ci-dessous
avant toute tentative de déploiement réel.

## 1. Composants

| Composant | Rôle | Démarré par |
|---|---|---|
| `migrator-ingestion-control` | Provisionne schéma + rôles PostgreSQL `ingestion_control` (migrations 001-006) | `docker-compose.v2.yml`, une fois au démarrage du stack |
| `ingestion-worker` | Réclame et traite les jobs (huit stages LOT44d) | `docker-compose.v2.yml`, service `unless-stopped` |
| `ingestor` (bloc ingestion gouvernée) | Pont best-effort `/ingest/v2` → job, gate LOT44c au démarrage | Conditionnel à `PG_INGESTION_CONTROL_DSN` |

## 2. Variables d'environnement requises

Voir `infra/.env.example` et `infra/.env.production.sample` pour la liste complète et les placeholders. Résumé des variables spécifiques à ce sous-système :

- `PG_INGESTION_CONTROL_DSN` — laissé vide = sous-système entièrement désactivé (comportement par défaut sûr). Le définir active le pont et le gate.
- `RAG_ENGINE_INGESTION_PROFILES_DIR` / `RAG_ENGINE_INGESTION_MANIFEST_PATH` — obligatoires dès que `PG_INGESTION_CONTROL_DSN` est défini (gate LOT44c fail-closed, `IngestionGovernanceConfigError` sinon).
- `RAG_ENGINE_INGESTION_PROFILES_HOST_DIR` / `RAG_ENGINE_INGESTION_MANIFEST_HOST_PATH` — chemins hôte montés en lecture seule dans le conteneur `ingestion-worker` (variables Compose distinctes des chemins conteneur ci-dessus).
- `INGESTION_CONTROL_MIGRATOR_PASSWORD` / `INGESTION_CONTROL_APP_PASSWORD` — mots de passe des deux rôles PostgreSQL dédiés (jamais de défaut).
- `INGESTION_WORKER_OWNER` — identité du worker dans les baux de jobs (`claimed_by`).

## 3. Démarrage (déploiement réel)

```bash
cd services/rag-engine/infra
cp .env.example .env   # puis remplir toutes les valeurs, y compris le bloc LOT44f
docker compose -f docker-compose.v2.yml up -d --build
docker compose -f docker-compose.v2.yml ps
docker compose -f docker-compose.v2.yml logs migrator-ingestion-control
```

`migrator-ingestion-control` doit se terminer avec `PROVISION_AND_BOOTSTRAP_COMPLETE` (code de sortie 0, `restart: "no"`) avant que `ingestion-worker` ne démarre (`depends_on: condition: service_completed_successfully`).

Vérifier le healthcheck du worker (heartbeat) :

```bash
docker compose -f docker-compose.v2.yml ps ingestion-worker
docker inspect --format '{{.State.Health.Status}}' <container_id>
```

## 4. Vérification du schéma

```bash
docker compose -f docker-compose.v2.yml exec pgvector \
  psql -U "$PGVECTOR_USER" -d "$PGVECTOR_DB" -c \
  "SELECT version, file_name FROM ingestion_control.schema_migrations ORDER BY version;"
```

Doit lister les versions 1 à 6 (`001_ingestion_control_schema.sql` … `006_resource_candidates_and_artifacts_payload.sql`).

## 5. Rollback

Deux niveaux distincts :

### 5.1 Rollback applicatif (image/code)

Identique au runbook général (`docs/runbooks/rollback.md`, section 1-2) : `git checkout <commit précédent>` + `docker compose up -d --build`. Le schéma PostgreSQL n'est **jamais** modifié par un rollback applicatif seul (les migrations sont additives, jamais réécrites).

### 5.2 Rollback de schéma (rare, seulement si une migration doit être défaite)

Rejouer les fichiers `.down.sql` (`infra/postgres/ingestion_control/rollbacks/`) **dans l'ordre numérique inverse strict**, jamais dans un autre ordre (chaque `.down.sql` suppose que les migrations plus récentes ont déjà été défaites) :

```bash
for f in 006 005 004 003 002 001; do
  psql "$SUPERUSER_DSN" -f infra/postgres/ingestion_control/rollbacks/${f}_*.down.sql
  psql "$SUPERUSER_DSN" -c "DELETE FROM ingestion_control.schema_migrations WHERE version = $((10#$f));"
done
```

Chaque `.down.sql` refuse explicitement (`RAISE EXCEPTION ROLLBACK_00X_DATA_PRESENT`) si la table concernée contient des données — jamais de perte silencieuse. Rejouer `bootstrap_ingestion_control_schema.sh` réapplique ensuite la chaîne complète depuis un schéma vidé.

Testé réellement (LOT44f) : `tests/integration/test_lot44f_migration_rollback_rehearsal.py` — rollback complet 006→001 puis ré-application complète, sur PostgreSQL jetable réel.

## 6. Supervision

- `ingestion-worker` : logs `WORKER_ITERATION job_id=... status=...` (stdout, un par itération traitée), `WORKER_ITERATION_ERROR ...` sur stderr en cas d'échec. `WORKER_STARTUP_GATE_FAILED: ...` sur stderr + sortie non nulle si le gate LOT44c échoue au démarrage (fail-closed, le conteneur ne démarre pas).
- Table `ingestion_control.jobs` : `status`, `attempt_count`, `last_error` — requête directe pour l'état des jobs.
- Table `ingestion_control.workflow_events` : trace complète des transitions, `job_id` cohérent sur toute l'exécution d'un job.
- Reaper de baux expirés (`reap_expired_job_leases`) : primitive disponible (`ingestion_control.jobs`) mais **non branchée à une boucle planifiée** dans ce lot — dette connue, à ajouter (cron/service dédié) avant une exploitation à fort volume.

## 7. Blocages de gouvernance (ne jamais contourner)

- `services/rag-pedago/configs/pedago_interface_contract.yml` et `transition_authorization.yml` : `real_documents_allowed: false`, `curated_ingestion_allowed: false` — aucune ingestion de documents réels n'est autorisée tant que ces verrous n'ont pas été levés par une ADR dédiée et une autorisation explicite (jamais par ce sous-système lui-même).
- Aucune matrice de profils de production n'existe dans le dépôt (`configs/ingestion_profiles/` n'existe pas). Le gate LOT44c (`enforce_production_manifest_gate`) refusera tout démarrage tant qu'un manifest de production réel, approuvé, n'est pas fourni à `RAG_ENGINE_INGESTION_MANIFEST_PATH`.
- Ne jamais placer un profil ou un manifest de test dans un chemin qui pourrait être confondu avec la configuration de production réelle.

## 8. Composants explicitement absents (hors périmètre LOT44f, à escalader si nécessaire)

- Activation de `ROUTED -> STAGED -> REVIEWED -> RETRIEVAL_ELIGIBLE` (transformation en chunks `rag_chunks`, application des droits/visibilité) : nécessite une décision produit + une extension de contrat, non prise dans ce lot.
- Reaper planifié (boucle périodique appelant `reap_expired_job_leases`) : primitive existante, pas de scheduler dédié.
- Quotas/limites de concurrence multi-workers : un seul `ingestion-worker` provisionné par défaut ; la primitive de claim (`FOR UPDATE SKIP LOCKED`) supporte plusieurs workers concurrents, non testé à grande échelle dans ce lot.
