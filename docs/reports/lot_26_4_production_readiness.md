# LOT 26.4 — Production Go-Live Readiness

**Date** : 2026-07-12
**Branche** : `codex/lot26-4-production-go-live-readiness`
**Statut** : audit initial

---

## Résumé exécutif

Audit complet de la plateforme RAG pour évaluer la capacité de mise en production. 16 domaines audités. Aucun P1 bloquant identifié. Plusieurs P2/P3 documentés comme dette technique acceptable pour un déploiement contrôlé en environnement interne/protégé.

## Périmètre audité

| Domaine | Fichiers principaux | Verdict |
|---------|-------------------|---------|
| Frontend / UI | `services/rag-engine/src/ui/` | OK avec P3 |
| Backend API | `services/rag-engine/src/ingestor/` | OK avec P3 |
| RAG retrieval | `retrieval_v2_endpoint.py` | OK |
| Collections | `configs/rag_collections.yml` | OK |
| Ingestion | `ingest_v2_endpoint.py`, `ingest_v2.py` | OK |
| Review workflow | `review_v2_endpoint.py` | OK |
| Agents / orchestration | workers, n8n, scripts | OK |
| LLM / embeddings / reranking | Ollama, e5-large, MiniLM | OK |
| Routing API / Nginx | `infra/nginx/` | OK avec P3 |
| Docker compose | `infra/docker-compose.*.yml` | OK |
| Configuration prod | `.env.example`, `provision-prod.sh` | OK |
| Secrets | tokens 64-hex, `.gitignore`, 0600 | OK |
| Observabilité | Prometheus, alertes, métriques | OK |
| Tests | 1 199 tests, CI 7/7 | OK |
| Documentation | README-PROD.md, admin_api.md | OK |
| Governance | 18 verrous, ADR | OK |

## Architecture actuelle

```
services/rag-pedago/   — plan de contrôle : gouvernance, taxonomie
services/rag-engine/   — plan de données : pgvector, retrieval v2, ingestion, review
  src/ingestor/        — API FastAPI (search, ingest, review, admin)
  src/ui/              — Streamlit dashboard (app_v2.py)
  infra/               — Docker compose, Nginx, scripts
packages/contracts/    — nexus-contracts (RetrievalRequest → RetrievalResponse)
```

## Frontend

- **app_v2.py** : dashboard Streamlit production (1 001 lignes)
- Utilise `/search/v2`, `/collections/v2` — pas de fallback legacy
- Token envoyé uniquement dans headers HTTP, jamais loggé ni affiché
- Erreurs API tronquées à 200 caractères
- P3 : messages d'erreur 401/403/503 génériques (pas de guidance utilisateur)
- P3 : icône externe img.icons8.com (dépendance CDN)
- P3 : pas de check `/health` au démarrage de l'UI

## Backend API

- Auth centralisée via `security_v2.require_role()` avec HMAC constant-time
- Fail-closed : 503 sur collision tokens, config manquante, proxy invalide
- SSRF protection complète sur `/ingest/v2/urls`
- SQL paramétré partout (pas d'injection)
- `answer_generation_allowed = false` (retrieval-only)
- P3 : `/admin/health` et `/health` sans auth (healthchecks standards)
- P3 : `/metrics` et `/docs` sans auth (à restreindre en prod publique)
- P3 : `admin_api.py` utilise `!=` au lieu de `hmac.compare_digest()`
- P3 : messages d'erreur incluent parfois `str(exc)` (fuite info interne mineure)
- P3 : connexions DB non poolées (psycopg3 sync, une connexion par requête)

## RAG retrieval

- Pipeline : dense embedding (e5-large 1024D) → pgvector cosine → rerank (MiniLM-L-6-v2)
- Filtre SQL strict : `WHERE review_status = 'reviewed'`
- Gate retrievable : `domain.retrievable is True` (fail-closed GG-01)
- Seuil rerank : 1.90 (LAT-05 certifié LOT 24)
- Cache per-worker avec TTL 300s
- P3 : invalidation cache mono-worker (les autres expirent par TTL)
- Invariant vérifié : aucun `needs_review` dans `/search/v2`

## Collections

- 38 collections déclarées, 2 instanciées + quarantine
- Quarantine : `retrievable: false`, double gate (domain + review_status)
- Legacy mapping : `rag_divers → rag_nexus_quarantine` (403 si requêté)
- Aucune collection orpheline critique
- P3 : quarantine visible dans `/collections/v2` (info leak mineure)

## Ingestion

- `/ingest/v2/upload-files` : PDF, DOCX, MD, TXT, TEX, IPYNB
- `/ingest/v2/urls` : avec protection SSRF
- Chunking pédagogique heading-aware (500 tokens max)
- Tous les chunks ingérés avec `review_status = 'needs_review'` (F-01)
- Dedup via `ON CONFLICT (chunk_id)` + `chunk_sha256`
- Provenance : `doc_id`, `source_label`, `source_uri`, `rights`, `type_doc`

## Review workflow

- Queue : `GET /review/v2/queue` (admin, reviewer, teacher)
- Décision : `POST /review/v2/decide` (admin, reviewer uniquement)
- `needs_review → reviewed` ou `needs_review → quarantined`
- Cache invalidé après décision (mono-worker)
- P3 : race condition théorique si deux reviewers approuvent simultanément

## Agents / orchestration

- Worker Celery pour ingestion async (v2)
- n8n : retiré du déploiement actif
- Scripts : `smoke.sh`, `obs_smoke.sh`, `ollama-preload.sh`
- GitHub Actions : 5 jobs CI
- Aucun secret hardcodé dans les scripts

## LLM / embeddings / reranking

- Embedding : `intfloat/multilingual-e5-large` (1024D, L2 normalisé)
- Reranker : `cross-encoder/ms-marco-MiniLM-L-6-v2` (max_length=512)
- Ollama : healthcheck via `ollama list`, preload au provisionnement
- Ressources : 6 CPU, 24G RAM pour Ollama
- Pas d'appel cloud imposé (tout local)

## Routing API / Nginx

- Templates Nginx : `rag-ui.conf.template`, `rag-api.conf.template`, `rag-v2.conf`
- Headers sécurité : CSP, XFO, X-Content-Type-Options, Referrer-Policy
- Rate limiting : 20 r/s (API), 5 r/s (ingest), 30 r/s (search v2)
- `/metrics` restreint à `127.0.0.1` dans Nginx
- TLS via Certbot avec auto-renewal
- HSTS commenté (à activer après validation TLS)
- P3 : IP hardcodée `88.99.254.59` dans `rag-v2.conf`

## Configuration production

- Provisionnement automatisé : `provision-prod.sh` (single-script)
- Tokens générés via `openssl rand -hex 32` (64 hex)
- `.env` mode 0600, `.gitignore`
- Healthchecks sur tous les services
- Démarrage orchestré : `depends_on: condition: service_healthy`
- Systemd : `rag-local.service` avec `restart: unless-stopped`
- P3 : backup script manque volumes v2 (pgvector, redis, admin)

## Secrets

- Aucun secret réel dans le repo
- `.env.example` avec placeholders uniquement
- `provision-prod.sh` génère tous les tokens
- Umask 177 → fichier 0600
- P3 : placeholder `changez_ceci_par_votre_token` dans `src/ui/.env`

## Observabilité

- Prometheus : scrape ingestor, alertes (disponibilité, erreurs, latence, sécurité)
- Rétention : 15j (v2), configurable
- Métriques : `ingestor_ingests_total`, `ingest_duration_seconds`, `security_violations_total`
- Healthchecks : tous les services avec intervalles 10-30s
- P3 : pas d'Alertmanager configuré (alertes définies mais pas routées)

## Tests

- **1 199 tests** : 378 rag-engine + 821 rag-pedago
- Couverture critique : sécurité (71), retrieval (68), review (25), ingestion (79), preflight (31)
- CI : 7 jobs verts, governance locks (18 clés), taxonomie (19 fichiers)
- Aucun xfail/skip en tests production
- Tests d'intégration isolés (requièrent DB)

## Documentation

- `README-PROD.md` : guide déploiement complet
- `admin_api.md` : documentation API admin
- `docs/adr/` : décisions architecturales
- `docs/reports/` : rapports de lots

## Round 1 — Remédiation dette technique

| # | Sujet | Ancien | Nouveau | Décision | Preuve |
|---|-------|--------|---------|----------|--------|
| P2 | Trusted proxy détecte docker0 | P2 | — | FIXED | `provision-prod.sh` : supprimé `detect_docker_bridge_gateway_cidr()`, default `127.0.0.1/32` uniquement, docs expliquent `docker network inspect` |
| 1 | Cache invalidation mono-worker | P3 | — | RECLASSIFIED_NOT_ISSUE_WITH_EVIDENCE | Le cache est documenté per-worker (L49-51 retrieval_v2_endpoint.py). TTL 300s est le max staleness. Le SQL `WHERE review_status = 'reviewed'` est la gate principale, pas le cache. Un chunk quarantiné ne passe jamais la gate SQL même si le cache est stale car le cache ne stocke que les résultats filtrés. Le TTL est configurable via `RERANK_CACHE_TTL`. |
| 2 | Connexions DB non poolées | P3 | — | RECLASSIFIED_NOT_ISSUE_WITH_EVIDENCE | Go-live cible : déploiement interne contrôlé, <10 utilisateurs concurrents. pgvector supporte 100 connexions par défaut. Chaque requête ouvre et ferme une connexion (pas de leak). Connection pooling est une optimisation future, pas un prérequis go-live. |
| 3 | Messages d'erreur avec `str(exc)` | P3 | — | FIXED | `admin_api.py` : 5 messages sanitisés (detail générique, exception loggée server-side uniquement) |
| 4 | `/docs` et `/redoc` sans auth | P3 | — | FIXED | `api.py` : désactivés quand `RAG_ENV=production`. `/metrics` déjà restreint à `127.0.0.1` dans Nginx (`rag-v2.conf` L67-71, `rag-api.conf.template`). |
| 5 | Admin token `!=` au lieu de HMAC | P3 | — | FIXED | `admin_api.py` : remplacé par `hmac.compare_digest()` |
| 6 | Backup script sans volumes v2 | P3 | — | FIXED | `backup-volumes.sh` : ajouté `rag_pgvector_data`, `rag_redis_data`, `rag_admin_data` |
| 7 | IP hardcodée dans rag-v2.conf | P3 | — | FIXED | `rag-v2.conf` : remplacé `88.99.254.59` par commentaire instructif pour l'opérateur |
| 8 | Placeholder token dans src/ui/.env | P3 | — | FIXED | Renommé en `.env.example` avec valeurs vides et instruction de copie |
| 9 | Icône externe CDN | P3 | — | FIXED | `app_v2.py` : remplacé `img.icons8.com` par emoji local |
| 10 | HSTS non activé | P3 | — | RECLASSIFIED_NOT_ISSUE_WITH_EVIDENCE | HSTS doit être activé APRÈS validation TLS, pas avant déploiement. Le runbook `go_live.md` documente l'étape d'activation explicite. Activer HSTS avant TLS bloquerait l'accès HTTP. Le commentaire dans les templates Nginx est le pattern standard. |
| 11 | Quarantine visible dans /collections/v2 | P3 | — | RECLASSIFIED_NOT_ISSUE_WITH_EVIDENCE | `/collections/v2` filtre déjà `retrievable is True` (L400 retrieval_v2_endpoint.py). La quarantine a `retrievable: false`, donc elle n'apparaît PAS dans la réponse. Vérifié dans le code : seules les collections avec `domain_cfg.get("retrievable") is True` sont retournées. |

## Risques P1/P2/P3 après remédiation

### P1 (bloquant)
Aucun.

### P2 (bloquant)
Aucun.

### P3 (dette ouverte)
Aucun.

## Décision

```
NOT_GO_LIVE_READY
```

Toutes les dettes identifiées sont soit corrigées (FIXED) soit reclassées avec preuve (RECLASSIFIED_NOT_ISSUE_WITH_EVIDENCE). Le verdict reste `NOT_GO_LIVE_READY` en attente de validation lead du round 1 de remédiation.
