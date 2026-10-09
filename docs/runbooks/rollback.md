# Runbook Rollback — Plateforme RAG

> **Release gouvernée V2 :** les recettes Docker des sections 1 à 4
> décrivent l'ancienne stack. Elles ne constituent pas une commande de
> rollback pour le go-live. La bascule et le retour doivent utiliser les
> bundles immuables et les digests d'image vérifiés par le déploiement
> atomique ; la commande exacte et la cible de retour sont figées au gate de
> cutover. Ne pas faire `git checkout`, `up --build`, `down` sur le projet de
> production, ni employer `--remove-orphans` comme raccourci de retour.

## Quand déclencher un rollback

- Erreurs 500/503 persistantes après déploiement
- Régression fonctionnelle confirmée (search, ingest, review)
- Fuite de données ou incident sécurité
- Corruption de données détectée

## 1. Rollback du stack Docker

```bash
cd /opt/rag-local/services/rag-engine/infra

# Arrêter le stack courant
docker compose -f docker-compose.v2.yml down
# OU
docker compose -f docker-compose.prod.yml down

# Revenir au commit précédent
git log --oneline -n 10
git checkout <commit-precedent>

# Relancer
docker compose -f docker-compose.v2.yml up -d --build
# OU
docker compose -f docker-compose.prod.yml --profile db --profile llm \
  --profile api --profile ui up -d --build
```

## 2. Rollback d'image Docker (sans rebuild)

```bash
# Lister les images précédentes
docker images | grep rag_ingestor

# Relancer avec l'image précédente
docker compose -f docker-compose.v2.yml up -d --no-build
```

## 3. Rollback de configuration

```bash
# Restaurer .env depuis backup
cp /backup/.env.backup infra/.env
chmod 600 infra/.env

# Redémarrer
docker compose -f docker-compose.v2.yml restart
```

## 4. Rollback Nginx

```bash
# Restaurer les configs précédentes
sudo cp /backup/nginx/*.conf /etc/nginx/sites-available/

# Tester et recharger
sudo nginx -t && sudo systemctl reload nginx
```

## 5. Restauration des volumes (données)

### pgvector (v2)

Les backups produits par `apply_pgvector_migrations.sh` et les runners de
rollback utilisent `pg_dump -Fc`. Ce format custom ne se restaure jamais avec
une redirection vers `psql` : utiliser `pg_restore` et vérifier le dump avant
toute mutation. L'exercice ci-dessous est isolé ; il ne touche pas la stack de
production et ne démarre ni API, ni worker.

```bash
set -euo pipefail
: "${RESTORE_BACKUP_FILE:?exporter le chemin exact publié par BACKUP_COMPLETE}"
: "${RESTORE_ENV_FILE:?chemin du fichier de secrets existant, sans afficher les valeurs}"
: "${RESTORE_SOURCE_CONTAINER:?conteneur PostgreSQL source à lire seulement}"
: "${RESTORE_SOURCE_DB:?base source du dump à lire seulement}"
normalize_restore_paths() {
  RESTORE_BACKUP_FILE="$(realpath -e -- "$RESTORE_BACKUP_FILE")"
  RESTORE_ENV_FILE="$(realpath -e -- "$RESTORE_ENV_FILE")"
}
normalize_restore_paths
cd services/rag-engine/infra

# Les mêmes noms de base/rôle doivent servir à Compose et à pg_restore.
# Les variables exportées priment sur un éventuel PGVECTOR_DB dans --env-file.
PGVECTOR_DB="${PGVECTOR_DB:-ragdb}"
PGVECTOR_USER="${PGVECTOR_USER:-raguser}"
export PGVECTOR_DB PGVECTOR_USER

# Valeurs explicites : jamais le projet production, jamais le projet infra.
RESTORE_PROJECT="nexus-pg-restore-rehearsal-$(date -u +%Y%m%dt%H%M%Sz)"
umask 077
RESTORE_FIXTURE_DIR="$(mktemp -d)"
RESTORE_COMPOSE="$RESTORE_FIXTURE_DIR/compose.yml"
RESTORE_FINGERPRINT_SQL="$RESTORE_FIXTURE_DIR/fingerprint.sql"
RUNTIME_ROLE_PROVISIONING="$PWD/postgres/provision_runtime_roles.sh"
test -f "$RESTORE_BACKUP_FILE"
test -f "$RESTORE_ENV_FILE"
test -f "$RUNTIME_ROLE_PROVISIONING"
test "$RESTORE_PROJECT" != infra
test "$RESTORE_PROJECT" != production

# Le dump custom ne crée pas la base cible. Sans encodage/locale identiques,
# PostgreSQL recalcule text_tsv différemment pendant la restauration.
DB_IDENTITY_SQL="SELECT pg_encoding_to_char(encoding)||'|'||datcollate||'|'||datctype FROM pg_database WHERE datname=current_database()"
SOURCE_DB_IDENTITY="$(docker exec -e PGOPTIONS='-c default_transaction_read_only=on' \
  "$RESTORE_SOURCE_CONTAINER" sh -c \
  'psql -X -Atq -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1" -c "$2"' \
  sh "$RESTORE_SOURCE_DB" "$DB_IDENTITY_SQL")"

assert_restore_compatible_identity() {
  local source_identity="$1" target_identity="$2"
  if [[ "$source_identity" != 'UTF8|C|C' || "$target_identity" != "$source_identity" ]]; then
    printf 'Refus de restauration : identité PostgreSQL encodage/locale différente de UTF8|C|C.\n' >&2
    return 1
  fi
}

# Fixture autonome : seulement la base isolée et un client de restauration.
# Les placeholders restent littéraux dans ce fichier privé ; Compose les résout
# depuis .env sans y recopier les secrets.
cat >"$RESTORE_COMPOSE" <<'YAML'
services:
  pgvector:
    image: pgvector/pgvector:pg16@sha256:00ba258a66dac104fd5171074a0084462a64a1369d8513f3d0a634e2f24d15bc
    restart: "no"
    environment:
      POSTGRES_DB: ${PGVECTOR_DB:-ragdb}
      POSTGRES_USER: ${PGVECTOR_USER:-raguser}
      POSTGRES_PASSWORD: ${PGVECTOR_PASSWORD:?PGVECTOR_PASSWORD requis}
      POSTGRES_INITDB_ARGS: "--locale=C --encoding=UTF8"
    volumes: [restore_pgvector_data:/var/lib/postgresql/data]
    networks: [restore_net]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 2s
      timeout: 2s
      retries: 30
    security_opt: [no-new-privileges:true]
  restore-migrator:
    image: postgres:16-alpine@sha256:57c72fd2a128e416c7fcc499958864df5301e940bca0a56f58fddf30ffc07777
    restart: "no"
    environment:
      PGHOST: pgvector
      PGPASSWORD: ${PGVECTOR_PASSWORD:?PGVECTOR_PASSWORD requis}
      POSTGRES_DB: ${PGVECTOR_DB:-ragdb}
      POSTGRES_USER: ${PGVECTOR_USER:-raguser}
      PGVECTOR_RETRIEVAL_USER: ${PGVECTOR_RETRIEVAL_USER:?PGVECTOR_RETRIEVAL_USER requis}
      PGVECTOR_RETRIEVAL_PASSWORD: ${PGVECTOR_RETRIEVAL_PASSWORD:?PGVECTOR_RETRIEVAL_PASSWORD requis}
      PGVECTOR_REVIEW_USER: ${PGVECTOR_REVIEW_USER:?PGVECTOR_REVIEW_USER requis}
      PGVECTOR_REVIEW_PASSWORD: ${PGVECTOR_REVIEW_PASSWORD:?PGVECTOR_REVIEW_PASSWORD requis}
      PGVECTOR_PUBLISHER_USER: ${PGVECTOR_PUBLISHER_USER:?PGVECTOR_PUBLISHER_USER requis}
      PGVECTOR_PUBLISHER_PASSWORD: ${PGVECTOR_PUBLISHER_PASSWORD:?PGVECTOR_PUBLISHER_PASSWORD requis}
    networks: [restore_net]
    entrypoint: ["pg_restore"]
    security_opt: [no-new-privileges:true]
networks:
  restore_net: {}
volumes:
  restore_pgvector_data: {}
YAML

restore_compose=(
  docker compose -p "$RESTORE_PROJECT" --env-file "$RESTORE_ENV_FILE"
  -f "$RESTORE_COMPOSE"
)

cleanup_restore_fixture() {
  "${restore_compose[@]}" down -v >/dev/null 2>&1 || true
  rm -f -- "$RESTORE_COMPOSE" "$RESTORE_FINGERPRINT_SQL"
  rmdir -- "$RESTORE_FIXTURE_DIR" 2>/dev/null || true
}
trap cleanup_restore_fixture EXIT

# Refuser toute extension accidentelle de la fixture avant sa création.
test "$("${restore_compose[@]}" config --services | sort)" = \
  $'pgvector\nrestore-migrator'

# Vérifier que le fichier est bien un dump custom avant de créer la fixture.
"${restore_compose[@]}" run --rm --no-deps \
  --volume "$RESTORE_BACKUP_FILE:/restore/source.dump:ro" \
  restore-migrator \
  --list --format=custom /restore/source.dump >/dev/null

# Démarrer uniquement PostgreSQL, puis restaurer avec le client migrateur.
"${restore_compose[@]}" up -d --wait pgvector
RESTORE_DB_IDENTITY="$("${restore_compose[@]}" exec -T \
  -e PGOPTIONS='-c default_transaction_read_only=on' pgvector sh -c \
  'psql -X -Atq -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' \
  sh "$DB_IDENTITY_SQL")"
assert_restore_compatible_identity "$SOURCE_DB_IDENTITY" "$RESTORE_DB_IDENTITY"

"${restore_compose[@]}" run --rm --no-deps \
  --volume "$RESTORE_BACKUP_FILE:/restore/source.dump:ro" \
  restore-migrator \
  --exit-on-error --clean --if-exists --no-owner --no-privileges \
  --single-transaction --format=custom --host=pgvector \
  --username="${PGVECTOR_USER:-raguser}" \
  --dbname="${PGVECTOR_DB:-ragdb}" /restore/source.dump

# Aucun service applicatif ne doit exister dans le projet de rehearsal.
test "$("${restore_compose[@]}" ps --services --status running)" = pgvector

# Un dump historique sans schéma de contrôle prouve seulement sa lisibilité.
# Le contrôle complet est réservé à une base restaurée au head final 005/020.
classify_restore_schema_heads() {
  if [[ "$1" == '5|20' ]]; then
    printf 'FINAL_SCHEMA_VERIFIED\n'
  else
    printf 'FINAL_SCHEMA_UNVERIFIED\n'
  fi
}
SCHEMA_TABLES_SQL="SELECT CASE WHEN to_regclass('public.rag_schema_migrations') IS NOT NULL AND to_regclass('ingestion_control.schema_migrations') IS NOT NULL AND to_regclass('public.rag_artifacts') IS NOT NULL AND to_regclass('public.rag_artifact_placements') IS NOT NULL AND to_regclass('public.rag_chunks') IS NOT NULL THEN 'present' ELSE 'missing' END"
RESTORE_SCHEMA_TABLES="$("${restore_compose[@]}" exec -T \
  -e PGOPTIONS='-c default_transaction_read_only=on' pgvector sh -c \
  'psql -X -Atq -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' \
  sh "$SCHEMA_TABLES_SQL")"
RESTORE_SCHEMA_HEADS=''
if [[ "$RESTORE_SCHEMA_TABLES" == present ]]; then
  SCHEMA_HEADS_SQL="SELECT (SELECT max(version)::text FROM public.rag_schema_migrations)||'|'||(SELECT max(version)::text FROM ingestion_control.schema_migrations)"
  RESTORE_SCHEMA_HEADS="$("${restore_compose[@]}" exec -T \
    -e PGOPTIONS='-c default_transaction_read_only=on' pgvector sh -c \
    'psql -X -Atq -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "$1"' \
    sh "$SCHEMA_HEADS_SQL")"
fi
RESTORE_SCHEMA_VERDICT="$(classify_restore_schema_heads "$RESTORE_SCHEMA_HEADS")"
if [[ "$RESTORE_SCHEMA_VERDICT" == FINAL_SCHEMA_VERIFIED ]]; then
  # `--no-privileges` exige de réimposer les ACL runtime sur le schéma final.
  # Une base historique sans ces tables reste uniquement lisible en isolation.
  "${restore_compose[@]}" run --rm --no-deps \
    --volume "$RUNTIME_ROLE_PROVISIONING:/opt/nexus/provision_runtime_roles.sh:ro" \
    --entrypoint bash restore-migrator \
    /opt/nexus/provision_runtime_roles.sh

  # Comparer les identités métier et la colonne lexicale générée. Une source
  # modifiée depuis sa capture échoue au lieu de simuler un vert.
cat >"$RESTORE_FINGERPRINT_SQL" <<'SQL'
SELECT 'product_head|'||max(version)::text FROM public.rag_schema_migrations;
SELECT 'control_head|'||max(version)::text FROM ingestion_control.schema_migrations;
SELECT 'collections|'||count(DISTINCT collection)::text FROM public.rag_artifact_placements;
SELECT 'artifacts|'||count(*)::text||'|'||md5(coalesce(string_agg(md5(to_jsonb(t)::text),'|' ORDER BY artifact_id),'')) FROM public.rag_artifacts t;
SELECT 'placements|'||count(*)::text||'|'||md5(coalesce(string_agg(md5(to_jsonb(t)::text),'|' ORDER BY placement_id),'')) FROM public.rag_artifact_placements t;
SELECT 'chunks|'||count(*)::text||'|'||md5(coalesce(string_agg(md5(to_jsonb(t)::text),'|' ORDER BY chunk_id),'')) FROM public.rag_chunks t;
SELECT 'text_tsv|'||count(*)::text||'|'||md5(coalesce(string_agg(md5(chunk_id||':'||text_tsv::text),'|' ORDER BY chunk_id),'')) FROM public.rag_chunks;
SQL
SOURCE_FINGERPRINT="$(docker exec -i \
  -e PGOPTIONS='-c default_transaction_read_only=on' \
  "$RESTORE_SOURCE_CONTAINER" sh -c \
  'psql -X -Atq -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$1"' \
  sh "$RESTORE_SOURCE_DB" <"$RESTORE_FINGERPRINT_SQL")"
RESTORE_FINGERPRINT="$("${restore_compose[@]}" exec -T \
  -e PGOPTIONS='-c default_transaction_read_only=on' pgvector sh -c \
  'psql -X -Atq -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  <"$RESTORE_FINGERPRINT_SQL")"
test "$SOURCE_FINGERPRINT" = "$RESTORE_FINGERPRINT"
  printf 'FINAL_SCHEMA_VERIFIED=true\n'
else
  printf 'FINAL_SCHEMA_UNVERIFIED=true (restauration historique lisible, pas une preuve de release finale)\n'
fi

# Après validation du schéma restauré, détruire la seule fixture isolée.
"${restore_compose[@]}" down -v
```

Ne jamais ajouter `--remove-orphans`. Une restauration réelle de production
reste un human gate distinct : backup frais, arrêt contrôlé des writers,
validation de l'identité de la cible, restauration, migrations via le seul
migrateur, reprovisionnement explicite des rôles runtime, contrôles de schéma,
puis seulement redémarrage des runtimes.

`FINAL_SCHEMA_UNVERIFIED=true` accepte uniquement la lisibilité isolée d'un
ancien dump. Ce verdict ne démontre ni les migrations 005/020, ni le contenu
publié ; il ne peut pas servir de preuve de readiness ou de rollback de la
release finale.

Le dump de la production **avant** le go-live peut encore être une base
historique sans schéma `ingestion_control` ; sa restauration réussie prouve
seulement que ce point de retour est lisible. Elle ne prouve ni le schéma
final, ni les placements et chunks à publier. La sauvegarde prise après
cutover doit associer le dump `ragdb` et le volume d'artefacts au même
instant, puis être restaurée sur une cible isolée et contrôlée avant de
servir la release. Pour cette release, comparer les registres restaurés aux
fichiers canoniques : head produit `005_official_snapshot_currentness` et
head d'ingestion déclaré dans `migrations/HEAD` (actuellement
`020_successor_control_resource_identity`, avec `019` et `020` appliquées et
leurs SHA-256 vérifiés). Si le snapshot est antérieur à ce head, ne pas
démarrer l'API ou les workers : appliquer uniquement les migrations
manquantes avec les runners canoniques sur la cible **isolée**, puis refaire
les contrôles. Ne pas dérouler les fichiers `019`/`020` ni leurs rollbacks
manuellement sur des adoptions existantes.

### Chroma (v1)

```bash
# Arrêter le stack
docker compose down

# Restaurer le volume
bash infra/scripts/restore-volumes.sh /backup/rag_chroma_data.tar.gz

# Relancer
docker compose up -d
```

### Redis (cache — optionnel)

```bash
# Le cache se reconstruit automatiquement.
# Pour forcer un reset :
docker exec rag_redis redis-cli -a "$REDIS_PASSWORD" FLUSHALL
```

## 6. Restauration des collections

```bash
# Si rag_collections.yml a été modifié :
git checkout <commit-precedent> -- configs/rag_collections.yml
git checkout <commit-precedent> -- configs/legacy_collection_mapping.yml

# Redémarrer l'ingestor pour recharger
docker compose restart ingestor
```

## 7. Vérification post-rollback

```bash
# Health check
curl -sf http://localhost:8001/health | jq .

# Search v2 fonctionnel
curl -sf -X POST http://localhost:8001/search/v2 \
  -H "Authorization: Bearer $RAG_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"test","collection":"rag_nexus_nsi_terminale_specialite","k":1}' | jq .

# Collections accessibles
curl -sf http://localhost:8001/collections/v2 \
  -H "Authorization: Bearer $RAG_ADMIN_TOKEN" | jq .

# Logs propres
docker compose logs --tail=20 ingestor | grep -i error

# Governance locks intacts
bash scripts/check-governance-locks.sh
```

## 8. Communication

Après rollback :

1. Notifier l'équipe (canal à définir)
2. Documenter la cause dans un incident report
3. Créer un ticket pour le fix
4. Planifier le re-déploiement après correction

## 9. Prévention

- Toujours faire un backup avant déploiement
- Tester en staging/local avant prod
- Utiliser `make test` et `bash scripts/ci-local.sh` avant push
- Ne jamais modifier `.env` sans backup préalable
