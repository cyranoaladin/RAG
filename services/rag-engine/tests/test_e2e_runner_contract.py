"""Static contract checks for the LOT 27 P3 read-only E2E runner."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER = REPO_ROOT / "scripts" / "e2e" / "run-lot27-p3-ui-readonly.sh"
E2E_RUNNER = REPO_ROOT / "scripts" / "e2e" / "lot27-p3-ui-readonly.js"


def test_runner_resolves_playwright_from_its_own_script_directory() -> None:
    content = RUNNER.read_text(encoding="utf-8")

    assert 'export SCRIPT_DIR' in content
    assert '"$SCRIPT_DIR/node_modules"' in content
    assert 'paths: [process.env.SCRIPT_DIR]' in content


def test_runner_keeps_the_script_relative_e2e_entrypoint() -> None:
    content = RUNNER.read_text(encoding="utf-8")

    assert 'node "$SCRIPT_DIR/lot27-p3-ui-readonly.js"' in content


def test_rag_host_5xx_is_blocking_before_streamlit_or_static_exceptions() -> None:
    content = E2E_RUNNER.read_text(encoding="utf-8")

    server_error_rule = content.index("response.status() >= 500")
    blocking_push = content.index("networkFailuresBlocking.push(event);", server_error_rule)
    streamlit_exception = content.index("if (isStcoreEndpoint(event.url))", server_error_rule)
    static_exception = content.index("else if (isStaticAsset(event.url))", server_error_rule)

    assert server_error_rule < blocking_push < streamlit_exception < static_exception


def test_post_deploy_console_502_and_chunk_load_errors_are_not_suppressed() -> None:
    content = E2E_RUNNER.read_text(encoding="utf-8")

    assert "function isPostDeployCriticalConsoleError" in content
    assert 'entry.text.includes("ChunkLoadError")' in content
    assert 'entry.text.includes("status of 502")' in content
    assert 'entry.text.includes("MIME type")' in content
    assert "if (isPostDeployCriticalConsoleError(entry))" in content


def test_rag_host_websocket_502_is_blocking_before_streamlit_noise() -> None:
    content = E2E_RUNNER.read_text(encoding="utf-8")

    assert "function isRagHost5xxFailure" in content
    assert '"Unexpected response code: 502"' in content
    websocket_5xx_rule = content.index("if (isRagHost5xxFailure(errorText))")
    blocking_push = content.index("networkFailuresBlocking.push(entry);", websocket_5xx_rule)
    streamlit_exception = content.index("if (isStcoreEndpoint(url))", websocket_5xx_rule)

    assert websocket_5xx_rule < blocking_push < streamlit_exception


def test_e2e_requires_non_empty_screenshots_and_fails_for_network_failures() -> None:
    content = E2E_RUNNER.read_text(encoding="utf-8")

    assert "screenshotFailures" in content
    assert "statSync" in content
    assert "...screenshotFailures" in content
    assert "...networkFailuresBlocking.map" in content


def test_e2e_requires_each_expected_page_and_screenshot_before_pass() -> None:
    content = E2E_RUNNER.read_text(encoding="utf-8")

    assert "const pageResults" in content
    assert "validatePageArtifacts" in content
    assert "pageResults.length !== PAGES.length" in content
    assert "Page PASS" in content
