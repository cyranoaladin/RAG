# LOT 26.4 — Redis Audit

**Date** : 2026-07-13

## Rôle dans l'architecture

Redis est utilisé activement dans le stack v2 pour :

1. **Cache embeddings** — `embedding_service.py:13,110-146` : cache async des vecteurs d'embedding via `redis.asyncio`, clé = hash du texte, TTL configurable via `EMBED_CACHE_TTL`.
2. **Broker Celery** — `tasks.py:20` : `broker=REDIS_URL` pour la queue d'ingestion async.
3. **Backend Celery** — `tasks.py:21` : `backend=REDIS_URL` pour les résultats des tâches.

## Verdict

```text
PASS
```

Redis est un composant actif et nécessaire du stack v2.

## Configuration

| Paramètre | Valeur | Source |
|-----------|--------|--------|
| Image | `redis:7-alpine` | `docker-compose.v2.yml:55` |
| Port host | `127.0.0.1:6381` | `docker-compose.v2.yml:67` — loopback |
| Password | `${REDIS_PASSWORD:?requis}` | `docker-compose.v2.yml:60` — obligatoire |
| Max memory | 1 GB | `docker-compose.v2.yml:62` — `--maxmemory 1gb` |
| Eviction | `allkeys-lru` | `docker-compose.v2.yml:63` — empêche OOM |
| Persistence | AOF (`--appendonly yes`) | `docker-compose.v2.yml:64` |
| Volume | `rag_redis_data:/data` | `docker-compose.v2.yml:65` |
| CPU limit | 0.5 | `docker-compose.v2.yml:83` |
| Memory limit | 1536M | `docker-compose.v2.yml:84` |
| Healthcheck | `redis-cli -a $REDIS_PASSWORD ping` | `docker-compose.v2.yml:70` |

## Sécurité

- Port non exposé publiquement (127.0.0.1 uniquement)
- Password requis (`REDIS_PASSWORD:?requis` — fail si absent)
- `security_opt: [no-new-privileges:true]`
- Réseau interne `rag_net` uniquement

## Backup

- Volume `rag_redis_data` inclus dans `backup-volumes.sh`
- Persistance AOF : données survivent au redémarrage
- Restore : via `restore-volumes.sh` ou copie du volume

## Fallback si Redis absent

- `embedding_service.py:54-56` : si connexion Redis échoue, cache désactivé silencieusement (`self._redis = None`). Les embeddings sont recalculés à chaque requête.
- `tasks.py` : Celery ne démarre pas si Redis absent (worker crash au boot). Impact : pas d'ingestion async, mais l'ingestion synchrone via API reste fonctionnelle.

## Risques

Aucun risque P1/P2/P3 identifié. Redis est correctement configuré, sécurisé, et sauvegardé.
