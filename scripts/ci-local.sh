#!/usr/bin/env bash
# ci-local.sh — Local CI reproducing the GitHub Actions pipeline.
# Runs contracts, rag-pedago, rag-engine, cockpit, and governance checks.
# Exits non-zero if any target fails.
set -uo pipefail

if [ "${NEXUS_CI_LOCAL_RUNNING:-0}" = "1" ]; then
    echo "ERROR: ci-local.sh refuse une réentrance" >&2
    exit 2
fi
export NEXUS_CI_LOCAL_RUNNING=1

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
if ! source "$SCRIPT_DIR/lib/ci-common.sh"; then
    echo "ERROR: unable to source scripts/lib/ci-common.sh" >&2
    exit 1
fi
cd "$REPO_ROOT"

PYTHON_BIN="$(command -v python3.11 || command -v python3.12 || command -v python3 || true)"
if ! require_python_311 "$PYTHON_BIN"; then
    exit 1
fi
echo "Using Python executable: $PYTHON_BIN ($($PYTHON_BIN --version))"

NODE_BIN="$(command -v node || true)"
if ! require_node_2222 "$NODE_BIN"; then
    exit 1
fi
echo "Using Node executable: $NODE_BIN ($($NODE_BIN --version))"

PASS=0
FAIL=0
RESULTS=()

run_target() {
    local name="$1"
    local target_exit
    shift
    echo ""
    echo "=============================="
    echo "  $name"
    echo "=============================="
    "$@"
    target_exit=$?
    if [ "$target_exit" -eq 0 ]; then
        RESULTS+=("PASS  $name")
        PASS=$((PASS + 1))
    else
        RESULTS+=("FAIL  $name")
        FAIL=$((FAIL + 1))
    fi
    return 0
}

# --- packages/contracts ---
run_contracts() {
    local venv="/tmp/ci-local-contracts-venv"
    rm -rf "$venv"
    "$PYTHON_BIN" -m venv "$venv"
    "$venv/bin/pip" install -q -e 'packages/contracts[dev]'
    "$venv/bin/python" -m pytest packages/contracts/tests -q
    "$venv/bin/python" packages/contracts/scripts/export_schemas.py \
        --output packages/contracts/schema --check
}
run_target "packages/contracts" run_contracts

# --- packages/pdf-page-policy (ADR-0046) ---
run_page_policy() {
    local venv="/tmp/ci-local-pdf-page-policy-venv"
    rm -rf "$venv"
    "$PYTHON_BIN" -m venv "$venv"
    "$venv/bin/pip" install -q -e "packages/pdf-page-policy[dev]"
    "$venv/bin/python" -c "import nexus_pdf_page_policy as p; print('pdf-page-policy:', p.POLICY_ID)"
    (cd packages/pdf-page-policy && "$venv/bin/python" -m pytest -q tests)
}
run_target "packages/pdf-page-policy" run_page_policy

# --- packages/release-chain ---
run_release_chain() {
    local venv="/tmp/ci-local-release-chain-venv"
    rm -rf "$venv"
    "$PYTHON_BIN" -m venv "$venv"
    "$venv/bin/pip" install -q -e "packages/contracts"
    "$venv/bin/pip" install -q -e "packages/pdf-page-policy"
    "$venv/bin/pip" install -q -e "packages/release-chain"
    "$venv/bin/python" -c "import nexus_release_chain; print('release-chain: import OK')"
}
run_target "packages/release-chain" run_release_chain

# --- services/rag-pedago ---
run_pedago() {
    cd "$REPO_ROOT/services/rag-pedago"
    rm -rf .venv
    "$PYTHON_BIN" -m venv .venv
    source .venv/bin/activate
    if ! make install; then
        echo "FAIL: rag-pedago install failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- lint ---"
    if ! make lint; then
        echo "FAIL: rag-pedago lint failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- typecheck ---"
    if ! make typecheck; then
        echo "FAIL: rag-pedago typecheck failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- test ---"
    local test_exit
    run_checked make test
    test_exit=$?

    if [ "$test_exit" -ne 0 ]; then
        echo "FAIL: rag-pedago tests failed (exit $test_exit)"
        deactivate 2>/dev/null || true
        cd "$REPO_ROOT"
        return "$test_exit"
    fi

    deactivate 2>/dev/null || true
    cd "$REPO_ROOT"
}
run_target "services/rag-pedago" run_pedago

# --- services/rag-engine ---
run_engine() {
    cd "$REPO_ROOT/services/rag-engine"
    if ! unset MAKEFLAGS GNUMAKEFLAGS MFLAGS MAKEFILES 2>/dev/null; then
        echo "FAIL: rag-engine make environment invalid"
        cd "$REPO_ROOT"; return 1
    fi

    rm -rf .venv
    if ! make install; then
        echo "FAIL: rag-engine install failed"
        cd "$REPO_ROOT"; return 1
    fi
    source .venv/bin/activate

    echo "--- lint ---"
    if ! make lint; then
        echo "FAIL: rag-engine lint failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- typecheck ---"
    if ! make typecheck; then
        echo "FAIL: rag-engine typecheck failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    echo "--- test ---"
    if ! make test; then
        echo "FAIL: rag-engine tests failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    if ! make test-integration-hybrid; then
        echo "FAIL: rag-engine hybrid integration failed"
        deactivate 2>/dev/null || true; cd "$REPO_ROOT"; return 1
    fi

    deactivate 2>/dev/null || true
    cd "$REPO_ROOT"
}
run_target "services/rag-engine" run_engine

# --- services/cockpit ---
run_cockpit() {
    (
        set -euo pipefail
        require_node_2222 "$NODE_BIN"
        cd "$REPO_ROOT/services/cockpit"
        npm ci
        npm run lint
        npm test -- --run
        npm run build
        npm audit
        npm audit --omit=dev
        cd "$REPO_ROOT"
        "$REPO_ROOT/services/rag-pedago/.venv/bin/python" scripts/tests/test-cockpit-snapshot-coherence.py
        bash scripts/tests/test-cockpit-clean-build.sh
    )
}
run_target "services/cockpit" run_cockpit

# --- repository hygiene ---
run_target "repository-hygiene" bash scripts/check-repository-hygiene.sh

# --- repository hygiene tests ---
run_target "repository-hygiene-tests" bash scripts/tests/test-repository-hygiene.sh

# --- CI topology tests ---
run_target "ci-topology-tests" bash scripts/tests/test-ci-local-topology.sh

# --- main protection policy tests ---
run_target "main-protection-policy-tests" \
  "$PYTHON_BIN" scripts/tests/test-main-protection-policy.py

# --- go-live evidence refresh ---
run_target "go-live-evidence-refresh-tests" "$PYTHON_BIN" scripts/tests/test-go-live-evidence-refresh.py

# --- trusted human review ---
run_target "trusted-human-review-core-tests" "$PYTHON_BIN" scripts/tests/test-trusted-human-review.py
run_target "trusted-human-review-github-tests" "$PYTHON_BIN" scripts/tests/test-trusted-human-review-github.py
run_target "trusted-human-review-workflow-tests" "$REPO_ROOT/services/rag-pedago/.venv/bin/python" scripts/tests/test-trusted-human-review-workflow.py

# --- governance locks ---
run_target "governance-locks" bash scripts/check-governance-locks.sh

# --- taxonomy validation ---
run_target "taxonomy-validation" bash -c "cd $REPO_ROOT/services/rag-pedago && source .venv/bin/activate && python scripts/validate_taxonomy.py"

# --- source evidence check (revue PR #74, round 11) ---
run_target "source-evidence-check" bash -c "cd $REPO_ROOT/services/rag-pedago && source .venv/bin/activate && python scripts/export_source_validation_evidence.py --check"

# --- governance guard tests ---
# --- qualification C1 (revue PR #153) ---
# AGENTS.md fait de cette CI locale le garde-fou quand GitHub Actions est
# indisponible. Sans ces cibles, elle rendait vert sans avoir exercé le
# périmètre promu : le gate C1 n'existait alors que dans un workflow distant.
#
# La cible est HERMÉTIQUE : elle construit son propre environnement avec les
# trois paquets locaux dont le chargeur canonique dépend. S'appuyer sur le
# `python` de l'hôte supposerait pytest installé globalement ; s'appuyer sur
# le venv d'un service supposerait que ce service dépende de
# `nexus-release-chain`, ce qu'aucun ne fait.
#
# Aucune clé n'est requise — seul le job POST-FUSION confronte le store privé.
run_target "qualification-c1" bash -c '
  set -euo pipefail
  cd "'"$REPO_ROOT"'"
  venv="${TMPDIR:-/tmp}/nexus-qualification-venv"
  if [ ! -x "$venv/bin/python" ]; then
    "'"$PYTHON_BIN"'" -m venv "$venv"
  fi
  "$venv/bin/pip" install --quiet --upgrade pip
  "$venv/bin/pip" install --quiet pytest \
    -e packages/contracts \
    -e packages/pdf-page-policy \
    -e packages/release-chain
  "$venv/bin/python" -m pytest -q scripts/qualification/tests
  "$venv/bin/python" scripts/qualification/compute_promoted_content_set.py \
    --output "${TMPDIR:-/tmp}/promoted-content-set.json"
'

run_target "governance-guard-tests" bash scripts/tests/test-governance-locks.sh

# --- ci failsafe tests ---
run_target "ci-failsafe-tests" bash scripts/tests/test-ci-local-failsafe.sh

# --- Summary ---
echo ""
echo "=============================="
echo "  CI LOCAL — SUMMARY"
echo "=============================="
for r in "${RESULTS[@]}"; do
    echo "  $r"
done
echo ""
echo "Total: $PASS passed, $FAIL failed"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
