#!/usr/bin/env bash
# ==============================================================================
# OPERATOR SIGNING GATE WRAPPER (P0-L1C)
# Orchestration transactionnelle et fail-closed de la signature opérateur.
# ==============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

EXPECTED_PR_HEAD="140b157fdb8d32b7e22fffb125d9acea4195bd28"
EXPECTED_PR_NUMBER=134
EXPECTED_KEY_ID="review-binding-v1-2026-08-25"
EXPECTED_CONTRACT_VERSION="0.14.0"
TRUST_ANCHOR_PATH="governance/trust-anchors/review-binding-v1.json"
EXPECTED_ANCHOR_SHA256="a7835fc6217fe426d9d5c7c28bb0949f05577e6258a620b2bf6a4029db0487ec"
EXPECTED_PUBLIC_KEY="1f34648789fe7ebdfde6c64197039c0ffa0cd36b98317ce7cad4836a26a058d8"
FINAL_TARGET_DIR="governance/review-bindings/prerentree-2026-2027"

PYTHON_BIN="services/rag-pedago/.venv/bin/python"

echo "=== [1/9] CONTROLE DU WORKTREE ==="
if [ -n "$(git status --porcelain)" ]; then
  echo "ERREUR: Le working tree n'est pas propre." >&2
  git status --short >&2
  exit 1
fi
echo "WORKTREE_CLEAN=YES"

echo "=== [2/9] CONTROLE DE LA VERSION DE NEXUS-CONTRACTS ==="
IMPORTED_VERSION=$("$PYTHON_BIN" -c "import importlib.metadata; print(importlib.metadata.version('nexus-contracts'))")
if [ "$IMPORTED_VERSION" != "$EXPECTED_CONTRACT_VERSION" ]; then
  echo "ERREUR: Version de nexus-contracts divergente (attendue=$EXPECTED_CONTRACT_VERSION, importée=$IMPORTED_VERSION)" >&2
  exit 1
fi
echo "CONTRACT_VERSION_MATCH=YES ($IMPORTED_VERSION)"

echo "=== [3/9] LIVE PR PREFLIGHT (AVANT SIGNATURE) ==="
if ! command -v gh >/dev/null 2>&1; then
  echo "ERREUR: La commande 'gh' est introuvable." >&2
  exit 1
fi

GITHUB_TOKEN="$(gh auth token -u cyranoaladin 2>/dev/null || true)"
if [ -z "$GITHUB_TOKEN" ]; then
  echo "ERREUR: Impossible d'obtenir le token GitHub via 'gh auth token'." >&2
  exit 1
fi

PRE_SIGN_PR_HEAD="$(gh pr view "$EXPECTED_PR_NUMBER" --repo cyranoaladin/RAG --json headRefOid --jq '.headRefOid')"
if [ "$PRE_SIGN_PR_HEAD" != "$EXPECTED_PR_HEAD" ]; then
  echo "ERREUR: HEAD PR #134 divergent avant signature (attendu=$EXPECTED_PR_HEAD, obtenu=$PRE_SIGN_PR_HEAD)" >&2
  exit 1
fi

NEXUS_GITHUB_TOKEN="$GITHUB_TOKEN" PYTHONPATH=services/rag-engine/src "$PYTHON_BIN" \
  services/rag-engine/src/ingestor/ingestion_worker/issue_review_binding_cli.py preflight \
  --repository cyranoaladin/RAG \
  --pull-request "$EXPECTED_PR_NUMBER" \
  --expected-head "$EXPECTED_PR_HEAD" \
  --key-id "$EXPECTED_KEY_ID" \
  --trust-anchor "$TRUST_ANCHOR_PATH" \
  --expected-anchor-sha256 "$EXPECTED_ANCHOR_SHA256" \
  --expected-public-key "$EXPECTED_PUBLIC_KEY" \
  --environment production

echo "LIVE_PR_PREFLIGHT_BEFORE_SIGN=PASS"

echo "=== [4/9] CREATION DU STAGING TEMPORAIRE ISOLE ==="
PRIVATE_STAGING_DIR="$(mktemp -d -t review_binding_staging_XXXXXX)"
# Nettoyage automatique du staging temporaire à la sortie
trap 'rm -rf "$PRIVATE_STAGING_DIR"' EXIT

echo "Staging privé créé dans $PRIVATE_STAGING_DIR"

echo "=== [5/9] SAISIE DU SECRET & GENERATION DANS LE STAGING ==="
read -s -p "Veuillez saisir NEXUS_REVIEW_BINDING_SIGNING_KEY: " OPERATOR_KEY && echo

(
  export NEXUS_REVIEW_BINDING_SIGNING_KEY="$OPERATOR_KEY"
  export NEXUS_GITHUB_TOKEN="$GITHUB_TOKEN"
  trap 'unset NEXUS_REVIEW_BINDING_SIGNING_KEY OPERATOR_KEY GITHUB_TOKEN' EXIT

  PYTHONPATH=scripts:services/rag-engine/src "$PYTHON_BIN" \
    scripts/review_binding_bundle_manager.py sign-all \
    --output-dir "$PRIVATE_STAGING_DIR" \
    --trust-anchor "$TRUST_ANCHOR_PATH"
)

# Purge explicite de la variable opérateur
unset OPERATOR_KEY
echo "PRIVATE_KEY_CLEANUP=DONE"

echo "=== [6/9] VERIFICATION EXHAUSTIVE DU STAGING AVANT TOUTE PROMOTION ==="
PYTHONPATH=scripts:services/rag-engine/src "$PYTHON_BIN" \
  scripts/review_binding_bundle_manager.py verify-bundle \
  --bundle-dir "$PRIVATE_STAGING_DIR" \
  --trust-anchor "$TRUST_ANCHOR_PATH" \
  --expected-head "$EXPECTED_PR_HEAD" \
  --expected-key-id "$EXPECTED_KEY_ID"

echo "STAGING_BUNDLE_VERIFICATION=PASS"

echo "=== [7/9] LIVE POST-SIGN PR CHECK (FAIL-CLOSED) ==="
POST_SIGN_PR_HEAD="$(gh pr view "$EXPECTED_PR_NUMBER" --repo cyranoaladin/RAG --json headRefOid --jq '.headRefOid')"
if [ "$POST_SIGN_PR_HEAD" != "$EXPECTED_PR_HEAD" ]; then
  echo "ERREUR CRITIQUE: Le HEAD de la PR #134 a changé pendant la signature !" >&2
  echo "Attendu: $EXPECTED_PR_HEAD" >&2
  echo "Obtenu:  $POST_SIGN_PR_HEAD" >&2
  echo "ABANDON : Le staging va être détruit, aucun fichier n'est copié dans l'arbre Git." >&2
  exit 2
fi
echo "LIVE_POST_SIGN_PR_CHECK=PASS ($POST_SIGN_PR_HEAD)"

echo "=== [8/9] PROMOTION ATOMIQUE DU STAGING VERS LE REPERTOIRE VERSIONNE ==="
mkdir -p "$FINAL_TARGET_DIR"
for f in "$PRIVATE_STAGING_DIR"/*.binding.json; do
  cp "$f" "$FINAL_TARGET_DIR/$(basename "$f")"
done
echo "STAGING_PROMOTED_TO_TARGET=YES"

echo "=== [9/9] DIFF GATE MACHINE-CHECKABLE ==="
PYTHONPATH=scripts "$PYTHON_BIN" -c "
import subprocess
import sys
from review_binding_bundle_manager import CANONICAL_AUTHORIZATION_IDS

expected_paths = {f'governance/review-bindings/prerentree-2026-2027/{aid}.binding.json' for aid in CANONICAL_AUTHORIZATION_IDS}

status_out = subprocess.check_output(['git', 'status', '--porcelain'], text=True)
changed_paths = set()
for line in status_out.strip().split('\n'):
    if not line:
        continue
    # Extraire le chemin indépendamment de ??, M, A, etc.
    path = line[3:].strip()
    changed_paths.add(path)

unexpected = changed_paths - expected_paths
missing = expected_paths - changed_paths

print(f'ACTUAL_CHANGED_PATHS={len(changed_paths)}')
print(f'EXPECTED_BINDING_PATH_COUNT={len(expected_paths)}')
print(f'UNEXPECTED_CHANGED_PATHS={len(unexpected)}')
print(f'MISSING_CHANGED_PATHS={len(missing)}')

if unexpected or missing:
    print(f'ERREUR DIFF GATE: unexpected={unexpected}, missing={missing}', file=sys.stderr)
    sys.exit(1)
else:
    print('DIFF_GATE=PASS')
"

echo ""
echo "================================================================================"
echo "SUCCÈS : Les 18 ReviewBindings ont été générés, vérifiés et promus avec succès."
echo "Vous pouvez maintenant inspecter 'git status' et exécuter le commit."
echo "================================================================================"
