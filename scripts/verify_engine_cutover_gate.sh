#!/usr/bin/env bash
# ==============================================================================
# scripts/verify_engine_cutover_gate.sh
#
# Porte de franchissement (Gate) pour la bascule vers le Cockpit.
# Doit être exécuté STRICTEMENT contre le serveur de production distant.
#
# Code de sortie 0 = Gate validée, bascule Phase 2 autorisée.
# Code de sortie 1 = Rejet, moteur non conforme ou cible invalide.
# ==============================================================================
set -euo pipefail

TARGET_URL="${1:-https://rag-api.nexusreussite.academy}"
ENGINE_INTERNAL_TOKEN="${RAG_ENGINE_INTERNAL_TOKEN:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log_info() { echo -e "[GATE CHECK] $*"; }
log_pass() { echo -e "[GATE CHECK] ${GREEN}PASS${NC}: $*"; }
log_fail() { echo -e "[GATE CHECK] ${RED}FAIL${NC}: $*"; }

echo "======================================================================"
log_info "CIBLE INTERROGÉE : ${TARGET_URL}"
echo "======================================================================"

# ------------------------------------------------------------------------------
# 0. Garde-fou strict anti-localhost / adresses privées
# ------------------------------------------------------------------------------
TARGET_HOST=$(python3 -c "from urllib.parse import urlparse; import sys; print(urlparse(sys.argv[1]).hostname or '')" "${TARGET_URL}")

if [ -z "${TARGET_HOST}" ]; then
  log_fail "URL cible invalide ou sans hôte : ${TARGET_URL}"
  exit 1
fi

IS_LOCAL_OR_PRIVATE=$(python3 -c "
import ipaddress, sys
host = sys.argv[1].lower()
if host in {'localhost', '127.0.0.1', '0.0.0.0', '::1'}:
    print('TRUE')
    sys.exit(0)
try:
    ip = ipaddress.ip_address(host)
    if ip.is_private or ip.is_loopback or ip.is_link_local:
        print('TRUE')
        sys.exit(0)
except ValueError:
    pass
print('FALSE')
" "${TARGET_HOST}")

if [ "${IS_LOCAL_OR_PRIVATE}" = "TRUE" ]; then
  log_fail "REFUS STRICT : La porte de franchissement ne doit JAMAIS être lancée contre localhost ou une adresse privée (${TARGET_HOST})."
  log_fail "Raison : Le poste local parle déjà le contrat moderne et produirait un faux positif (validation d'un moteur non migré en production)."
  exit 1
fi

FAILURES=0

# ------------------------------------------------------------------------------
# 1. Assertion 1 : Rejet sans identité signée (Fail-Closed Auth)
#    POST /search/v2 sans header X-Nexus-Identity doit retourner STRICTEMENT 401.
# ------------------------------------------------------------------------------
log_info "1/3 Vérification du rejet sans enveloppe X-Nexus-Identity sur ${TARGET_URL}/search/v2..."
HTTP_CODE_NO_AUTH=$(curl -s -k -o /dev/null -w "%{http_code}" \
  -X POST "${TARGET_URL}/search/v2" \
  -H "Content-Type: application/json" \
  -d '{"need":{"intent":"context","query":"test"}}' || true)

if [ "${HTTP_CODE_NO_AUTH}" = "401" ]; then
  log_pass "POST /search/v2 sans X-Nexus-Identity a bien retourné HTTP 401 (rejet sécurisé)."
else
  log_fail "POST /search/v2 sans X-Nexus-Identity : attendu HTTP 401, reçu HTTP ${HTTP_CODE_NO_AUTH}."
  FAILURES=$((FAILURES + 1))
fi

# ------------------------------------------------------------------------------
# 2. Assertion 2 : Endpoint de diagnostic readiness opérationnel
#    GET /collections/readiness avec token doit retourner HTTP 200.
# ------------------------------------------------------------------------------
log_info "2/3 Vérification de GET /collections/readiness sur ${TARGET_URL}..."
AUTH_HEADER=()
if [ -n "${ENGINE_INTERNAL_TOKEN}" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${ENGINE_INTERNAL_TOKEN}")
fi

HTTP_CODE_READINESS=$(curl -s -k -o /dev/null -w "%{http_code}" \
  -X GET "${TARGET_URL}/collections/readiness" \
  "${AUTH_HEADER[@]}" || true)

if [ "${HTTP_CODE_READINESS}" = "200" ]; then
  log_pass "GET /collections/readiness a retourné HTTP 200."
else
  log_fail "GET /collections/readiness a retourné HTTP ${HTTP_CODE_READINESS} (attendu 200)."
  FAILURES=$((FAILURES + 1))
fi

# ------------------------------------------------------------------------------
# 3. Assertion 3 : Validation stricte de RetrievalResponse contre packages/contracts
#    POST /search/v2 valide doit renvoyer une réponse validant le schéma Pydantic.
# ------------------------------------------------------------------------------
log_info "3/3 Validation stricte du schéma RetrievalResponse (packages/contracts)..."

PYTHON_VALIDATOR=$(cat << 'PYEOF'
import sys
import json
try:
    from nexus_contracts.retrieval import RetrievalResponse
    payload = json.load(sys.stdin)
    RetrievalResponse.model_validate(payload)
    print("VALID_CONTRACT")
except Exception as exc:
    print(f"INVALID_CONTRACT: {exc}", file=sys.stderr)
    sys.exit(1)
PYEOF
)

SAMPLE_REQUEST='{
  "student_profile": {
    "niveau": "terminale",
    "voie": "gen",
    "matieres": ["nsi"],
    "statut_enseignement": "specialite",
    "candidat": "scolarise",
    "school_year": "2025-2026",
    "zone": "fr"
  },
  "need": {
    "intent": "context",
    "query": "arbres binaires"
  },
  "retrieval": {
    "k": 3,
    "hybrid": true,
    "rerank": true,
    "include_citations": true
  }
}'

SEARCH_RESPONSE_FILE=$(mktemp)
HTTP_CODE_SEARCH=$(curl -s -k -w "%{http_code}" -o "${SEARCH_RESPONSE_FILE}" \
  -X POST "${TARGET_URL}/search/v2" \
  -H "Content-Type: application/json" \
  "${AUTH_HEADER[@]}" \
  -d "${SAMPLE_REQUEST}" || true)

if [ "${HTTP_CODE_SEARCH}" != "200" ]; then
  log_fail "POST /search/v2 a échoué avec HTTP ${HTTP_CODE_SEARCH}."
  FAILURES=$((FAILURES + 1))
else
  if python3 -c "${PYTHON_VALIDATOR}" < "${SEARCH_RESPONSE_FILE}" 2>/dev/null; then
    log_pass "La réponse de /search/v2 est strictement conforme au schéma RetrievalResponse."
  else
    log_fail "La structure JSON retournée viole le contrat canonique RetrievalResponse."
    FAILURES=$((FAILURES + 1))
  fi
fi
rm -f "${SEARCH_RESPONSE_FILE}"

# ------------------------------------------------------------------------------
# Décision Gate
# ------------------------------------------------------------------------------
echo "----------------------------------------------------------------------"
if [ "${FAILURES}" -eq 0 ]; then
  log_pass "GATE VÉRIFIÉE pour la cible ${TARGET_URL} (0 échec). Bascule Phase 2 autorisée."
  exit 0
else
  log_fail "GATE REFUSÉE pour la cible ${TARGET_URL} (${FAILURES} assertion(s) en échec). Ne pas basculer."
  exit 1
fi
