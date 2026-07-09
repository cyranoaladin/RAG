docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --remove-orphans
docker compose logs --tail 200   # optionnel, suivi des journaux
bash infra/scripts/smoke.sh  # health + ingestion factice
docker compose -f infra/docker-compose.yml --env-file infra/.env down --remove-orphans
grep -q '^COMPOSE_PROFILES=' infra/.env || cp infra/.env.example infra/.env
make nginx-up
docker compose -f infra/docker-compose.yml --env-file infra/.env ps web || true
make nginx-smoke
make nginx-reload
make nginx-down

# rag-local — Documentation complète

**Auteur : Alaeddine BEN RHOUMA**

---

> Avertissement Lot 19 — document historique/prod actuelle.
> Ce README decrit le moteur `rag-local` encore represente en production par `rag-ui.nexusreussite.academy` : Streamlit, FastAPI ingestor, ChromaDB, Ollama, uploads, Google Drive et catalogue admin. Ce n'est pas la source de verite du chemin Nexus gouverné pgvector/HMAC. Pour la transition, lire aussi `docs/rag_dual_engine_transition.md`, `docs/retrieval_api_convergence.md`, `configs/rag_collections.yml` et `configs/legacy_collection_mapping.yml`.

## Présentation générale

`rag-local` est une solution RAG (Retrieval-Augmented Generation) 100% locale, conçue pour fonctionner sur un VPS sans GPU, avec une architecture modulaire : ingestion de ressources (web, fichiers, GDrive), indexation vectorielle (ChromaDB par défaut, pgvector en cible — voir Lot 1.2), embeddings et LLM locaux (Ollama), UI de recherche (Streamlit), orchestrations (n8n, optionnel), et observabilité Prometheus. Le tout est orchestré par Docker Compose, sécurisé par Nginx, et prêt pour la production.

Depuis le Lot 19, les collections Chroma historiques restent supportees uniquement via mapping :
`rag_education`, `rag_francais_premiere`, `rag_maths_premiere`, `rag_web3`, `rag_divers`
vers `rag_nexus_education`, `rag_nexus_web3` ou `rag_nexus_quarantine`. `rag_divers` est une quarantaine non retrievable.

**Objectifs** :
- Zéro dépendance cloud/LLM externe
- RAM et CPU maîtrisés (VPS-friendly)
- Sécurité (auth, allowlist, reverse proxy)
- Observabilité et CI/CD robustes

---

## Architecture détaillée

```
[n8n/UI] --HTTP--> [Ingestor FastAPI] --RPC--> [Ollama Embeddings]
												  \--REST--> [ChromaDB]  (défaut)
												  \--SQL---> [PostgreSQL/pgvector]  (cible Lot 1.2)
															\--> [Streamlit UI]
```

- **Ingestor** (FastAPI) : endpoint `/ingest` (URL, fichiers, GDrive), `/health`, `/metrics` (Prometheus)
- **ChromaDB** : stockage vectoriel par défaut (`docker-compose.yml`)
- **PostgreSQL + pgvector** : stockage vectoriel cible, indexation HNSW + GIN (voir `infra/postgres/init.sql`, `docker-compose.v2.yml`). Bascule planifiée au Lot 1.2
- **Ollama** : embeddings (`nomic-embed-text`), LLM (`llama3.2`)
- **UI** (Streamlit) : recherche sémantique, top-k borné, métadonnées
- **n8n** (optionnel) : automatisations, webhooks, planifications
- **Nginx** : reverse proxy, TLS, headers sécurité
- **Prometheus** (optionnel) : observabilité, alertes

Voir `docs/dossier-technique-exhaustif.md` et `SPEC.md` pour tous les détails (API, variables, sécurité, flux, profils Compose).

---

## Installation et usage local (développement)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp infra/.env.example infra/.env
# Adapter les variables (tokens, ports, modèles Ollama…)
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d --remove-orphans
bash infra/scripts/smoke.sh  # health + ingestion factice
```

Qualité :
- `make lint` (ruff)
- `make typecheck` (mypy)
- `make test` (pytest)
- `make smoke` (stack + health)

Arrêt :
```bash
docker compose -f infra/docker-compose.yml --env-file infra/.env down --remove-orphans
```

---

## Déploiement production (VPS)

1. Cloner le repo sur le VPS (`/srv/rag-local` recommandé)
2. Copier `infra/.env.example` → `infra/.env` et renseigner toutes les variables (voir section Sécurité)
3. Générer les secrets (voir tableau ci-dessous)
4. Préparer les credentials GDrive si besoin (`/srv/rag/creds/gdrive-service-account.json`)
5. Rendre les vhosts Nginx via `envsubst` et activer TLS avec certbot
6. Lancer le déploiement :
	```bash
	cd /srv/rag-local
	sudo scripts/deploy-prod.sh
	```

**Secrets à générer** :
| Nom | Longueur | Usage |
|-----|----------|-------|
| `LEGACY_ADMIN_API_TOKEN` | 64 hex | Auth dédiée des routes legacy `/admin/*` |
| `RAG_ADMIN_TOKEN` | 64 hex | Auth v2 admin |
| `RAG_REVIEWER_TOKEN` | 64 hex | Auth v2 reviewer |
| `REVIEWER_API_TOKEN` | 64 hex | Alias legacy reviewer |
| `RAG_TEACHER_TOKEN` | 64 hex | Auth v2 teacher |
| `RAG_INGEST_AGENT_TOKEN` | 64 hex | Auth v2 ingest_agent |
| `INGESTOR_API_TOKEN` | 64 hex | Alias legacy ingest_agent / UI ↔ API |
| `INGEST_AUTH_TOKEN` | 64 hex | Alias legacy ingest_agent |
| `RAG_STUDENT_TOKEN` | 64 hex | Auth v2 student |
| `N8N_ENCRYPTION_KEY` | 64 hex | n8n credentials |
| `N8N_BASIC_AUTH_PASSWORD` | 32 | n8n UI |
| `PROMETHEUS_SCRAPE_PASSWORD` | 32 | /metrics |

Unicite des tokens v2 : chaque role doit utiliser une valeur de token distincte. `RAG_REVIEWER_TOKEN` et `REVIEWER_API_TOKEN` peuvent etre identiques pour le role reviewer. `INGESTOR_API_TOKEN` et `INGEST_AUTH_TOKEN` restent des alias de compatibilite ingest_agent v2, mais `RAG_INGEST_AGENT_TOKEN` devrait rester distinct des tokens d'ingestion legacy. Exemple interdit : `RAG_ADMIN_TOKEN` et `RAG_STUDENT_TOKEN` identiques. En cas de collision entre roles v2 distincts, `security_v2` bloque en fail-closed `503`.

Attention legacy : les routes `/admin/*` utilisent exclusivement `LEGACY_ADMIN_API_TOKEN`. Ce token doit rester distinct de `RAG_ADMIN_TOKEN`, `INGESTOR_API_TOKEN` et `INGEST_AUTH_TOKEN`. Les tokens d'ingestion legacy ne donnent aucun acces admin.

Si `INGESTOR_IP_ALLOWLIST` est utilisee derriere un proxy, definir `INGESTOR_TRUSTED_PROXY_CIDRS` avec les CIDR des proxies de confiance. Les variables v2 sont transmises au conteneur `ingestor` par les compose prod, par defaut et v2 (`make v2-up`). Sans cette variable, `X-Forwarded-For` et `X-Real-IP` sont ignores. Si elle est explicitement non vide mais ne contient aucun CIDR valide, l'allowlist echoue en fail-closed `503`. Depuis un peer trusted, `X-Real-IP` reste ignore cote application tant qu'un template proxy versionne ne prouve pas sa reecriture stricte ; `X-Forwarded-For` est analyse de droite a gauche en retirant les proxies de confiance, jamais en premiere position naive.

Ne pas utiliser `proxy_add_x_forwarded_for` sans strategie anti-spoof cote application ou sans reecriture stricte du header par le proxy.

**Modèles Ollama** : `nomic-embed-text`, `llama3.2:3b` (précharger via `infra/scripts/ollama-preload.sh`)

---

## Sécurité et bonnes pratiques

- Authentification token sur `/ingest` (header configurable)
- Allowlist CIDR IP (prod)
- Fichiers uploadés : whitelist MIME, racine restreinte
- Nginx : BasicAuth, TLS, headers CSP/HSTS
- Secrets hors VCS, droits 600 sur les credentials
- Jamais d’exposition directe des ports Compose en production

---

## Observabilité et métriques

- Endpoint Prometheus `/metrics` (ingestor) activable via `METRICS_ENABLED=true`
- Métriques : `ingestor_ingests_total{source,modality,status}`, `ingestor_ingest_duration_seconds`
- Profil Compose `obs` pour Prometheus local
- Alertes PromQL recommandées (cf. `docs/observability.md`)

---

## CI/CD et qualité logicielle

- Pipeline GitHub Actions : lint, typecheck, tests, smoke
- Script `infra/scripts/smoke.sh` : health check, logs, auto-diagnostic en cas d’échec
- Robustesse : tous les logs, états réseau, inspect sont dumpés en cas de fail CI
- Tests unitaires et d’intégration couvrant sécurité, chunking, métriques, multimodal

---


## FAQ et ressources complémentaires

- [English README](README-EN.md)
- [Guide de troubleshooting](TROUBLESHOOTING.md)
- Architecture détaillée : `docs/architecture.md`, `docs/dossier-technique-exhaustif.md`
- Spécifications API et variables : `SPEC.md`
- Observabilité : `docs/observability.md`
- CI/CD et robustesse : `CI_ROBUSTESSE.md`
- Instructions Copilot : `.github/copilot-instructions.md`

---

## Auteur

Ce guide a été rédigé et maintenu par **Alaeddine BEN RHOUMA** pour garantir la compréhension, la robustesse et la maintenabilité du projet rag-local en production.
