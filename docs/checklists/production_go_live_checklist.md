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
- [ ] `RAG_ENGINE_INTERNAL_TOKEN` côté Cockpit est identique à `RAG_BFF_SERVICE_TOKEN` côté moteur et distinct de tous les tokens humains
- [ ] Les secrets de session Auth.js et de signature d'identité interne sont configurés, non versionnés et distincts des credentials moteur
- [ ] `INGESTOR_API_TOKEN` / `INGEST_AUTH_TOKEN` peuvent être identiques (même rôle)
- [ ] `.env` mode 0600, non versionné
- [ ] Aucun secret dans le repo Git

## Configuration

- [ ] Cockpit HTTPS et routes BFF déployés ; le runbook historique ne les provisionne pas
- [ ] Préflight de la [configuration d'identité serveur](../../services/cockpit/README.md) exécuté sans afficher de secret
- [ ] `NEXUS_COCKPIT_PUBLIC_ORIGIN` égale exactement l'origine publique HTTPS canonique du Cockpit, sans credentials, chemin, query ni fragment
- [ ] `RAG_ENV=production` dans `.env`
- [ ] `ALLOW_UNAUTHENTICATED_ADMIN_DEV=false`
- [ ] `RAG_ENGINE_CONFIG_DIR=/app/configs`
- [ ] `INGESTOR_IP_ALLOWLIST` contient uniquement les CIDR clients réels autorisés
- [ ] `INGESTOR_IP_ALLOWLIST` ne contient pas `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` sauf justification écrite
- [ ] `INGESTOR_TRUSTED_PROXY_CIDRS` contient uniquement la gateway Compose / reverse proxy exact en `/32`
- [ ] `RERANK_SCORE_THRESHOLD=1.90`
- [ ] Search cache production désactivé (`RERANK_CACHE` absent ou `0`) sauf si invalidation cross-worker validée

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
- [ ] `nexus-contracts==0.5.0` est installé côté moteur et ses cinq schémas de review sont générés côté Cockpit
- [ ] `GET /api/review/queue` avec session Auth.js `reviewer` ou `admin` → 200
- [ ] `POST /api/review/decide` avec session Auth.js `reviewer` ou `admin` → 200
- [ ] Cookie jars Netscape de test obtenus par le provider Credentials Auth.js avec des jetons SSO Nexus éphémères ; aucun JWT/cookie fabriqué manuellement
- [ ] Toutes les réponses `/api/review/*` portent `Cache-Control: private, no-store, max-age=0`
- [ ] `POST /api/review/decide` avec session Auth.js `student` → 403 avant appel moteur
- [ ] `POST /api/review/decide` avec session Auth.js `teacher` → 403 avant appel moteur
- [ ] `GET /review/v2/queue` direct avec un simple token reviewer humain → 401 faute de credential BFF et d'identité signée
- [ ] `POST /review/v2/decide` direct avec un simple token reviewer humain → 401 faute de credential BFF et d'identité signée
- [ ] Quarantine collection → 403 sur `/search/v2`

## Validation RAG

- [ ] Ingestion d'un document test → `review_status = 'needs_review'`
- [ ] Approbation via `/api/review/decide` → chaîne `needs_review → reviewed`
- [ ] Quarantaine via `/api/review/decide` → chaîne `needs_review|reviewed → quarantined`
- [ ] `/search/v2` retourne le document approuvé
- [ ] `/search/v2` ne retourne PAS les documents `needs_review`
- [ ] Le document `quarantined` n'est pas retourné par `/search/v2`

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
