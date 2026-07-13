# LOT 26.4 — Go-Live Evidence Matrix

**Date** : 2026-07-13
**Head** : `a39bfa2` + round 3

---

| # | Domaine | Exigence | Preuve code/doc/test | Commande validation | Statut |
|---|---------|----------|---------------------|---------------------|--------|
| 1 | Frontend | Token jamais affiché/loggé | `app_v2.py:136-141` — token uniquement dans headers HTTP (`Authorization: Bearer`). Aucun `st.write(TOKEN)`, `print(TOKEN)`, `logging.*TOKEN` | `grep -n "API_TOKEN" services/rag-engine/src/ui/app_v2.py` | PASS |
| 2 | Frontend | Pas de CDN externe | `app_v2.py:518` — emoji local `🧠`, pas d'URL `img.icons8.com` | `grep "icons8" services/rag-engine/src/ui/app_v2.py; echo $?` → 1 | PASS |
| 3 | Frontend | Pas de faux .env avec token | `src/ui/.env` supprimé, `.env.example` avec valeurs vides | `ls services/rag-engine/src/ui/.env` → erreur | PASS |
| 4 | Frontend | /search/v2 uniquement | `app_v2.py:375` — appelle `/search/v2`, aucun appel `/search` legacy | `grep "/search" services/rag-engine/src/ui/app_v2.py` | PASS |
| 5 | Backend | /docs /redoc disabled prod | `api.py:309-314` — `docs_url=None`, `redoc_url=None`, `openapi_url=None` quand `RAG_ENV=production` | `grep "docs_url" services/rag-engine/src/ingestor/api.py` | PASS |
| 6 | Backend | hmac.compare_digest admin | `admin_api.py:89` — `hmac.compare_digest(header_token, token_env)` | `grep "compare_digest" services/rag-engine/src/ingestor/admin_api.py` | PASS |
| 7 | Backend | Erreurs sans str(exc) | `admin_api.py` — 5 messages sanitisés : `"Admin ingest failed"`, `"Failed to save upload"`, `"Invalid tags format"`, `"Invalid metadata format"`, `"Ingestion trigger failed"` | `grep 'detail=f.*exc' services/rag-engine/src/ingestor/admin_api.py; echo $?` → 1 | PASS |
| 8 | Backend | /metrics restreint Nginx | `rag-v2.conf:67-71`, `rag-api.conf.template` — `allow 127.0.0.1; deny all;` | `grep -A2 "/metrics" services/rag-engine/infra/nginx/rag-v2.conf` | PASS |
| 9 | Backend | Auth centralisée v2 | `security_v2.py:140-200` — `require_role()` avec `hmac.compare_digest()` | test `test_security_v2.py` (39 tests) | PASS |
| 10 | Backend | Fail-closed config manquante | `retrieval_v2_endpoint.py:149-157` — 503 si `PG_RAG_DSN` absent | test `test_retrieval_v2_endpoint.py` | PASS |
| 11 | RAG | /search/v2 reviewed-only | `retrieval_v2_endpoint.py:344` — SQL `WHERE ... review_status = 'reviewed'` | `grep "needs_review" retrieval_v2_endpoint.py` → invariant check | PASS |
| 12 | RAG | Cache disabled prod | `retrieval_v2_endpoint.py:57-60` — `CACHE_ENABLED = RERANK_CACHE default "0"` en production | test `test_search_cache_disabled_in_production` | PASS |
| 13 | RAG | Reranker seuil documenté | `retrieval_v2_endpoint.py:118` — `RERANK_SCORE_THRESHOLD = 1.90` (LAT-05) | docs `README-PROD.md` | PASS |
| 14 | RAG | Embeddings cohérents | `retrieval_v2_endpoint.py:120,128` — `intfloat/multilingual-e5-large` (1024D), même modèle ingest/search | `grep EMBED_MODEL retrieval_v2_endpoint.py` | PASS |
| 15 | Collections | Quarantine non-retrievable | `configs/rag_collections.yml` — `quarantine: {retrievable: false}` | `grep -A1 "quarantine" configs/rag_collections.yml` | PASS |
| 16 | Collections | /collections/v2 filtre retrievable | `retrieval_v2_endpoint.py:400` — `if domain_cfg.get("retrievable") is not True: continue` | test `test_retrieval_v2_endpoint.py` | PASS |
| 17 | Collections | Mapping legacy sûr | `legacy_collection_mapping.yml` — `rag_divers: rag_nexus_quarantine` → 403 | test `test_prod_compose_config_mount.py` | PASS |
| 18 | Ingestion | Chunks = needs_review | `ingest_v2.py:121,256` — `review_status = 'needs_review'` hardcodé | test `test_ingest_v2.py` | PASS |
| 19 | Ingestion | SSRF protection | `ingest_v2_endpoint.py:47-66` — bloque private IP, loopback, metadata.google.internal | test `test_ingestor_unit.py` | PASS |
| 20 | Ingestion | Dedup deterministic | `ingest_v2.py:256` — `ON CONFLICT (chunk_id) DO UPDATE` + `chunk_sha256` | test `test_ingest_v2.py` | PASS |
| 21 | Review | Queue roles stricts | `review_v2_endpoint.py` — queue: admin/reviewer/teacher, decide: admin/reviewer | test `test_review_v2.py` (18 tests) | PASS |
| 22 | Review | Decide = reviewed/quarantined | `review_v2_endpoint.py` — SQL `UPDATE ... SET review_status = %s WHERE review_status = 'needs_review'` | test `test_review_v2.py` | PASS |
| 23 | Agents | Worker Celery sécurisé | `tasks.py:20-21` — broker/backend Redis avec password | `docker-compose.v2.yml` worker service | PASS |
| 24 | Agents | Pas de secret hardcodé | Aucun token dans scripts ou workflows | `grep -r "secret\|token" .github/workflows/` | PASS |
| 25 | LLM | EMBED_MODEL documenté | `retrieval_v2_endpoint.py:120` — `intfloat/multilingual-e5-large` | `README-PROD.md`, `go_live.md` | PASS |
| 26 | LLM | Ollama healthcheck | `docker-compose.v2.yml` — `curl -sf http://localhost:11434/api/tags` | compose healthcheck | PASS |
| 27 | LLM | Pas d'appel cloud | Aucun appel OpenAI/Anthropic/cloud dans src/ingestor | `grep -r "openai\|anthropic\|api.openai" services/rag-engine/src/ingestor/` | PASS |
| 28 | Routing | Ports loopback | `docker-compose.v2.yml` — tous les `ports:` en `127.0.0.1:` | test `test_prod_preflight_check.py` (loopback check) | PASS |
| 29 | Routing | Pas de hardcoded IP | `rag-v2.conf` — `88.99.254.59` supprimé | audit invariant | PASS |
| 30 | Routing | X-Real-IP non utilisé app | Aucune occurrence dans `src/ingestor/*.py` | `grep "X-Real-IP" services/rag-engine/src/ingestor/*.py` → vide | PASS |
| 31 | Routing | XFF gated trusted proxy | `security_v2.py:222-230` — XFF seulement si peer dans trusted_proxy_networks | test `test_security_v2.py` | PASS |
| 32 | Compose | Containers hardened | `docker-compose.v2.yml` — `security_opt: [no-new-privileges:true]`, `read_only: true` | test `test_prod_compose_config_mount.py` | PASS |
| 33 | Compose | Healthchecks tous services | pgvector, redis, ollama, ingestor, ui — tous avec healthcheck | compose YAML | PASS |
| 34 | Compose | Startup orchestré | `depends_on: condition: service_healthy` | compose YAML | PASS |
| 35 | Postgres | Password requis | `docker-compose.v2.yml` — `PGVECTOR_PASSWORD: ${PGVECTOR_PASSWORD:?requis}` | compose validation | PASS |
| 36 | Redis | Password requis | `docker-compose.v2.yml:60` — `--requirepass ${REDIS_PASSWORD:?requis}` | compose YAML | PASS |
| 37 | Redis | Port loopback | `docker-compose.v2.yml:67` — `127.0.0.1:6381:6379` | compose YAML | PASS |
| 38 | Redis | Volume sauvegardé | `backup-volumes.sh` — `rag_redis_data` inclus | `grep redis backup-volumes.sh` | PASS |
| 39 | Redis | Healthcheck | `docker-compose.v2.yml:70` — `redis-cli -a $REDIS_PASSWORD ping` | compose YAML | PASS |
| 40 | Secrets | Aucun secret dans repo | `.env` non versionné, `.env.example` valeurs vides | `git ls-files | grep "\.env$"` → vide | PASS |
| 41 | Secrets | Tokens 64-hex | `provision-prod.sh:245-253` — `generate_hex 32` pour tous les tokens | test `test_prod_preflight_check.py` | PASS |
| 42 | Secrets | LEGACY_ADMIN distinct | `prod_preflight_check.py:87-90` — vérifie distinctness | test `test_prod_preflight_check.py` | PASS |
| 43 | Secrets | Allowlist restrictive | `provision-prod.sh` — `ALLOWLIST_DEFAULT="127.0.0.1/32"` | test + audit invariant | PASS |
| 44 | Secrets | Trusted proxy restrictif | `provision-prod.sh` — `TRUSTED_PROXY_CIDRS_DEFAULT="127.0.0.1/32"`, pas de docker0 | test + audit invariant | PASS |
| 45 | Backups | Volumes v1+v2 inclus | `backup-volumes.sh` — chroma, ollama, n8n, pgvector, redis, admin | `cat backup-volumes.sh` | PASS |
| 46 | Backups | Restore documenté | `docs/runbooks/rollback.md` — procédure pgvector, chroma, redis | document | PASS |
| 47 | Observabilité | Healthchecks Docker | Tous services avec healthcheck dans compose | compose YAML | PASS |
| 48 | Observabilité | Logs sans token | `admin_api.py` — `header_provided: bool(token)`, jamais la valeur | code review | PASS |
| 49 | Observabilité | Alert rules | `prometheus/rules/rag-alerts.yml` — disponibilité, erreurs, latence, sécurité | fichier existant | PASS |
| 50 | Observabilité | Incident response | `docs/runbooks/rag_incident_response.md` — classification, diagnostic, escalade | document | PASS |
| 51 | Runbooks | Go-live complet | `docs/runbooks/go_live.md` — 13 étapes, smoke tests, HSTS post-TLS | document | PASS |
| 52 | Runbooks | Rollback complet | `docs/runbooks/rollback.md` — compose, image, config, volumes, Nginx | document | PASS |
| 53 | CI | Tests verts | 7/7 ci-local.sh, CI GitHub 5/5 | `bash scripts/ci-local.sh` | PASS |
| 54 | CI | Governance locks | 18 clés vérifiées, ADR référencés | `bash scripts/check-governance-locks.sh` | PASS |
| 55 | CI | Audit script | `scripts/audit/rag-pr-audit.sh` — 12+ invariants vérifiés | `bash scripts/audit/rag-pr-audit.sh` | PASS |
| 56 | Observabilité | Alertmanager | Non configuré — configuration opérateur au déploiement | Documenté dans checklist | NEEDS_OPERATOR_CONFIGURATION |
