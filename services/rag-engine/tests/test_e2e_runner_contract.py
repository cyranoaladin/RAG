"""Static contract checks for the LOT 27 P3 read-only E2E runner."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "scripts" / "e2e" / "run-lot27-p3-ui-readonly.sh"


def test_runner_resolves_playwright_from_its_own_script_directory() -> None:
    content = RUNNER.read_text(encoding="utf-8")

    assert 'export SCRIPT_DIR' in content
    assert '"$SCRIPT_DIR/node_modules"' in content
    assert 'paths: [process.env.SCRIPT_DIR]' in content


def test_runner_keeps_the_script_relative_e2e_entrypoint() -> None:
    content = RUNNER.read_text(encoding="utf-8")

    assert 'node "$SCRIPT_DIR/lot27-p3-ui-readonly.js"' in content
