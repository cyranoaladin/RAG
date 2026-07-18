# Runbook Go-Live — Plateforme RAG

## Prérequis

- Serveur Ubuntu 22.04/24.04 provisionné
- DNS configuré pour les domaines RAG
- Ports 80/443 ouverts
- Accès SSH opérationnel
- Repo cloné sur le serveur

## 1. Provisionnement automatisé

```bash
cd /opt/rag-local
sudo bash services/rag-engine/infra/scripts/provision-prod.sh
```

Le script demande interactivement :
- Domaine Streamlit (ex: `rag.nexusreussite.academy`)
- Domaine n8n (optionnel)
- Email Certbot
- CIDR allowlist ingestor
- CIDR trusted proxy
- Basic Auth UI (optionnel)

## 2. Provisionnement manuel (alternative)

```bash
cd /opt/rag-local/services/rag-engine/infra

# Copier et éditer .env
cp .env.example .env
chmod 600 .env

# Générer les tokens
for var in LEGACY_ADMIN_API_TOKEN RAG_ADMIN_TOKEN RAG_REVIEWER_TOKEN \
  RAG_TEACHER_TOKEN RAG_INGEST_AGENT_TOKEN INGESTOR_API_TOKEN \
  INGEST_AUTH_TOKEN RAG_STUDENT_TOKEN; do
  echo "${var}=$(openssl rand -hex 32)"
done >> .env

# Configurer les variables obligatoires dans .env :
# RAG_ENV=production
# ALLOW_UNAUTHENTICATED_ADMIN_DEV=false
# RAG_ENGINE_CONFIG_DIR=/app/configs
# PGVECTOR_PASSWORD=<generated>
# REDIS_PASSWORD=<generated>
```

## 3. Lancement du stack

```bash
# Stack v2 (pgvector)
docker compose -f docker-compose.v2.yml up -d --build

# OU stack prod (Chroma)
docker compose -f docker-compose.prod.yml --profile db --profile llm \
  --profile api --profile ui --profile obs up -d
```

## 3b. Appliquer les migrations pgvector (volumes existants)

Si le volume pgvector existe déjà (upgrade, pas premier déploiement),
appliquer les migrations versionnées **avant** les smoke tests :

```bash
cd services/rag-engine/infra
chmod +x scripts/apply_pgvector_migrations.sh
BACKUP_ROOT=/backup/rag ./scripts/apply_pgvector_migrations.sh
```

`BACKUP_ROOT` is required — the script will refuse to run without it.

Le script :
- crée un backup automatique (`pg_dump -Fc`) ;
- applique les migrations SQL triées depuis `postgres/migrations/` ;
- vérifie que le schéma v2 est en place (colonnes + `vector(1024)`).

Si la migration échoue (legacy avec données), elle bloque avec un message
explicite. Ne pas poursuivre sans résolution.

## 4. Vérification des services

```bash
docker compose ps
# Tous les services doivent être "healthy"

# Health check API
curl -sf http://localhost:8001/health | jq .

# Health check UI
curl -sf http://localhost:8501/_stcore/health
```

## 5. Preload des modèles

```bash
# Embedding model
docker exec rag_ollama ollama pull intfloat/multilingual-e5-large

# Vérification
docker exec rag_ollama ollama list
```

## 6. Configuration Nginx

```bash
# Si provision-prod.sh n'a pas été utilisé :
cd infra
set -a; . ./.env; set +a
envsubst < nginx/rag-ui.conf.template > nginx/rendered/rag-ui.conf
envsubst < nginx/rag-api.conf.template > nginx/rendered/rag-api.conf

sudo cp nginx/rendered/*.conf /etc/nginx/sites-available/
sudo ln -sf /etc/nginx/sites-available/rag-ui.conf /etc/nginx/sites-enabled/
sudo ln -sf /etc/nginx/sites-available/rag-api.conf /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

## 7. TLS (Certbot)

```bash
sudo certbot --nginx --non-interactive --agree-tos --redirect \
  -m admin@example.com -d rag.example.com -d rag-api.example.com
```

## 8. Smoke tests post-déploiement

```bash
API="https://rag-api.example.com"
TOKEN="<RAG_ADMIN_TOKEN>"

# Health
curl -sf "$API/health" | jq .

# Search v2 (admin)
curl -sf -X POST "$API/search/v2" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"q":"test","collection":"rag_nexus_nsi_terminale_specialite","k":3}' | jq .

# Collections v2
curl -sf "$API/collections/v2" \
  -H "Authorization: Bearer $TOKEN" | jq .

# Search sans token (doit retourner 401)
curl -s -o /dev/null -w "%{http_code}" -X POST "$API/search/v2" \
  -H "Content-Type: application/json" \
  -d '{"q":"test","collection":"rag_nexus_nsi_terminale_specialite","k":3}'
# Attendu : 401
```

## 9. Ingestion initiale

```bash
INGEST_TOKEN="<RAG_INGEST_AGENT_TOKEN>"

# Upload d'un fichier test
curl -X POST "$API/ingest/v2/upload-files" \
  -H "Authorization: Bearer $INGEST_TOKEN" \
  -F "files=@/tmp/test_cours.md" \
  -F "collection=rag_nexus_nsi_terminale_specialite" \
  -F "source_label=Test cours NSI" \
  -F "source_uri=file:///test_cours.md" \
  -F "rights=nexus_owned" \
  -F "type_doc=cours" | jq .
```

## 10. Revue initiale

```bash
REVIEWER_TOKEN="<RAG_REVIEWER_TOKEN>"

# Queue de review
curl -sf "$API/review/v2/queue" \
  -H "Authorization: Bearer $REVIEWER_TOKEN" | jq .

# Approuver un document
curl -X POST "$API/review/v2/decide" \
  -H "Authorization: Bearer $REVIEWER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"target_type":"doc","target_id":"<doc_id>","decision":"reviewed"}' | jq .
```

## 11. Backup initial

```bash
# Backup volumes
bash infra/scripts/backup-volumes.sh

# Pour v2 (pgvector) :
docker exec rag_pgvector pg_dump -U raguser ragdb > /backup/ragdb_$(date +%Y%m%d).sql
```

## 12. Systemd (auto-start)

```bash
RAG_DIR=/opt/rag-local sudo bash infra/scripts/install-systemd.sh
sudo systemctl enable rag-local
sudo systemctl status rag-local
```

## 13. Validation finale

- [ ] HTTPS fonctionnel sur les deux domaines
- [ ] Search v2 retourne des résultats après ingestion + review
- [ ] Tokens distincts entre rôles
- [ ] Logs propres (`docker compose logs --tail=50 ingestor`)
- [ ] Aucun token visible dans les logs
- [ ] Backup effectué

## 14. Validation complète (régression)

La commande officielle de régression complète est :

```bash
make full-regression
```

Elle exécute depuis la racine du repo :

1. `scripts/check-governance-locks.sh` — verrous de gouvernance
2. `scripts/tests/test-governance-locks.sh` — tests des verrous
3. `git diff --check` — vérification whitespace
4. `services/rag-engine` : lint, typecheck, test
5. `services/rag-pedago` : lint, typecheck, test

Les suites Python réelles restent service-scopées : chaque service a son propre
venv et ses propres tests. Ne pas lancer `python -m pytest` depuis la racine
pour exécuter les tests des services — utiliser `make full-regression` à la place.

### E2E production (read-only)

```bash
bash scripts/e2e/run-rag-v2-prod-readonly.sh
```

Vérifie Dashboard, Administration, Collections v2, et soumission Recherche
sans aucune mutation. Nécessite Playwright (`bash scripts/e2e/setup-playwright.sh`).

### Vérification zombies / doublons

```bash
bash scripts/tests/check-zombies-and-duplicates.sh
```

Contrôle l'absence de processus zombies locaux et de conteneurs dupliqués en production.

## Contacts

- Lead technique : à définir
- Oncall : à définir
- Alertes : à configurer via Alertmanager
