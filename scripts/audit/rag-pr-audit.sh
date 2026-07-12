#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "${REPO_ROOT}"

echo "=============================="
echo "  RAG PR Audit"
echo "=============================="

echo ""
echo "--- rag-engine targeted tests ---"
cd services/rag-engine
PYTHONPATH=src .venv/bin/python -m pytest -q \
  tests/test_prod_preflight_check.py \
  tests/test_prod_compose_config_mount.py \
  tests/test_security_v2.py \
  tests/test_retrieval_v2_endpoint.py \
  tests/test_review_v2.py \
  tests/test_review_visibility.py

echo ""
echo "--- rag-engine make test ---"
make test

cd "${REPO_ROOT}"

echo ""
echo "--- governance locks ---"
bash scripts/check-governance-locks.sh

echo ""
echo "--- governance guard tests ---"
bash scripts/tests/test-governance-locks.sh

echo ""
echo "--- ci-local ---"
bash scripts/ci-local.sh

echo ""
echo "--- git diff check ---"
git diff --check

echo ""
echo "--- invariant checks ---"

if grep -R "review_status IN ('reviewed', 'needs_review')" \
  services/rag-engine/src/ingestor/retrieval_v2_endpoint.py 2>/dev/null; then
  echo "FAIL: needs_review found in search v2"
  exit 1
fi
echo "OK: no needs_review in search v2"

if grep -R "^<<<<<<<\|^>>>>>>>" \
  services/rag-engine/src/ingestor \
  services/rag-engine/tests \
  docs/reports 2>/dev/null; then
  echo "FAIL: merge conflict markers found"
  exit 1
fi
echo "OK: no merge conflicts"

if grep -R "même jeton que /ingest\|same token as /ingest" \
  services/rag-engine/README-PROD.md \
  services/rag-engine/docs/admin_api.md 2>/dev/null; then
  echo "FAIL: stale admin doc references ingest token"
  exit 1
fi
echo "OK: no stale admin docs"

if grep -R 'TRUSTED_PROXY_CIDRS_DEFAULT=.*172.16.0.0/12' \
  services/rag-engine/infra/scripts/provision-prod.sh 2>/dev/null; then
  echo "FAIL: broad trusted proxy default (172.16/12)"
  exit 1
fi
if grep -R 'TRUSTED_PROXY_CIDRS_DEFAULT=.*10.0.0.0/8' \
  services/rag-engine/infra/scripts/provision-prod.sh 2>/dev/null; then
  echo "FAIL: broad trusted proxy default (10/8)"
  exit 1
fi
if grep -R 'TRUSTED_PROXY_CIDRS_DEFAULT=.*192.168.0.0/16' \
  services/rag-engine/infra/scripts/provision-prod.sh 2>/dev/null; then
  echo "FAIL: broad trusted proxy default (192.168/16)"
  exit 1
fi
if grep -R "addr show docker0" \
  services/rag-engine/infra/scripts/provision-prod.sh 2>/dev/null; then
  echo "FAIL: provision-prod.sh detects docker0 for trusted proxy"
  exit 1
fi
echo "OK: no broad trusted proxy default, no docker0 detection"

if grep -R 'ALLOWLIST_DEFAULT=.*10.0.0.0/8' \
  services/rag-engine/infra/scripts/provision-prod.sh 2>/dev/null; then
  echo "FAIL: broad allowlist default (10/8)"
  exit 1
fi
if grep -R 'ALLOWLIST_DEFAULT=.*172.16.0.0/12' \
  services/rag-engine/infra/scripts/provision-prod.sh 2>/dev/null; then
  echo "FAIL: broad allowlist default (172.16/12)"
  exit 1
fi
if grep -R 'ALLOWLIST_DEFAULT=.*192.168.0.0/16' \
  services/rag-engine/infra/scripts/provision-prod.sh 2>/dev/null; then
  echo "FAIL: broad allowlist default (192.168/16)"
  exit 1
fi
echo "OK: no broad allowlist default"

if grep -R "https://img.icons8.com" \
  services/rag-engine/src/ui 2>/dev/null; then
  echo "FAIL: external CDN icon in UI"
  exit 1
fi
echo "OK: no external CDN icon"

if grep -R "88\.99\.254\.59" \
  services/rag-engine/infra/nginx 2>/dev/null; then
  echo "FAIL: hardcoded IP in nginx config"
  exit 1
fi
echo "OK: no hardcoded IP in nginx"

if grep -R "changez_ceci_par_votre_token" \
  services/rag-engine/src/ui 2>/dev/null; then
  echo "FAIL: placeholder token in UI .env"
  exit 1
fi
echo "OK: no placeholder token in UI"

if grep -P "^(?!.*NOT_).*GO_LIVE_READY" \
  docs/reports/lot_26_4_production_readiness.md 2>/dev/null; then
  echo "FAIL: report still claims GO_LIVE_READY"
  exit 1
fi
echo "OK: report does not claim GO_LIVE_READY"

echo ""
echo "=============================="
echo "  RAG PR AUDIT — ALL PASS"
echo "=============================="
