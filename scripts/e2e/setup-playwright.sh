#!/usr/bin/env bash
# Explicit, manual dependency installation for the separately-triggered E2E.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
npm install --package-lock=false --save-exact
npx playwright install chromium
