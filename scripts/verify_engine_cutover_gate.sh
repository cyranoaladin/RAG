#!/usr/bin/env bash
# ==============================================================================
# scripts/verify_engine_cutover_gate.sh
#
# Porte de franchissement (Gate) pour la bascule vers le Cockpit.
# Doit être exécuté par le chantier de migration du moteur rag-engine.
# Code de sortie 0 = Gate validée, bascule Phase 2 autorisée.
# Code de sortie 1 = Rejet, moteur non conforme.
# ==============================================================================
set -euo pipefail

ENGINE_URL="${1:-http://127.0.0.1:8001}"
ENGINE_INTERNAL_TOKEN="${RAG_ENGINE_INTERNAL_TOKEN:-}"

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log_info() { echo -e "[GATE CHECK] $*"; }
log_pass() { echo -e "[GATE CHECK] ${GREEN}PASS${NC}: $*"; }
log_fail() { echo -e "[GATE CHECK] ${RED}FAIL${NC}: $*"; }

FAILURES=0

# ------------------------------------------------------------------------------
# 1. Assertion 1 : Rejet sans identité signée (Fail-Closed Auth)
#    POST /search/v2 sans header X-Nexus-Identity doit retourner STRICTEMENT 401.
# ------------------------------------------------------------------------------
log_info "1/3 Vérification du rejet sans enveloppe X-Nexus-Identity..."
HTTP_CODE_NO_AUTH=$(curl -s -o /dev/null -w "%{http_code}" \
  -X POST "${ENGINE_URL}/search/v2" \
  -H "Content-Type: application/json" \
  -d '{"need":{"intent":"context","query":"test"}}' || true)

if [ "${HTTP_CODE_NO_AUTH}" = "401" ]; then
  log_pass "POST /search/v2 sans X-Nexus-Identity a bien retourné HTTP 401 (rejet sécurisé)."
else
  log_fail "Attendu HTTP 401, reçu HTTP ${HTTP_CODE_NO_AUTH}."
  FAILURES=$((FAILURES + 1))
fi

# ------------------------------------------------------------------------------
# 2. Assertion 2 : Endpoint de diagnostic readiness opérationnel
#    GET /collections/readiness avec token doit retourner HTTP 200.
# ------------------------------------------------------------------------------
log_info "2/3 Vérification de GET /collections/readiness..."
AUTH_HEADER=()
if [ -n "${ENGINE_INTERNAL_TOKEN}" ]; then
  AUTH_HEADER=(-H "Authorization: Bearer ${ENGINE_INTERNAL_TOKEN}")
fi

HTTP_CODE_READINESS=$(curl -s -o /dev/null -w "%{http_code}" \
  -X GET "${ENGINE_URL}/collections/readiness" \
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
HTTP_CODE_SEARCH=$(curl -s -w "%{http_code}" -o "${SEARCH_RESPONSE_FILE}" \
  -X POST "${ENGINE_URL}/search/v2" \
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
  log_pass "GATE VÉRIFIÉE (0 échec). Le moteur est prêt pour la Phase 2 (Bascule Cockpit)."
  exit 0
else
  log_fail "GATE REFUSÉE (${FAILURES} assertion(s) en échec). Ne pas basculer."
  exit 1
fi
