#!/usr/bin/env bash
# setup-playwright.sh — Install Playwright + Chromium for E2E tests.
# Works on Ubuntu/Debian. Uses npx from system Node.js.
set -euo pipefail

echo "=== Playwright setup ==="

if ! command -v node >/dev/null 2>&1; then
    echo "ERROR: Node.js is required. Install it first."
    exit 1
fi

if ! command -v npx >/dev/null 2>&1; then
    echo "ERROR: npx is required (comes with npm/Node.js)."
    exit 1
fi

# Install Playwright browsers (chromium only for speed)
npx playwright install chromium

# Install system deps (Ubuntu/Debian)
if command -v apt-get >/dev/null 2>&1; then
    npx playwright install-deps chromium 2>/dev/null || {
        echo "WARN: Could not install system deps automatically."
        echo "Run: sudo npx playwright install-deps chromium"
    }
fi

echo "=== Playwright ready ==="
