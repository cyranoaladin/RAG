"""Contract tests for the fail-closed embedding smoke script."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = REPO_ROOT / "scripts" / "e2e" / "smoke-embedding-contract.sh"
EXECUTION_MARKER = "EMBEDDING_CONTRACT_PYTHON_HEREDOC_EXECUTED"


def _source() -> str:
    return SMOKE_SCRIPT.read_text(encoding="utf-8")


def _without_shell_comments(source: str) -> str:
    return "\n".join(
        line for line in source.splitlines() if not line.lstrip().startswith("#")
    )


def test_smoke_attaches_stdin_to_the_container_python_process() -> None:
    source = _source()

    assert 'docker exec -i "$api_container" python3 - <<\'PY\'' in source
    assert 'docker exec "$api_container" python3 - <<' not in source


def test_smoke_requires_proof_that_the_python_heredoc_executed() -> None:
    source = _source()

    assert EXECUTION_MARKER in source
    assert 'grep -Fqx "$execution_marker"' in source
    assert "EMBEDDING_CONTRACT_PYTHON_HEREDOC_NOT_EXECUTED" in source


def test_smoke_fails_when_docker_succeeds_without_executing_python(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_docker = tmp_path / "docker"
    fake_docker.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_docker.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:/usr/bin:/bin")

    result = subprocess.run(
        ["bash", str(SMOKE_SCRIPT)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "EMBEDDING_CONTRACT_PYTHON_HEREDOC_NOT_EXECUTED" in result.stderr


def test_smoke_has_no_legacy_embedding_fallback() -> None:
    assert "nomic-embed-text:v1.5" not in _source()


def test_smoke_has_no_model_download_command() -> None:
    executable_source = _without_shell_comments(_source())

    for command in ("pull", "download", "wget", "curl"):
        assert re.search(rf"\b{command}\b", executable_source, re.IGNORECASE) is None


def test_smoke_has_no_ingestion_command() -> None:
    executable_source = _without_shell_comments(_source())

    assert re.search(
        r"(?:/ingest(?:ion)?\b|\bingest_v2\b|\benqueue_ingestion\b)",
        executable_source,
        re.IGNORECASE,
    ) is None


def test_smoke_has_no_database_write_statement() -> None:
    source = _source()

    assert re.search(
        r"\b(?:insert\s+into|update|delete\s+from|truncate)\b",
        source,
        re.IGNORECASE,
    ) is None
