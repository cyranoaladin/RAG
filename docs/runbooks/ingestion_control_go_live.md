# Runbook — Plan de contrôle d'ingestion gouvernée (`ingestion_control`, LOT44f/ADR-0031)

> Périmètre strict de ce runbook : le plan de contrôle d'ingestion
> gouvernée (`docker-compose.ingestion.yml`, opt-in) — migrateur, worker,
> volume d'artefacts, rollback, sauvegarde/restauration, attestation de
> rôle. Ne couvre pas le runtime v2 normal (`docker-compose.v2.yml`,
> lecture/revue), documenté par ailleurs (`go_live.md`, `rollback.md`).
>
> État réel à la date de ce document : **jamais déployé en production**
> (cf. ADR-0031). Ce runbook prépare le jour où ce sera le cas ; il ne
> constitue ni une autorisation, ni une preuve d'approbation gouvernance.

## 0. Préalable non négociable — gouvernance

Ce plan de contrôle ne démarre le worker qu'à la condition qu'un manifest
de production **réellement approuvé par une autorité humaine nommée**
existe (`enforce_production_manifest_gate`, LOT44c/LOT44f). Aucune
commande de ce runbook ne crée, n'approuve, ni ne contourne ce manifest.
Si aucun manifest approuvé n'existe, le worker refuse de démarrer
(`WORKER_STARTUP_GATE_FAILED`) — c'est le comportement voulu, pas un bug à
corriger en urgence.

De même, les verrous de `services/rag-pedago/configs/
pedago_interface_contract.yml` (`real_documents_allowed`,
`curated_ingestion_allowed`) régissent indépendamment si une ingestion de
documents réels est autorisée. Ce runbook ne les modifie jamais — cf.
AGENTS.md.

## 1. Prérequis

- Le runtime v2 normal (`pgvector`) doit pouvoir démarrer sainement —
  cf. `go_live.md`.
- Variables d'environnement requises dans `infra/.env` (jamais commitées,
  jamais réutilisées d'un environnement à l'autre) :
  - `INGESTION_CONTROL_MIGRATOR_PASSWORD`, `INGESTION_CONTROL_APP_PASSWORD`
    (≥ 32 caractères, générés aléatoirement — cf.
    `provision_runtime_roles.sh` pour la même exigence sur les autres
    rôles) ;
  - `PG_INGESTION_CONTROL_DSN` (DSN complet du rôle
    `ingestion_control_app`, jamais recomposé depuis des champs séparés) ;
  - `RAG_INGESTION_PROFILES_HOST_DIR`, `RAG_INGESTION_MANIFEST_HOST_PATH`
    (chemins hôte vers le répertoire de profils et le manifest approuvé —
    **jamais** un chemin placé dans l'arbre `configs/` versionné tant
    qu'aucune approbation gouvernance réelle n'existe) ;
  - `INGESTION_CONTROL_MIGRATOR_ROLE`/`INGESTION_CONTROL_APP_ROLE` (valeurs
    par défaut acceptables : `ingestion_control_migrator`/
    `ingestion_control_app` — ne jamais les rendre identiques entre eux, ni
    égales à `PGUSER` : `provision_ingestion_control_roles.sh` refuse ces
    deux collisions avant toute écriture).

## 2. Démarrage

```bash
cd services/rag-engine
make v2-ingestion-up
```

Cette cible attend explicitement (`--wait`) que :
1. `migrator-ingestion-control` (job ponctuel) se termine avec succès
   (bootstrap du schéma + provisioning des rôles) ;
2. `ingestion-worker` devienne `healthy` (heartbeat file), ce qui inclut
   son attestation de rôle au démarrage (item I, § 5 ci-dessous) et le
   gate LOT44c (§ 0 ci-dessus).

Un code de sortie non-nul signifie que l'un des deux a échoué — **ne
jamais** interpréter un retour rapide de la commande comme un succès sans
vérifier son code de sortie réel. `docker compose ... ps -a` donne le
détail du service en cause.

## 3. Créer un job d'ingestion (opérateur humain uniquement)

Aucun endpoint réseau n'existe pour créer un job — volontairement, pour ne
jamais recréer le writer public fermé par ADR-0024 :

```bash
docker exec -it <container_ingestion-worker> \
  python -m ingestion_worker.create_job_cli \
  --profiles-dir /app/configs/ingestion_profiles \
  --manifest-path /app/configs/ingestion_manifest.yml \
  --tenant ... --collection ... --niveau ... --voie ... --matiere ... \
  --candidat ... --audience ... --visibility ... --school-year ... \
  --programme-version ... \
  --profile-version ... \
  --source-url ... --canonical-url ... --domain ... --proposed-type-doc ...
```

L'identité d'idempotence est `(collection, dedup_key)` — une resoumission
de la même URL dans une collection différente crée un job indépendant,
jamais un doublon silencieusement ignoré.

## 4. Rollback du schéma `ingestion_control`

**Jamais** `psql -f <rollback>.sql` à la main, fichier par fichier — sans
transaction unique, un verrou pris par une instruction isolée est relâché
avant la suivante, laissant une fenêtre où une écriture concurrente peut
s'intercaler. Utiliser exclusivement le runner officiel :

```bash
cd services/rag-engine
PGHOST=... PGPORT=... PGUSER=<superutilisateur ou rôle de migration> \
PGPASSWORD=... PGDATABASE=... \
TARGET_VERSION=<version de schéma cible, ex. 3> \
./infra/scripts/rollback_ingestion_control_schema.sh
```

Ce script :
- **refuse** si un job est `running` ou si une ressource porte un bail
  actif (`INGESTION_NOT_QUIESCENT`) — attendre la fin naturelle du
  traitement ou laisser le reaper de baux agir, puis réessayer ;
- exécute l'intégralité de la plage annulée (verrous + gardes de vacuité +
  DROP/ALTER + mise à jour de `schema_migrations`) dans **une seule**
  transaction — tout ou rien, jamais un état partiel ;
- verrouille les six tables du schéma dans un ordre alphabétique fixe, dès
  le début de la transaction, indépendamment de la plage réellement
  affectée — élimine tout risque d'interblocage avec le worker.

## 5. Attestation du worker au démarrage

Le worker refuse de démarrer si la connexion PostgreSQL réelle
(`PG_INGESTION_CONTROL_DSN`) ne correspond pas exactement au rôle attendu
(`--expected-role`, dérivé de `INGESTION_CONTROL_APP_ROLE`) et à une
politique de moindre privilège stricte : non-superutilisateur, sans
`CREATEDB`/`CREATEROLE`/`REPLICATION`/`BYPASSRLS`, sans propriété du
schéma `ingestion_control`, sans privilège excédentaire sur
`workflow_events` (`UPDATE`/`DELETE`/`TRUNCATE`), sans appartenance à un
autre rôle (aucune voie de `SET ROLE` vers une autorité supérieure).

Un échec produit `WORKER_ATTESTATION_FAILED: <raison>` sur stderr et un
code de sortie 1 — jamais un démarrage dégradé avec des privilèges non
vérifiés. Cause la plus probable en cas d'échec : `PG_INGESTION_CONTROL_DSN`
pointe par erreur vers le superutilisateur du conteneur `pgvector` plutôt
que vers le rôle `ingestion_control_app` dédié — vérifier la valeur
réellement injectée dans le conteneur (`docker exec ... env | grep
PG_INGESTION_CONTROL_DSN`, jamais affichée dans des logs persistants).

## 6. Sauvegarde et restauration

Le volume d'artefacts (`rag_ingestion_artifacts_data`) et le schéma
PostgreSQL `ingestion_control` doivent **toujours** être sauvegardés et
restaurés ensemble — une restauration de l'un sans l'autre laisse des
`extracted_text_ref` orphelins (référence en base vers un fichier absent
du volume restauré, ou inversement).

```bash
BACKUP_DIR=/path/to/backups ./infra/scripts/backup-volumes.sh
```

Ce script résout le nom **réel** du volume Docker (préfixé par le nom de
projet Compose, ex. `infra_rag_ingestion_artifacts_data`) via les
étiquettes `com.docker.compose.project`/`com.docker.compose.volume` posées
par Compose lui-même — jamais un nom nu supposé, qui ne correspondrait à
aucun volume réellement créé par `docker compose up` sans
`-p`/`COMPOSE_PROJECT_NAME` explicite. Le schéma PostgreSQL, lui, suit la
même procédure de sauvegarde que le reste de l'instance `pgvector`
(cf. `go_live.md`) — même instance, schéma logique distinct (décision D1).

Restauration : restaurer le volume ET le schéma depuis des archives
prises **au même instant** (même horodatage de nom de fichier), jamais
deux archives d'horodatages différents.

## 7. Diagnostics courants

| Symptôme | Cause probable | Action |
|---|---|---|
| `make v2-ingestion-up` retourne non-zéro | `migrator-ingestion-control` a échoué (rôles identiques, mot de passe < 32 car., etc.) OU `ingestion-worker` jamais healthy (gate refusé, attestation refusée) | `docker compose ... ps -a` puis `docker logs <container>` |
| `WORKER_STARTUP_GATE_FAILED` | Aucun manifest approuvé, ou empreinte ne correspondant plus au profil réel | Vérifier `RAG_INGESTION_MANIFEST_HOST_PATH` ; ne jamais fabriquer une approbation |
| `WORKER_ATTESTATION_FAILED` | DSN pointant vers le mauvais rôle | Vérifier `PG_INGESTION_CONTROL_DSN` réellement injecté |
| `INGESTION_NOT_QUIESCENT` au rollback | Job `running` ou bail actif | Attendre, ou vérifier `ingestion_control.jobs`/`resources` directement |
| `ROLLBACK_00X_DATA_PRESENT` | Données présentes que le rollback refuse de détruire silencieusement | Décision opérateur explicite (archiver ou confirmer la perte), jamais un contournement automatique |

## 8. Ce que ce runbook ne couvre pas

- L'approbation d'un manifest de production (processus humain hors
  périmètre technique).
- La bascule des verrous de gouvernance (`real_documents_allowed`,
  `curated_ingestion_allowed`) — cf. `transition_authorization.yml` + ADR
  dédié.
- Tout écriture sur un serveur de production réel — aucun serveur cible
  n'est nommé dans ce dépôt à la date de ce document (cf. ADR-0031).
