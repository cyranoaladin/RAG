Ces fichiers sont des **templates** de vhosts Nginx (hôte) :
- `rag-ui.conf.template` pour l’UI Streamlit (reverse proxy vers 127.0.0.1:8501, Basic Auth requise)
- `rag-api.conf.template` pour l’API Ingestor (reverse proxy vers 127.0.0.1:${NGINX_API_PORT}, `/metrics` restreint à 127.0.0.1)
- `rag-api.public-search.conf.template` pour le **candidat public V1** : seul
  `POST /search/v2` est transmis au port loopback du candidat blue-green.
  Les routes de writer, revue, ingestion, métriques, catalogue et readiness
  reçoivent 404 sur HTTP et HTTPS ; seule `/search/v2` est redirigée de HTTP
  vers HTTPS. Les en-têtes `Forwarded`, `X-Forwarded-*` usuels et `X-Real-IP`
  fournis par le client ne sont pas transmis à l'API. Le scrape et les sondes
  utilisent le port loopback directement.
- `rag-v2.conf` est l'alternative TLS déjà matérialisée ; elle doit être rendue
  avec `RAG_API_EXTERNAL_DOMAIN` et `NGINX_API_PORT` et cible le même port
  loopback.

Le template public V1 est distinct des vhosts historiques. Le rendre avec
`envsubst '${RAG_API_EXTERNAL_DOMAIN} ${NGINX_API_PORT}'`, en fixant
`NGINX_API_PORT` au `NEXUS_SEARCH_PORT` du candidat scellé. Sa pose/remplacement
atomique dans Nginx appartient au cutover signé : ce dépôt ne prouve ni la
connexion interne Cockpit BFF → API du réseau blue-green, ni l'activation du
vhost en production. Ne jamais activer deux vhosts pour le même domaine API.

## Rendu des vhosts via `envsubst`

```bash
# Variables explicitement définies (pas de ${VAR:-def})
export RAG_UI_EXTERNAL_DOMAIN="rag-ui.example.com"
export RAG_API_EXTERNAL_DOMAIN="rag-api.example.com"
export NGINX_API_PORT="8001"
export NGINX_UI_UPSTREAM="127.0.0.1:8501"
export NGINX_CLIENT_MAX_BODY_SIZE="16m"

# Rendu + activation
envsubst '${RAG_UI_EXTERNAL_DOMAIN} ${NGINX_UI_UPSTREAM} ${NGINX_CLIENT_MAX_BODY_SIZE}' \
  < infra/nginx/rag-ui.conf.template \
  | sudo tee /etc/nginx/sites-available/rag-ui.conf >/dev/null
envsubst '${RAG_API_EXTERNAL_DOMAIN} ${NGINX_API_PORT}' \
  < infra/nginx/rag-api.conf.template \
  | sudo tee /etc/nginx/sites-available/rag-api.conf >/dev/null
sudo ln -sf /etc/nginx/sites-available/rag-ui.conf  /etc/nginx/sites-enabled/rag-ui.conf
sudo ln -sf /etc/nginx/sites-available/rag-api.conf /etc/nginx/sites-enabled/rag-api.conf
sudo nginx -t && sudo systemctl reload nginx
```

Pour utiliser à la place le vhost TLS matérialisé `rag-v2.conf`, ne rendez pas
`rag-api.conf.template` et exécutez explicitement :

```bash
envsubst '${RAG_API_EXTERNAL_DOMAIN} ${NGINX_API_PORT}' \
  < infra/nginx/rag-v2.conf \
  | sudo tee /etc/nginx/sites-available/rag-api.conf >/dev/null
sudo ln -sf /etc/nginx/sites-available/rag-api.conf /etc/nginx/sites-enabled/rag-api.conf
sudo nginx -t && sudo systemctl reload nginx
```

Ensuite, **Certbot** peut gérer la terminaison TLS :

```bash
sudo certbot --nginx -d "$RAG_UI_EXTERNAL_DOMAIN" --redirect
sudo certbot --nginx -d "$RAG_API_EXTERNAL_DOMAIN" --redirect
```

Certbot ajoutera automatiquement les blocs HTTPS.
Ajoutez `add_header Strict-Transport-Security "max-age=63072000" always;` dans les blocs HTTPS de production.

## Rate limiting
- Le vhost API inclut une zone `limit_req_zone` appliquée uniquement aux routes
  exactes retrieval, catalogue, readiness et revue. Les chemins `/ingest*` ne
  sont jamais transmis.
- Ajustez ces valeurs si nécessaire en éditant `infra/nginx/rag-api.conf.template` avant rendu.
- Le candidat public V1 fixe `public_search_v1` à **20 requêtes POST/s par IP**, avec
  `burst=40`. Une clé vide pour les autres méthodes empêche les GET refusés de
  consommer ce quota. Toute modification éventuelle doit être évaluée contre
  les budgets C0 figés avant de rendre le template public ; elle ne constitue
  pas une méthode pour faire passer un test de charge rouge.
