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

## 10. Revue initiale via le Cockpit BFF

Les opérations humaines de review passent exclusivement par le Cockpit. Le
reviewer doit avoir une session Auth.js active, non révoquée, avec le rôle
`reviewer` ou `admin`.

Ce runbook historique **ne provisionne pas le Cockpit**. La configuration
canonique est décrite dans le
[README Cockpit](../../services/cockpit/README.md).
Arrêter la procédure si le Cockpit HTTPS et son BFF ne sont pas déjà déployés.
Charger les variables depuis le gestionnaire de secrets dans un shell opérateur
sécurisé, sans activer `xtrace`, puis exécuter le préflight ci-dessous. Il ne
doit afficher aucune valeur. Tous les blocs de cette section s'exécutent dans
ce même shell.

```bash
set +x
set -euo pipefail

COCKPIT="https://cockpit.example.com"
case "$COCKPIT" in
  https://*) ;;
  *) printf '%s\n' "ERREUR: URL Cockpit HTTPS requise" >&2; exit 1 ;;
esac

required_secret_names=(
  NEXTAUTH_SECRET
  NEXUS_SSO_ISSUER
  NEXUS_SSO_AUDIENCE
  NEXUS_RELEASE_SCHOOL_YEAR
  NEXUS_INTERNAL_TOKEN_SECRET
  NEXUS_INTERNAL_TOKEN_ISSUER
  NEXUS_INTERNAL_TOKEN_AUDIENCE
  NEXUS_SESSION_REDIS_URL
  RAG_ENGINE_INTERNAL_TOKEN
  RAG_BFF_SERVICE_TOKEN
  RAG_ADMIN_TOKEN
  RAG_REVIEWER_TOKEN
  RAG_TEACHER_TOKEN
  RAG_INGEST_AGENT_TOKEN
  RAG_STUDENT_TOKEN
)
missing_secret=0
for secret_name in "${required_secret_names[@]}"; do
  if [ -z "${!secret_name:-}" ]; then
    printf 'ERREUR: variable requise absente: %s\n' "$secret_name" >&2
    missing_secret=1
  fi
done
test "$missing_secret" -eq 0

if [ -z "${NEXUS_SSO_JWKS_URL:-}" ] && [ -z "${NEXUS_SSO_SHARED_SECRET:-}" ]; then
  printf '%s\n' \
    "ERREUR: NEXUS_SSO_JWKS_URL ou NEXUS_SSO_SHARED_SECRET requis" >&2
  exit 1
fi
case "$NEXUS_SSO_AUDIENCE" in
  *,*) printf '%s\n' "ERREUR: audience SSO unique requise" >&2; exit 1 ;;
esac
printf '%s' "$NEXUS_RELEASE_SCHOOL_YEAR" \
  | grep -Eq '^[0-9]{4}-[0-9]{4}$'

if [ "$RAG_ENGINE_INTERNAL_TOKEN" != "$RAG_BFF_SERVICE_TOKEN" ]; then
  printf '%s\n' "ERREUR: credentials BFF Cockpit/moteur différents" >&2
  exit 1
fi

human_token_names=(
  RAG_ADMIN_TOKEN
  RAG_REVIEWER_TOKEN
  RAG_TEACHER_TOKEN
  RAG_INGEST_AGENT_TOKEN
  RAG_STUDENT_TOKEN
)
for human_name in "${human_token_names[@]}"; do
  if [ "${!human_name}" = "$RAG_ENGINE_INTERNAL_TOKEN" ]; then
    printf 'ERREUR: credential BFF confondu avec le rôle %s\n' "$human_name" >&2
    exit 1
  fi
done
for ((left = 0; left < ${#human_token_names[@]}; left++)); do
  for ((right = left + 1; right < ${#human_token_names[@]}; right++)); do
    left_name="${human_token_names[$left]}"
    right_name="${human_token_names[$right]}"
    if [ "${!left_name}" = "${!right_name}" ]; then
      printf 'ERREUR: tokens de rôles non distincts: %s/%s\n' \
        "$left_name" "$right_name" >&2
      exit 1
    fi
  done
done
```

Obtenir ensuite trois jetons SSO éphémères de comptes de test
`reviewer`, `student` et `teacher` par le parcours Nexus officiel. Les charger
respectivement dans `NEXUS_REVIEWER_SSO_TOKEN`, `NEXUS_STUDENT_SSO_TOKEN` et
`NEXUS_TEACHER_SSO_TOKEN` sans les afficher. Le bloc suivant utilise le provider
Credentials Auth.js supporté, crée des cookie jars Netscape en mode privé et
valide chaque session. Il ne fabrique ni JWT ni cookie.

```bash
umask 077
for sso_name in \
  NEXUS_REVIEWER_SSO_TOKEN NEXUS_STUDENT_SSO_TOKEN NEXUS_TEACHER_SSO_TOKEN; do
  if [ -z "${!sso_name:-}" ]; then
    printf 'ERREUR: jeton SSO éphémère absent: %s\n' "$sso_name" >&2
    exit 1
  fi
done

REVIEW_SMOKE_TMP="$(mktemp -d)"
REVIEWER_COOKIE_JAR="$REVIEW_SMOKE_TMP/reviewer.cookies"
STUDENT_COOKIE_JAR="$REVIEW_SMOKE_TMP/student.cookies"
TEACHER_COOKIE_JAR="$REVIEW_SMOKE_TMP/teacher.cookies"

cleanup_review_smoke() {
  if [ -n "${REVIEW_SMOKE_TMP:-}" ] && [ -d "$REVIEW_SMOKE_TMP" ]; then
    find "$REVIEW_SMOKE_TMP" -type f -delete
    rmdir "$REVIEW_SMOKE_TMP"
  fi
}
trap cleanup_review_smoke EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

assert_review_json_response() {
  local expected_status="$1"
  local actual_status="$2"
  local headers_file="$3"
  local body_file="$4"
  local normalized_headers="$headers_file.normalized"
  test "$actual_status" = "$expected_status"
  tr -d '\r' < "$headers_file" > "$normalized_headers"
  grep -Fxiq 'Cache-Control: private, no-store, max-age=0' \
    "$normalized_headers"
  jq -e . "$body_file" >/dev/null
}

# Prouve que le BFF review est déployé et fermé sans session.
bff_preflight_status="$(curl -sS \
  -D "$REVIEW_SMOKE_TMP/bff-preflight.headers" \
  -o "$REVIEW_SMOKE_TMP/bff-preflight.json" \
  -w '%{http_code}' \
  "$COCKPIT/api/review/queue")"
assert_review_json_response 401 "$bff_preflight_status" \
  "$REVIEW_SMOKE_TMP/bff-preflight.headers" \
  "$REVIEW_SMOKE_TMP/bff-preflight.json"

create_authjs_cookie_jar() {
  local label="$1"
  local sso_token="$2"
  local cookie_jar="$3"
  local token_file="$REVIEW_SMOKE_TMP/$label.sso"
  local csrf_status csrf_token callback_status session_status
  printf '%s' "$sso_token" > "$token_file"

  csrf_status="$(curl -sS \
    -D "$REVIEW_SMOKE_TMP/$label-csrf.headers" \
    -o "$REVIEW_SMOKE_TMP/$label-csrf.json" \
    -w '%{http_code}' \
    -c "$cookie_jar" \
    "$COCKPIT/api/auth/csrf")"
  test "$csrf_status" = "200"
  csrf_token="$(jq -er \
    '.csrfToken | select(type == "string" and length > 0)' \
    "$REVIEW_SMOKE_TMP/$label-csrf.json")"

  callback_status="$(curl -sS -X POST \
    -D "$REVIEW_SMOKE_TMP/$label-callback.headers" \
    -o "$REVIEW_SMOKE_TMP/$label-callback.json" \
    -w '%{http_code}' \
    -b "$cookie_jar" -c "$cookie_jar" \
    -H 'Content-Type: application/x-www-form-urlencoded' \
    --data-urlencode "csrfToken=$csrf_token" \
    --data-urlencode "token@$token_file" \
    --data-urlencode "callbackUrl=$COCKPIT/" \
    --data-urlencode 'json=true' \
    "$COCKPIT/api/auth/callback/credentials")"
  test "$callback_status" = "200"
  jq -e '.url | select(type == "string" and length > 0)' \
    "$REVIEW_SMOKE_TMP/$label-callback.json" >/dev/null
  find "$token_file" -type f -delete

  session_status="$(curl -sS \
    -D "$REVIEW_SMOKE_TMP/$label-session.headers" \
    -o "$REVIEW_SMOKE_TMP/$label-session.json" \
    -w '%{http_code}' \
    -b "$cookie_jar" \
    "$COCKPIT/api/auth/session")"
  test "$session_status" = "200"
  jq -e '.user != null' "$REVIEW_SMOKE_TMP/$label-session.json" >/dev/null
}

create_authjs_cookie_jar \
  reviewer "$NEXUS_REVIEWER_SSO_TOKEN" "$REVIEWER_COOKIE_JAR"
create_authjs_cookie_jar \
  student "$NEXUS_STUDENT_SSO_TOKEN" "$STUDENT_COOKIE_JAR"
create_authjs_cookie_jar \
  teacher "$NEXUS_TEACHER_SSO_TOKEN" "$TEACHER_COOKIE_JAR"
unset NEXUS_REVIEWER_SSO_TOKEN NEXUS_STUDENT_SSO_TOKEN NEXUS_TEACHER_SSO_TOKEN
```

Exécuter les contrôles positifs dans le même shell. Définir
`REVIEW_TARGET_ID` avec l'identifiant non sensible d'un document
`needs_review` de la collection de test.

```bash
REVIEW_COLLECTION="rag_nexus_nsi_terminale_specialite"
: "${REVIEW_TARGET_ID:?identifiant de document needs_review requis}"

# Queue de review ; collection, limit et offset sont les seuls filtres admis.
queue_status="$(curl -sS -G \
  -D "$REVIEW_SMOKE_TMP/queue.headers" \
  -o "$REVIEW_SMOKE_TMP/queue.json" \
  -w '%{http_code}' \
  -b "$REVIEWER_COOKIE_JAR" \
  --data-urlencode "collection=$REVIEW_COLLECTION" \
  --data-urlencode 'limit=50' \
  --data-urlencode 'offset=0' \
  "$COCKPIT/api/review/queue")"
assert_review_json_response 200 "$queue_status" \
  "$REVIEW_SMOKE_TMP/queue.headers" "$REVIEW_SMOKE_TMP/queue.json"
jq -e '.documents | type == "array"' \
  "$REVIEW_SMOKE_TMP/queue.json" >/dev/null

review_payload="$(jq -cn \
  --arg target_id "$REVIEW_TARGET_ID" \
  --arg collection "$REVIEW_COLLECTION" \
  '{target_type:"doc", target_id:$target_id, decision:"reviewed", collection:$collection}')"

# Approuver un document. Le navigateur ne fournit ni tenant ni reason.
decide_status="$(curl -sS -X POST \
  -D "$REVIEW_SMOKE_TMP/decide.headers" \
  -o "$REVIEW_SMOKE_TMP/decide.json" \
  -w '%{http_code}' \
  -b "$REVIEWER_COOKIE_JAR" \
  -H "Content-Type: application/json" \
  --data-binary "$review_payload" \
  "$COCKPIT/api/review/decide")"
assert_review_json_response 200 "$decide_status" \
  "$REVIEW_SMOKE_TMP/decide.headers" "$REVIEW_SMOKE_TMP/decide.json"
jq -e --arg target_id "$REVIEW_TARGET_ID" \
  '.target_id == $target_id and .decision == "reviewed"' \
  "$REVIEW_SMOKE_TMP/decide.json" >/dev/null
```

Toutes les réponses de ces routes, succès comme erreurs, doivent porter
`Cache-Control: private, no-store, max-age=0`.

Contrôles négatifs à conserver lors du smoke test :

```bash
HUMAN_REVIEW_HEADER="$REVIEW_SMOKE_TMP/human-review.header"
printf 'Authorization: Bearer %s\n' "$RAG_REVIEWER_TOKEN" \
  > "$HUMAN_REVIEW_HEADER"
unset RAG_REVIEWER_TOKEN

# Un simple token humain ne satisfait ni le credential BFF ni l'identité signée.
for endpoint in queue decide; do
  if [ "$endpoint" = "queue" ]; then
    status="$(curl -sS -o /dev/null -w '%{http_code}' \
      "$API/review/v2/queue" \
      -H @"$HUMAN_REVIEW_HEADER")"
  else
    status="$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
      "$API/review/v2/decide" \
      -H @"$HUMAN_REVIEW_HEADER" \
      -H "Content-Type: application/json" \
      -d '{"tenant":"libre_terminale","target_type":"doc","target_id":"smoke-review-target","decision":"reviewed"}')"
  fi
  test "$status" = "401"
done

# Le BFF refuse student et teacher avant tout appel moteur de décision.
for role in student teacher; do
  if [ "$role" = "student" ]; then
    cookie_jar="$STUDENT_COOKIE_JAR"
  else
    cookie_jar="$TEACHER_COOKIE_JAR"
  fi
  status="$(curl -sS -X POST \
    -D "$REVIEW_SMOKE_TMP/$role-forbidden.headers" \
    -o "$REVIEW_SMOKE_TMP/$role-forbidden.json" \
    -w '%{http_code}' \
    "$COCKPIT/api/review/decide" \
    -b "$cookie_jar" \
    -H "Content-Type: application/json" \
    -d '{"target_type":"doc","target_id":"smoke-review-target","decision":"reviewed"}')"
  assert_review_json_response 403 "$status" \
    "$REVIEW_SMOKE_TMP/$role-forbidden.headers" \
    "$REVIEW_SMOKE_TMP/$role-forbidden.json"
  jq -e '.error == "forbidden"' \
    "$REVIEW_SMOKE_TMP/$role-forbidden.json" >/dev/null
done

trap - HUP INT TERM EXIT
cleanup_review_smoke
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
- [ ] Review humaine effectuée uniquement via `/api/review/*` et une session Auth.js
- [ ] Tokens distincts entre rôles
- [ ] Logs propres (`docker compose logs --tail=50 ingestor`)
- [ ] Aucun token visible dans les logs
- [ ] Backup effectué

## Contacts

- Lead technique : à définir
- Oncall : à définir
- Alertes : à configurer via Alertmanager
