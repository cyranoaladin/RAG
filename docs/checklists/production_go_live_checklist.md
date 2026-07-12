# Checklist Go-Live Production — Plateforme RAG

## Prérequis infrastructure

- [ ] Serveur Ubuntu 22.04 ou 24.04 disponible
- [ ] 8+ vCPU, 32+ GB RAM, 100+ GB SSD
- [ ] Ports 80/443 ouverts (Nginx + Certbot)
- [ ] DNS A/AAAA configurés pour `RAG_DOMAIN` et `RAG_API_DOMAIN`
- [ ] Accès SSH opérationnel (provisionnement uniquement)

## Secrets et tokens

- [ ] `provision-prod.sh` exécuté OU tokens générés manuellement (`openssl rand -hex 32`)
- [ ] Tous les tokens 64-hex distincts entre rôles v2
- [ ] `LEGACY_ADMIN_API_TOKEN` distinct de tous les tokens v2
- [ ] `RAG_REVIEWER_TOKEN` / `REVIEWER_API_TOKEN` peuvent être identiques (même rôle)
- [ ] `INGESTOR_API_TOKEN` / `INGEST_AUTH_TOKEN` peuvent être identiques (même rôle)
- [ ] `.env` mode 0600, non versionné
- [ ] Aucun secret dans le repo Git

## Configuration

- [ ] `RAG_ENV=production` dans `.env`
- [ ] `ALLOW_UNAUTHENTICATED_ADMIN_DEV=false`
- [ ] `RAG_ENGINE_CONFIG_DIR=/app/configs`
- [ ] `INGESTOR_IP_ALLOWLIST` configuré selon réseau
- [ ] `INGESTOR_TRUSTED_PROXY_CIDRS` restreint (loopback + bridge Docker en /32)
- [ ] `RERANK_SCORE_THRESHOLD=1.90`
- [ ] `RERANK_CACHE_TTL=300` (ou 60 pour invalidation plus rapide)

## Docker compose

- [ ] `docker compose -f docker-compose.prod.yml up -d` ou `make v2-up`
- [ ] Tous les services healthy (`docker compose ps`)
- [ ] Ports host en loopback uniquement (127.0.0.1)
- [ ] Volumes persistants montés correctement
- [ ] Configs montées en read-only (`/app/configs:ro`)

## Nginx / TLS

- [ ] Templates rendus (`envsubst`)
- [ ] Configs déployées dans `/etc/nginx/sites-enabled/`
- [ ] `nginx -t` passe
- [ ] Certbot exécuté avec succès (certificats valides)
- [ ] HTTPS fonctionnel sur les deux domaines
- [ ] Rate limiting actif (20 r/s API, 5 r/s ingest)
- [ ] `/metrics` restreint à 127.0.0.1

## Modèles LLM / embeddings

- [ ] Ollama démarré et healthy
- [ ] Modèle embedding chargé : `ollama pull intfloat/multilingual-e5-large`
- [ ] Reranker chargé automatiquement au premier appel

## Smoke tests

- [ ] `GET /health` → 200 `{"status": "ok"}`
- [ ] `POST /search/v2` avec token admin → 200 (résultats ou liste vide)
- [ ] `POST /search/v2` sans token → 401
- [ ] `POST /search/v2` avec token invalide → 401
- [ ] `GET /collections/v2` avec token → 200 (liste collections)
- [ ] `POST /ingest/v2/upload-files` avec token ingest_agent → 200/202
- [ ] `POST /ingest/v2/upload-files` avec token student → 403
- [ ] `GET /review/v2/queue` avec token reviewer → 200
- [ ] `GET /review/v2/queue` avec token student → 403
- [ ] `POST /review/v2/decide` avec token teacher → 403
- [ ] Quarantine collection → 403 sur `/search/v2`

## Validation RAG

- [ ] Ingestion d'un document test → `review_status = 'needs_review'`
- [ ] Approbation via `/review/v2/decide` → `review_status = 'reviewed'`
- [ ] `/search/v2` retourne le document approuvé
- [ ] `/search/v2` ne retourne PAS les documents `needs_review`
- [ ] Quarantine via `/review/v2/decide` → document non trouvé dans search

## Observabilité

- [ ] Prometheus scrape l'ingestor (`/metrics`)
- [ ] Alertes définies dans `prometheus/rules/rag-alerts.yml`
- [ ] Logs lisibles (`docker compose logs ingestor`)
- [ ] Aucun token visible dans les logs

## Backup

- [ ] Script de backup fonctionnel pour volumes v2
- [ ] Premier backup effectué après déploiement
- [ ] Procédure de restore documentée et testée

## Gouvernance

- [ ] `bash scripts/check-governance-locks.sh` → PASS
- [ ] 18 verrous vérifiés
- [ ] Aucun verrou modifié sans ADR

## Décision finale

- [ ] Tous les points ci-dessus cochés
- [ ] Rapport `lot_26_4_production_readiness.md` complété
- [ ] Runbook go-live et rollback relus par l'équipe
- [ ] **GO_LIVE_READY** confirmé par le lead
