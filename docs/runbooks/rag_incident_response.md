# Runbook Incident Response — Plateforme RAG

## Classification des incidents

| Sévérité | Critère | Exemples |
|----------|---------|----------|
| P1 | Service totalement indisponible | API down, toutes les requêtes 500 |
| P2 | Fonctionnalité critique dégradée | Search KO, ingestion KO, review KO |
| P3 | Fonctionnalité secondaire dégradée | Stats KO, cache KO, UI lente |
| P4 | Anomalie sans impact utilisateur | Log warning, métrique anormale |

## Diagnostic rapide

### 1. Vérifier l'état des services

```bash
cd /opt/rag-local/services/rag-engine/infra
docker compose ps
docker compose logs --tail=50 ingestor
docker compose logs --tail=50 pgvector
docker compose logs --tail=50 ollama
```

### 2. Vérifier les healthchecks

```bash
curl -sf http://localhost:8001/health | jq .
curl -sf http://localhost:8501/_stcore/health
docker exec rag_pgvector pg_isready -U raguser -d ragdb
docker exec rag_redis redis-cli -a "$REDIS_PASSWORD" ping
```

### 3. Vérifier les métriques

```bash
curl -sf http://localhost:8001/metrics | grep -E "error|failure|violation"
```

## Cas fréquents

### API retourne 503

**Causes possibles :**
- Token collision entre rôles v2
- `PG_RAG_DSN` non configuré
- Trusted proxy CIDR invalide
- Service dépendant down (pgvector, Ollama)

**Diagnostic :**
```bash
docker compose logs --tail=20 ingestor | grep -i "503\|collision\|configured\|proxy"
```

**Résolution :**
- Vérifier unicité des tokens dans `.env`
- Vérifier que pgvector est healthy
- Vérifier `INGESTOR_TRUSTED_PROXY_CIDRS`

### Search retourne 0 résultats

**Causes possibles :**
- Aucun document avec `review_status = 'reviewed'`
- Collection non instanciée
- Modèle embedding non chargé

**Diagnostic :**
```bash
# Vérifier les documents reviewed
docker exec rag_pgvector psql -U raguser ragdb -c \
  "SELECT review_status, count(*) FROM rag_chunks GROUP BY review_status;"

# Vérifier le modèle
docker exec rag_ollama ollama list
```

### Ingestion échoue

**Causes possibles :**
- Token incorrect (401)
- IP hors allowlist (403)
- pgvector down (503)
- Fichier trop volumineux

**Diagnostic :**
```bash
docker compose logs --tail=30 ingestor | grep -i "ingest\|401\|403\|503"
```

### Violations de sécurité détectées

**Diagnostic :**
```bash
curl -sf http://localhost:8001/metrics | grep security_violations
docker compose logs ingestor | grep "security_violation"
```

**Actions :**
1. Identifier l'IP source
2. Vérifier si l'allowlist est correcte
3. Si attaque : bloquer l'IP au niveau Nginx ou firewall
4. Documenter l'incident

## Escalade

| Sévérité | Délai réponse | Action |
|----------|---------------|--------|
| P1 | 15 min | Rollback immédiat si nécessaire |
| P2 | 1h | Diagnostic + fix ou rollback |
| P3 | 4h | Diagnostic + planification fix |
| P4 | 24h | Ticket + monitoring |

## Post-incident

1. Documenter dans `docs/reports/incident_YYYY-MM-DD.md`
2. Identifier la root cause
3. Créer ticket pour fix permanent
4. Mettre à jour les alertes si nécessaire
5. Communiquer le post-mortem à l'équipe
