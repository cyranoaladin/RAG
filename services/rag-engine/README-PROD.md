# rag-local — Déploiement Production (VPS)

> Avertissement Lot 19 — prod historique, pas deploiement Nexus final.
> Ce document reste utile pour comprendre et operer l'UI historique `rag-ui.nexusreussite.academy` (Streamlit + FastAPI ingestor + ChromaDB + Ollama). Il ne doit pas etre lu comme un plan de deploiement du futur RAG Nexus pgvector. Avant toute mise a jour de prod, utiliser `docs/reports/lot_19_prod_deployment_plan.md` : backup, diff prod/repo, rsync cible, post-check et rollback.

Ce projet fournit un **RAG 100% local** (LLM & embeddings via **Ollama**) avec **ingestion multi-sources** et **UI de recherche**. L’architecture est prête à être exposée en **HTTPS** via **Nginx + Let's Encrypt**, sans dépendance à des API externes.

> ℹ️ n8n a été retiré du déploiement. L’ingestion se fait directement via l’API (Authorization: Bearer) et un petit utilitaire CLI (`scripts/ingest-cli.py`).

Collections Lot 19 : les noms Chroma historiques ne sont pas renommes physiquement en prod. La couche applicative mappe `rag_education`, `rag_francais_premiere`, `rag_maths_premiere`, `rag_web3`, `rag_divers` vers les collections Nexus versionnees dans `configs/rag_collections.yml`. `rag_divers` correspond a `rag_nexus_quarantine` et ne doit pas etre expose a la recherche.

Securite admin Lot 19 follow-up : `RAG_ENV=production` doit etre explicite dans l'environnement prod. En l'absence de `LEGACY_ADMIN_API_TOKEN`, `/admin/*` retourne 503 ; aucun fallback vers `INGESTOR_API_TOKEN` ou `INGEST_AUTH_TOKEN` n'est applique. Le mode admin sans token est reserve au developpement local et exige `RAG_ENV=development` plus `ALLOW_UNAUTHENTICATED_ADMIN_DEV=true`. En prod Docker, le compose versionne monte `${RAG_CONFIGS_HOST_DIR:-../configs}:/app/configs:ro` : le defaut `../configs` convient depuis `services/rag-engine/infra`, tandis que le layout historique plat `/srv/nexusreussite/rag-ui/compose` doit definir `RAG_CONFIGS_HOST_DIR=./configs`. Definir aussi `RAG_ENGINE_CONFIG_DIR=/app/configs` pour charger `rag_collections.yml` et `legacy_collection_mapping.yml`. Si les fichiers sont separes, utiliser les overrides explicites `RAG_COLLECTIONS_CONFIG` et `RAG_LEGACY_COLLECTION_MAPPING`; ces overrides echouent fermes si le chemin configure est absent.

## Prérequis VPS
- Ubuntu 22.04/24.04, accès sudo, ports 80/443 ouverts, DNS des domaines pointés sur le VPS.
- Docker Engine ≥ 24.0 + plugin Compose ≥ 2.24 (`docker compose version`).
- Cloner le repo et copier `infra/.env.example` vers `infra/.env`, puis éditer `RAG_UI_EXTERNAL_DOMAIN`, `RAG_API_EXTERNAL_DOMAIN`, `NGINX_API_PORT`, `RAG_ENV=production`, `RAG_ENGINE_CONFIG_DIR=/app/configs`, `RAG_CONFIGS_HOST_DIR` si le compose n'est pas execute depuis `services/rag-engine/infra`, `LEGACY_ADMIN_API_TOKEN`, les tokens v2 par role (`RAG_ADMIN_TOKEN`, `RAG_REVIEWER_TOKEN`, `REVIEWER_API_TOKEN`, `RAG_TEACHER_TOKEN`, `RAG_INGEST_AGENT_TOKEN`, `INGESTOR_API_TOKEN`, `INGEST_AUTH_TOKEN`, `RAG_STUDENT_TOKEN`), et `INGESTOR_TRUSTED_PROXY_CIDRS` si `INGESTOR_IP_ALLOWLIST` doit lire `X-Forwarded-For` derriere un reverse proxy de confiance. Les compose prod, par defaut et v2 (`make v2-up`) transmettent ces variables au conteneur `ingestor`.

## Secrets à générer
| Nom | Longueur conseillée | Usage | Où le renseigner |
|-----|---------------------|-------|------------------|
| `LEGACY_ADMIN_API_TOKEN` | 64 hex (`openssl rand -hex 32`) | Auth dédiée des routes legacy `/admin/*` | `infra/.env` (`LEGACY_ADMIN_API_TOKEN`) |
| `RAG_ADMIN_TOKEN` | 64 hex (`openssl rand -hex 32`) | Auth v2 admin | `infra/.env` (`RAG_ADMIN_TOKEN`) |
| `RAG_REVIEWER_TOKEN` | 64 hex (`openssl rand -hex 32`) | Auth v2 reviewer | `infra/.env` (`RAG_REVIEWER_TOKEN`) |
| `REVIEWER_API_TOKEN` | 64 hex (`openssl rand -hex 32`) | Alias legacy reviewer | `infra/.env` (`REVIEWER_API_TOKEN`) |
| `RAG_TEACHER_TOKEN` | 64 hex (`openssl rand -hex 32`) | Auth v2 teacher | `infra/.env` (`RAG_TEACHER_TOKEN`) |
| `RAG_INGEST_AGENT_TOKEN` | 64 hex (`openssl rand -hex 32`) | Auth v2 ingest_agent | `infra/.env` (`RAG_INGEST_AGENT_TOKEN`) |
| `INGESTOR_API_TOKEN` | 64 hex (`openssl rand -hex 32`) | Alias legacy ingest_agent / UI vers API | `infra/.env` (`INGESTOR_API_TOKEN`) |
| `INGEST_AUTH_TOKEN` | 64 hex (`openssl rand -hex 32`) | Alias legacy ingest_agent | `infra/.env` (`INGEST_AUTH_TOKEN`) |
| `RAG_STUDENT_TOKEN` | 64 hex (`openssl rand -hex 32`) | Auth v2 student | `infra/.env` (`RAG_STUDENT_TOKEN`) |
| `UI_BASIC_AUTH_USER_FILE_DIRECTIVE` | fichier htpasswd | Optionnel : restreindre l’UI Streamlit | `infra/.env` (`UI_BASIC_AUTH_*`) + templates Nginx |

> Astuce : conserver les secrets hors dépôt (ex: `pass`, `1Password`) et régénérer à chaque rotation.

Unicite des tokens v2 : chaque role v2 doit utiliser une valeur distincte. `RAG_REVIEWER_TOKEN` et `REVIEWER_API_TOKEN` peuvent partager une valeur pour le role reviewer. `INGESTOR_API_TOKEN` et `INGEST_AUTH_TOKEN` restent des alias de compatibilite ingest_agent v2, mais `RAG_INGEST_AGENT_TOKEN` devrait rester distinct des tokens d'ingestion legacy. Une collision entre roles v2 distincts, par exemple `RAG_ADMIN_TOKEN` identique a `RAG_STUDENT_TOKEN`, bloque `security_v2` en fail-closed `503`.

Attention legacy : `INGESTOR_API_TOKEN` et `INGEST_AUTH_TOKEN` sont des tokens historiques d'ingestion. Ils ne doivent jamais etre reutilises pour les routes admin legacy `/admin/*`. Ces routes utilisent exclusivement `LEGACY_ADMIN_API_TOKEN`, qui doit aussi rester distinct de `RAG_ADMIN_TOKEN`. `RAG_ADMIN_TOKEN` protege les routes v2 admin et n'ouvre pas automatiquement `/admin/*`.

Allowlist ingestion : les chemins `/ingest` legacy et `/ingest/v2` utilisent la resolution IP durcie partagee. Sans `INGESTOR_TRUSTED_PROXY_CIDRS`, l'allowlist n'utilise que le peer direct `request.client.host` et ignore `X-Forwarded-For` / `X-Real-IP`. Avec `INGESTOR_TRUSTED_PROXY_CIDRS`, `X-Forwarded-For` est accepte uniquement depuis un proxy de confiance, analyse de droite a gauche, et toute entree vide ou malformee rend la chaine non fiable. Une valeur explicitement non vide sans aucun CIDR valide bloque l'allowlist en fail-closed `503`, sans exposer la valeur invalide. `X-Real-IP` est ignore cote application. Le provisioning interactif propose par defaut `127.0.0.1/32,172.16.0.0/12` pour couvrir loopback et les bridges Docker, sans faire confiance aux LAN prives `10/8` ou `192.168/16` ; resserrer cette valeur si le CIDR exact du bridge est connu.

Ne pas utiliser `proxy_add_x_forwarded_for` sans strategie anti-spoof cote application ou sans reecriture stricte du header par le proxy. Le durcissement applicatif LOT 26.3 ignore XFF depuis un peer non trusted et parcourt XFF de droite a gauche depuis un proxy trusted.

## Modèles Ollama conseillés
- `EMBED_MODEL=nomic-embed-text` (cohérent avec la collection Chroma)
- `SMALL_LLM=llama3.2:3b` (modèle instruct compact, compatible Ollama 0.3.13)

> Vérifiez les modèles disponibles sur le VPS avec `docker exec "$(docker compose -f /srv/rag/docker-compose.yml ps -q ollama)" ollama list` avant de les déclarer dans `.env`, afin d’éviter un préchargement en échec.

## Démarrage (services internes, non exposés)
```bash
# Développement local (ports de loopback, sans Nginx)
docker compose -f infra/docker-compose.yml --env-file infra/.env up -d

# Production (ports loopback, Nginx hôte devant, Prometheus en option)
docker compose -f infra/docker-compose.prod.yml --env-file infra/.env --profile db --profile llm --profile api --profile ui --profile obs up -d
```

## Service systemd (recommandé en prod)
```bash
# depuis la racine du dépôt déjà synchronisé sur le VPS
export RAG_DIR=/srv/rag-local
sudo mkdir -p "$RAG_DIR"

# ⚠️ ATTENTION : la commande suivante SUPPRIMERA tout fichier dans "$RAG_DIR" qui n'existe pas dans le dossier courant.
# Assurez-vous d'être dans la racine du dépôt (là où se trouve ce README) avant d'exécuter cette commande !
# Optionnel : vérification automatique (décommentez pour activer)
# [ -f "infra/docker-compose.prod.yml" ] || { echo "Erreur : exécutez cette commande depuis la racine du dépôt (infra/docker-compose.prod.yml introuvable)"; exit 1; }

sudo rsync -a --delete ./ "$RAG_DIR"/
cd "$RAG_DIR"
# rendre le service et l'installer
./infra/scripts/install-systemd.sh
# vérifier
systemctl status rag-local.service --no-pager
```

## Exposition HTTPS (Nginx + Certbot)

- Utiliser `infra/nginx/rag-ui.conf.template` et `infra/nginx/rag-api.conf.template` avec `envsubst` pour générer les vhosts (les templates n’emploient pas `${VAR:-def}`).
- Activer ensuite TLS via `certbot --nginx -d <domaines> --agree-tos -m <email> --redirect -n`.
- Les templates intègrent CSP stricte, `Permissions-Policy`, `X-Frame-Options`, et `Referrer-Policy`.
- Ajouter `add_header Strict-Transport-Security "max-age=63072000" always;` après issuance TLS (HSTS production).

Exemple :
```bash
export RAG_UI_EXTERNAL_DOMAIN="rag-ui.example.com"
export RAG_API_EXTERNAL_DOMAIN="rag-api.example.com"
export NGINX_API_PORT="8001"
export NGINX_CLIENT_MAX_BODY_SIZE="16m"

sudo -E bash -c 'envsubst < infra/nginx/rag-ui.conf.template  > /etc/nginx/sites-available/rag-ui.conf'
sudo -E bash -c 'envsubst < infra/nginx/rag-api.conf.template > /etc/nginx/sites-available/rag-api.conf'
sudo ln -sf /etc/nginx/sites-available/rag-ui.conf  /etc/nginx/sites-enabled/rag-ui.conf
sudo ln -sf /etc/nginx/sites-available/rag-api.conf /etc/nginx/sites-enabled/rag-api.conf
sudo nginx -t && sudo systemctl reload nginx

# Certbot TLS
echo $RAG_UI_EXTERNAL_DOMAIN  | xargs -I {} sudo certbot --nginx -d {} --redirect
echo $RAG_API_EXTERNAL_DOMAIN | xargs -I {} sudo certbot --nginx -d {} --redirect
```

## Ingestion

- Endpoint `POST /ingest` (service ingestor) pour URL/fichiers/Google Drive.
- Authentification: `Authorization: Bearer $INGESTOR_API_TOKEN` (ou `X-API-Token: $INGESTOR_API_TOKEN`).
- Chunking par défaut 800/120 (ajustable via `INGEST_CHUNK_SIZE`, `INGEST_CHUNK_OVERLAP`).
- Les chunks et métadonnées sont stockés dans Chroma (v2).
- Utilitaire CLI pour cron: `scripts/ingest-cli.py` (voir `scripts/requirements-cli.txt`).
- API externe de consultation (agents): voir `docs/kb-api.md` (`POST /search`).

## UI

- Streamlit: recherche, top-k, sources, métadonnées.
- Top-k borné à 8 par défaut (`UI_MAX_K`).
- Ingestion depuis l’UI: envoi direct à l’API via `Authorization: Bearer` (variables `UI_INGEST_AUTH_HEADER=Authorization`, `UI_INGEST_AUTH_BEARER_PREFIX=true`).

## Observabilité

### Ops checks Nginx/API/UI (safe paste)

Exécutez ces contrôles sur le VPS pour valider rapidement Nginx côté API/UI sans révéler de secrets.

```bash path=null start=null
set -euo pipefail

# API et UI (déduits des vhosts)
API_DOMAIN=$(sed -n 's/^[[:space:]]*server_name[[:space:]]\+\([^;]*\).*/\1/p' /etc/nginx/conf.d/rag-api.conf | head -n1)
UI_DOMAIN=$(sed -n 's/^[[:space:]]*server_name[[:space:]]\+\([^;]*\).*/\1/p'  /etc/nginx/conf.d/rag-ui.conf  | head -n1)

# API via SNI (boucle locale, validation TLS conservee)
HC=$(curl -sS -o /dev/null -w '%{http_code}' --resolve "${API_DOMAIN}:443:127.0.0.1" "https://${API_DOMAIN}/health")
MC=$(curl -sS -I --resolve "${API_DOMAIN}:443:127.0.0.1" "https://${API_DOMAIN}/metrics" | awk '/^HTTP/{print $2}' | head -n1)
echo "API: /health=$HC (200 attendu), /metrics HEAD=$MC (200 attendu côté localhost; FastAPI peut renvoyer 405 sur HEAD — utilisez GET si besoin)"

# UI BasicAuth — renseignez un compte valide côté Nginx
UI_USER={{UI_USER}}
UI_PASS={{UI_PASS}}
UC1=$(curl -sS -o /dev/null -w '%{http_code}' --resolve "${UI_DOMAIN}:443:127.0.0.1" "https://${UI_DOMAIN}/")
UC2=$(curl -sS -o /dev/null -w '%{http_code}' --user "$UI_USER:$UI_PASS" --resolve "${UI_DOMAIN}:443:127.0.0.1" "https://${UI_DOMAIN}/")
echo "UI: sans creds=$UC1 (401 attendu), avec creds=$UC2 (200 attendu)"
```

- Ingestor expose `GET /metrics` (Prometheus) lorsque `METRICS_ENABLED=true` dans `infra/.env`.
- Restreindre `/metrics` côté Nginx API à `127.0.0.1` (voir `infra/nginx/rag-api.conf.template`).
- Métriques clés:
  - `ingestor_ingests_total{status}` pour identifier les échecs (`status=http_4xx/http_5xx`).
  - `histogram_quantile` sur `ingestor_ingest_duration_seconds` (p99 > 4s ⇒ alerte latence ingestion).
- Exemple d'alerte PromQL:
  - `sum(increase(ingestor_ingests_total{status!="success"}[5m])) > 0`
  - `histogram_quantile(0.99, sum(rate(ingestor_ingest_duration_seconds_bucket[5m])) by (le)) > 4`

## Sauvegardes (idée)

* Volume Chroma en snapshot (rsync / restic / rclone) + rotation (daily/weekly).

Voir `SPEC.md` pour l’architecture et le contrat d’API.

---

## Notes
- Les profils Compose `automations` et les fichiers Nginx `rag-n8n.*` ne sont plus utilisés.
- L’API utilise par défaut `Authorization: Bearer` mais accepte `X-API-Token` pour compatibilité.

## Observability profile (internal-only)
- Set \`METRICS_ENABLED=true\`, bring up Prometheus with \`--profile obs\`
- /metrics is **not** exposed publicly; Prometheus scrapes the ingestor over the bridge network.

---

## Uploads de fichiers (Admin UI / API)

- Assurez-vous que le répertoire des uploads est monté en écriture:
  - Volume: /srv/rag-data sur l’hôte mappé vers /data/uploads dans le conteneur ingestor (rw)
  - NGINX_CLIENT_MAX_BODY_SIZE (ex: 64m) si vous uploadez de gros PDF
- Authentification: `Authorization: Bearer $LEGACY_ADMIN_API_TOKEN` (ou `X-API-Token: $LEGACY_ADMIN_API_TOKEN`)
- Endpoint: POST /admin/upload (multipart/form-data)
  - Params: ingest=true|false, domain, title?, tags(JSON), metadata(JSON)
  - Réponse: chemin, type MIME, taille, guess du source_type

## Persistance du catalog Admin (SQLite)

- Variable: ADMIN_DB_PATH=/data/catalog.sqlite (persisté via volume rag_admin_data)
- Montez le volume rag_admin_data:/data pour conserver la base entre redémarrages
- Sauvegarde: copiez /data/catalog.sqlite régulièrement (rsync/restic)

## Activer Google Drive en prod

1) Préparer la clé de Service Account Google Drive (JSON) et partager le dossier/Drive cible avec l’email du service account (lecteur).

2) Déposer la clé sur le VPS et activer GDrive via le script

```bash path=null start=null
# Sur votre machine
scp ./gdrive-sa.json root@<VPS>:/opt/rag-local/gdrive-sa.json

# Sur le VPS
sudo -i
cd /opt/rag-local
chmod 600 /opt/rag-local/gdrive-sa.json
./infra/scripts/enable-gdrive-prod.sh /opt/rag-local/gdrive-sa.json
```

Ce script:
- Installe la clé en `infra/creds/gdrive-sa.json` (chmod 600)
- Ajoute/actualise dans `infra/.env`:
  - `GOOGLE_APPLICATION_CREDENTIALS=/creds/gdrive-sa.json`
  - `GOOGLE_DRIVE_TOKEN_PATH=/tmp/google-drive-token.json`
- Redémarre la stack (systemd si présent, sinon `docker compose` pour `ingestor`).

3) Tester l’ingestion GDrive

```bash path=null start=null
API="https://<RAG_API_DOMAIN>"     # ex. https://rag-api.example.com
TOKEN="<INGESTOR_API_TOKEN>"       # valeur dans /opt/rag-local/infra/.env
FOLDER_ID="<GOOGLE_FOLDER_ID>"     # ID du dossier Google Drive

curl -sS -X POST "$API/ingest" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d "{\"source_type\":\"gdrive_folder\",\"source\":\"$FOLDER_ID\",\"hints\":{\"tag\":\"drive\"}}"
```
