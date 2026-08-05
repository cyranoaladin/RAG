# ADR-0029 — Câblage du gate LOT44c, provisioning du plan de contrôle et sort du worker Celery (LOT44f)

- **Statut** : Accepté
- **Date** : 2026-08-05
- **Décideur** : Alaeddine Ben Rhouma (Shark)
- **Découle de** : ADR-0024 (contrats LOT44a), ADR-0025 (plan de contrôle, LOT44b), ADR-0026 (profils/validation/gate, LOT44c), ADR-0027 (stages, LOT44d), ADR-0028 (scheduler/worker/pont `/ingest/v2`, LOT44e)
- **Déclencheur** : audit `docs/reports/rag_project_global_state_2026-08-04.md` (statut `NOT_READY_FOR_PRODUCTION`), mission de finalisation technique go-live du 2026-08-05.

## Contexte

ADR-0026 documente explicitement que le gate LOT44c (`ingestion_profiles.startup_gate.enforce_production_manifest_gate`) est un mécanisme complet mais **non câblé** dans `api.py`, pour ne pas modifier un fichier d'un lot antérieur (LOT43) sans mandat explicite — mandat que la présente mission fournit. Ce document couvre trois décisions fermées ensemble parce qu'elles concernent le même passage de LOT44a-e du statut « construit et testé isolément » à « réellement intégré dans un processus déployé ».

Rappel du blocage de gouvernance qui borne toute cette mission, et que rien ci-dessous ne lève : `services/rag-pedago/configs/pedago_interface_contract.yml` et `services/rag-pedago/configs/transition_authorization.yml` fixent tous deux `real_documents_allowed: false` et `curated_ingestion_allowed: false`, sans aucun `authorization_case` autorisant un pipeline réel. Aucune matrice de profils de production n'existe dans le dépôt (`configs/ingestion_profiles/` n'existe pas). Cet ADR câble un mécanisme de gate — il ne l'alimente d'aucun profil réel et ne prétend à aucune approbation.

## Décision 1 — Le gate est conditionnel dans `api.py`, inconditionnel dans le worker

`api.py` sert deux fonctions distinctes : le retrieval en lecture seule (`pedago_interface_contract.yml` : `server_start_allowed: true`, indépendant de `real_documents_allowed`) et, depuis LOT44e, une tentative best-effort de création de job vers le plan de contrôle si `PG_INGESTION_CONTROL_DSN` est configuré. Bloquer inconditionnellement le démarrage de `api.py` en l'absence de manifest casserait tout déploiement retrieval-only légitime — un déploiement qui n'a jamais eu l'intention d'activer l'ingestion gouvernée.

**Décision** : le signal d'activation du gate dans `api.py` est `PG_INGESTION_CONTROL_DSN` — la même variable qui active déjà, depuis LOT44e, le pont best-effort `/ingest/v2` → job. Ce n'est pas un nouveau flag arbitraire de contournement (proscrit par la mission et par ADR-0026) : c'est la réutilisation d'un signal d'intention déjà existant. Si la variable est absente (état réel de tous les `.env*` du dépôt aujourd'hui), `api.py` démarre exactement comme avant cette mission. Si elle est présente, le gate est appelé dans `_app_lifespan` avant `yield` ; toute exception (manifest absent, registre vide/invalide, empreinte incohérente, version de manifest non supportée) empêche FastAPI de démarrer — fail-closed, aucune capture d'exception.

Le worker (`ingestion_worker.cli`) n'a, par construction, aucune raison d'être démarré sans plan de contrôle — son unique rôle est de réclamer et traiter des jobs. Le gate y est donc **inconditionnel**, appelé en tout premier dans `main()`, avant toute connexion PostgreSQL. Un nouvel argument CLI obligatoire `--manifest-path` est ajouté (même discipline que `--profiles-dir` : explicite, jamais de valeur par défaut devinée), conformément à la garantie de LOT44c qu'aucun chemin de manifest par défaut n'est jamais supposé.

Nouveau module `services/rag-engine/src/ingestor/ingestion_governance_gate.py` : câblage pour `api.py` uniquement (résolution par variables d'environnement — `RAG_ENGINE_INGESTION_PROFILES_DIR`, nouvelle `RAG_ENGINE_INGESTION_MANIFEST_PATH`). Ne modifie aucun fichier `ingestion_profiles/*.py` — ADR-0026 reste fermé.

## Décision 2 — Provisioning réel du schéma `ingestion_control`

`bootstrap_ingestion_control_schema.sh` et `provision_ingestion_control_roles.sh` existaient, testés, jamais invoqués par `docker-compose.v2.yml` (dont le service `migrator` n'exécute que `bootstrap_pgvector_schema.sh`). Décision : ajouter un service Compose dédié `migrator-ingestion-control` (nouveau, pas une extension du `migrator` existant — schémas et rôles logiquement distincts, échec de l'un ne doit jamais bloquer silencieusement l'autre), qui exécute les deux scripts existants sans modification, avec les mots de passe de rôle exigés par variables d'environnement sans défaut (`INGESTION_CONTROL_MIGRATOR_PASSWORD`, `INGESTION_CONTROL_APP_PASSWORD`).

Le service `ingestion-worker` (nouveau) dépend de `migrator-ingestion-control` (`service_completed_successfully`) et exécute `python -m ingestor.ingestion_worker.cli` avec les arguments désormais requis, dont `--manifest-path`.

## Décision 3 — Le worker Celery orphelin est retiré, pas connecté

`tasks.py::ingest_document_task` n'a aucun appelant dans `src/` (`rg ".delay(\|.apply_async("` → 0 résultat, reconfirmé). Aucun besoin métier actuel ne justifie une tâche asynchrone Celery distincte : la nouvelle chaîne d'ingestion gouvernée (LOT44e) a déjà son propre worker. Décision : retirer le service `worker` (Celery) de `docker-compose.v2.yml` et supprimer `tasks.py`, plutôt que de le connecter à un besoin qui n'existe pas (sur-ingénierie proscrite par AGENTS.md). Réversible via Git si un besoin Celery réel émerge plus tard — ce serait alors une nouvelle décision, avec un appelant réel à documenter, pas une résurrection de code mort.

## Ce que cette décision ne fait pas

- Ne crée, ne charge et ne marque approuvé aucun profil de production réel.
- Ne lève aucun verrou de `pedago_interface_contract.yml`/`transition_authorization.yml`.
- Ne modifie aucun fichier `ingestion_profiles/*.py` (ADR-0026 reste fermé).
- Ne rend `api.py` bloquant que pour les déploiements qui configurent explicitement `PG_INGESTION_CONTROL_DSN` — tout déploiement retrieval-only actuel reste inchangé.

## Tests

Positifs et négatifs pour les deux processus (`api.py` via `TestClient` + lifespan, `ingestion_worker.cli.main`) : manifest valide, manifest absent, répertoire de profils absent, empreinte incohérente, version de manifest non supportée, `PG_INGESTION_CONTROL_DSN` absent (gate non appelée, démarrage `api.py` inchangé).
