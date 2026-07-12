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

```bash
# Arrêter le stack
docker compose -f docker-compose.v2.yml down

# Restaurer depuis backup SQL
docker compose -f docker-compose.v2.yml up -d pgvector
sleep 10  # Attendre que pgvector soit healthy

docker exec -i rag_pgvector psql -U raguser ragdb < /backup/ragdb_YYYYMMDD.sql

# Relancer le reste
docker compose -f docker-compose.v2.yml up -d
```

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
