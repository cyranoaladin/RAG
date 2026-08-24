# Runbook Rollback — Plateforme RAG

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
cd services/rag-engine/infra

# Valeurs explicites : jamais le projet production, jamais le projet infra.
RESTORE_PROJECT="nexus-pg-restore-rehearsal-$(date -u +%Y%m%dT%H%M%SZ)"
RESTORE_BACKUP_FILE=/backup/rag/pgvector-migration-YYYYMMDD/ragdb-before-migrations.dump
umask 077
RESTORE_FIXTURE_DIR="$(mktemp -d)"
RESTORE_COMPOSE="$RESTORE_FIXTURE_DIR/compose.yml"
test -f "$RESTORE_BACKUP_FILE"
test "$RESTORE_PROJECT" != infra
test "$RESTORE_PROJECT" != production

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
      PGPASSWORD: ${PGVECTOR_PASSWORD:?PGVECTOR_PASSWORD requis}
    networks: [restore_net]
    entrypoint: ["pg_restore"]
    security_opt: [no-new-privileges:true]
networks:
  restore_net: {}
volumes:
  restore_pgvector_data: {}
YAML

restore_compose=(
  docker compose -p "$RESTORE_PROJECT" --env-file .env
  -f "$RESTORE_COMPOSE"
)

cleanup_restore_fixture() {
  "${restore_compose[@]}" down -v >/dev/null 2>&1 || true
  rm -f -- "$RESTORE_COMPOSE"
  rmdir -- "$RESTORE_FIXTURE_DIR" 2>/dev/null || true
}
trap cleanup_restore_fixture EXIT

# Refuser toute extension accidentelle de la fixture avant sa création.
test "$("${restore_compose[@]}" config --services)" = \
  $'pgvector\nrestore-migrator'

# Vérifier que le fichier est bien un dump custom avant de créer la fixture.
"${restore_compose[@]}" run --rm --no-deps \
  --volume "$RESTORE_BACKUP_FILE:/restore/source.dump:ro" \
  restore-migrator \
  --list --format=custom /restore/source.dump >/dev/null

# Démarrer uniquement PostgreSQL, puis restaurer avec le client migrateur.
"${restore_compose[@]}" up -d --wait pgvector
"${restore_compose[@]}" run --rm --no-deps \
  --volume "$RESTORE_BACKUP_FILE:/restore/source.dump:ro" \
  restore-migrator \
  --exit-on-error --clean --if-exists --no-owner --no-privileges \
  --single-transaction --format=custom --host=pgvector \
  --username="${PGVECTOR_USER:-raguser}" \
  --dbname="${PGVECTOR_DB:-ragdb}" /restore/source.dump

# Aucun service applicatif ne doit exister dans le projet de rehearsal.
test "$("${restore_compose[@]}" ps --services --status running)" = pgvector

# Après validation du schéma restauré, détruire la seule fixture isolée.
"${restore_compose[@]}" down -v
```

Ne jamais ajouter `--remove-orphans`. Une restauration réelle de production
reste un human gate distinct : backup frais, arrêt contrôlé des writers,
validation de l'identité de la cible, restauration, migrations via le seul
migrateur, contrôles de schéma, puis seulement redémarrage des runtimes.

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
