from __future__ import annotations

import builtins
import importlib.util
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest
import yaml

from rag_pedago.paths import REPO_ROOT

PROTOCOL_DOC = REPO_ROOT / "docs/CLEANUP_REVIEW_PROTOCOL.md"
POLICY_CONFIG = REPO_ROOT / "configs/cleanup_policy.yml"
SCRIPT = REPO_ROOT / "scripts/cleanup_review_package.py"
MAKEFILE = REPO_ROOT / "Makefile"
DATA_STAGING = REPO_ROOT / "data/staging"
PERMANENT_LEDGER = REPO_ROOT / "data/ledger/rag_pedago.sqlite"


def _load_review_module():
    spec = importlib.util.spec_from_file_location("cleanup_review_package", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_file(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _mini_workspace_config(tmp_path: Path, *, safe_count: int = 5) -> Path:
    workspace = tmp_path
    pedago = workspace / "rag-pedago"
    local = workspace / "rag-local"

    _write_file(pedago / "data/reports/codex_lot_1.md", "# Codex lot 1\n")
    _write_file(pedago / "docs/CLEANUP_POLICY.md", "# Cleanup policy\n")
    _write_file(pedago / "tests/sample.py", "print('sample')\n")
    _write_file(pedago / ".git/config", "[core]\n    repositoryformatversion = 0\n")
    for index in range(safe_count):
        _write_file(pedago / f"__pycache__/sample_{index}.pyc", "compiled")
    for index in range(3):
        _write_file(
            pedago / f"data/reports/manifest_directory_import_batch-{index}.md",
            "# Runtime report\n",
        )

    _write_file(local / ".git/config", "[core]\n    repositoryformatversion = 0\n")
    _write_file(local / ".venv/ignored.pyc", "compiled")
    _write_file(local / "patch-ci.diff", "diff --git a/x b/x\n")
    _write_file(local / ".env", "SECRET=must-not-be-read\n")
    _write_file(local / "drive_sync_state.db", "sqlite bytes\n")

    config = tmp_path / "cleanup_policy.yml"
    config.write_text(
        dedent(
            f"""
            workspace_root: {workspace.as_posix()}
            active_repo: rag-pedago
            readonly_repos:
              - rag-local

            deep_scan_exclusions:
              - "rag-local/.venv/**"
              - "rag-local/.mypy_cache/**"
              - "rag-local/.pytest_cache/**"
              - "rag-local/.ruff_cache/**"
              - "**/.git/**"

            summarize_only_roots:
              - "rag-local/.venv"
              - "rag-local/.mypy_cache"
              - "rag-local/.pytest_cache"
              - "rag-local/.ruff_cache"

            safe_delete_candidates:
              - "**/__pycache__/"
              - "**/*.pyc"
              - "**/.pytest_cache/"
              - "**/.ruff_cache/"
              - "**/.mypy_cache/"

            archive_candidates:
              - "rag-pedago/data/reports/manifest_directory_import_batch-*.md"
              - "rag-local/*.diff"

            never_delete:
              - "**/.git/**"
              - "**/.env"
              - "**/.env.*"
              - "**/*secret*"
              - "**/*credential*"
              - "**/*creds*"
              - "**/*.pem"
              - "**/*.key"
              - "**/*.sqlite"
              - "**/*.sqlite3"
              - "**/*.db"
              - "**/uploads/**"
              - "**/raw/**"
              - "**/infra/creds/**"
              - "**/creds/**"

            always_keep:
              - "rag-pedago/data/reports/codex_lot_*.md"
              - "rag-pedago/docs/**"
              - "rag-pedago/tests/**"
              - "rag-pedago/schema/**"
              - "rag-pedago/taxonomy/**"
              - "rag-pedago/data/fixtures/**"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return config


def _run_review(tmp_path: Path, capsys, *, sample_limit: int = 2, safe_count: int = 5) -> str:  # noqa: ANN001
    module = _load_review_module()
    config = _mini_workspace_config(tmp_path, safe_count=safe_count)

    status = module.main(["--config", str(config), "--sample-limit", str(sample_limit)])

    output = capsys.readouterr().out
    assert status == 0
    return output


def _ledger_marker() -> tuple[bool, int | None]:
    if not PERMANENT_LEDGER.exists():
        return False, None
    return True, PERMANENT_LEDGER.stat().st_mtime_ns


def _git_status() -> str:
    return subprocess.check_output(
        ["git", "status", "--short", "--branch"],
        cwd=REPO_ROOT,
        text=True,
    )


def test_cleanup_review_protocol_and_script_exist() -> None:
    assert PROTOCOL_DOC.is_file()
    assert SCRIPT.is_file()


def test_cleanup_review_script_has_no_destructive_api_or_options() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    forbidden_tokens = [
        "unlink(",
        "remove(",
        "rmdir(",
        "shutil.rmtree",
        "shutil.move",
        "find -delete",
        "rm -rf",
        "git clean",
        "--apply",
        "--delete",
        "--move",
        "--write",
        "--output",
        "requests",
        "httpx",
        "urllib",
        "socket",
        "subprocess",
        "docker",
        "qdrant",
        "psycopg",
    ]
    assert not any(token in text for token in forbidden_tokens)
    assert "_SPEC is not None" not in text
    assert "_SPEC.loader is not None" not in text


def test_cleanup_review_returns_markdown_package(tmp_path, capsys) -> None:  # noqa: ANN001
    output = _run_review(tmp_path, capsys)

    assert "# Cleanup review package" in output
    assert "human_review_required: true" in output
    assert "destructive_action_available: false" in output
    assert "would_delete: 0" in output
    assert "would_move: 0" in output
    assert "Les compteurs sont observationnels." in output
    assert "Les chemins listés ne valent pas autorisation d’action." in output
    for non_action in [
        "no file deleted",
        "no file moved",
        "no archive created",
        "no secret read",
        "no .env opened",
        "no ledger modified",
        "no data/staging created",
    ]:
        assert non_action in output
    for section in [
        "## Summary",
        "## Counts",
        "## Safe delete candidates — sample only",
        "## Archive candidates — sample only",
        "## Never delete matches — sample only",
        "## Always keep matches — sample only",
        "## Read-only repository matches — summary",
        "## Deep scan exclusions",
        "## Human decision checklist",
        "## Explicit non-actions",
    ]:
        assert section in output


def test_cleanup_review_limits_samples(tmp_path, capsys) -> None:  # noqa: ANN001
    output = _run_review(tmp_path, capsys, sample_limit=3, safe_count=6)

    assert "sample_limit: 3" in output
    assert "sample_0.pyc" in output
    assert "sample_1.pyc" in output
    assert "sample_2.pyc" not in output


def test_cleanup_review_cli_subprocess_outputs_markdown(tmp_path) -> None:
    config = _mini_workspace_config(tmp_path)

    result = subprocess.run(
        [
            "python3",
            "scripts/cleanup_review_package.py",
            "--config",
            str(config),
            "--sample-limit",
            "2",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "# Cleanup review package" in result.stdout
    assert "human_review_required: true" in result.stdout
    assert "destructive_action_available: false" in result.stdout
    assert "would_delete: 0" in result.stdout
    assert "would_move: 0" in result.stdout
    assert "sample_limit: 2" in result.stdout
    assert "error" not in result.stderr.lower()


def test_cleanup_review_cli_python_optimized_mode_outputs_markdown(tmp_path) -> None:
    config = _mini_workspace_config(tmp_path)

    result = subprocess.run(
        [
            "python3",
            "-O",
            "scripts/cleanup_review_package.py",
            "--config",
            str(config),
            "--sample-limit",
            "2",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "# Cleanup review package" in result.stdout
    assert "human_review_required: true" in result.stdout
    assert "destructive_action_available: false" in result.stdout
    assert "would_delete: 0" in result.stdout
    assert "would_move: 0" in result.stdout


def test_cleanup_review_rejects_invalid_sample_limit(tmp_path) -> None:
    config = _mini_workspace_config(tmp_path)

    result = subprocess.run(
        [
            "python3",
            "scripts/cleanup_review_package.py",
            "--config",
            str(config),
            "--sample-limit",
            "0",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "sample-limit" in result.stderr
    assert "between 1 and 200" in result.stderr


def test_cleanup_review_rejects_too_large_sample_limit(tmp_path) -> None:
    config = _mini_workspace_config(tmp_path)

    result = subprocess.run(
        [
            "python3",
            "scripts/cleanup_review_package.py",
            "--config",
            str(config),
            "--sample-limit",
            "100000",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "sample-limit" in result.stderr
    assert "between 1 and 200" in result.stderr


def test_cleanup_review_writes_no_files(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_review_module()
    config = _mini_workspace_config(tmp_path)
    original_path_open = Path.open

    def fail_write_text(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError(f"cleanup review must not write text files: {path}")

    def fail_write_bytes(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        raise AssertionError(f"cleanup review must not write binary files: {path}")

    def guard_path_open(path, mode="r", *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if any(flag in mode for flag in ("w", "a", "x", "+")):
            raise AssertionError(f"cleanup review must not open files for writing: {path}")
        return original_path_open(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_write_text)
    monkeypatch.setattr(Path, "write_bytes", fail_write_bytes)
    monkeypatch.setattr(Path, "open", guard_path_open)

    assert module.main(["--config", str(config), "--sample-limit", "2"]) == 0


def test_cleanup_review_does_not_read_env_contents(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_review_module()
    config = _mini_workspace_config(tmp_path)
    original_builtin_open = builtins.open
    original_path_open = Path.open

    def fail_env_open(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        path_name = Path(str(path)).name
        if path_name == ".env" or path_name.startswith(".env."):
            raise AssertionError("cleanup review must not open .env files")
        return original_builtin_open(path, *args, **kwargs)

    def fail_env_path_open(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if path.name == ".env" or path.name.startswith(".env."):
            raise AssertionError("cleanup review must not open .env files")
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_env_open)
    monkeypatch.setattr(Path, "open", fail_env_path_open)

    assert module.main(["--config", str(config), "--sample-limit", "2"]) == 0


def test_cleanup_review_does_not_descend_into_git_directories(tmp_path, capsys) -> None:  # noqa: ANN001
    output = _run_review(tmp_path, capsys, sample_limit=5)

    assert "rag-pedago/.git" in output
    assert "rag-local/.git" in output
    assert "rag-pedago/.git/config" not in output
    assert "rag-local/.git/config" not in output


def test_cleanup_review_does_not_follow_symlinks(tmp_path, capsys) -> None:  # noqa: ANN001
    workspace = tmp_path / "workspace"
    config = _mini_workspace_config(workspace)
    outside_heavy = tmp_path / "outside-heavy"
    _write_file(outside_heavy / "hidden.pyc", "compiled")
    link_path = workspace / "rag-pedago/link-to-outside-heavy"
    try:
        link_path.symlink_to(outside_heavy, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink not supported: {exc}")

    module = _load_review_module()
    assert module.main(["--config", str(config), "--sample-limit", "5"]) == 0
    output = capsys.readouterr().out
    assert "hidden.pyc" not in output
    assert "link-to-outside-heavy" not in output


def test_cleanup_review_does_not_modify_git_status_staging_or_ledger() -> None:
    module = _load_review_module()
    before_status = _git_status()
    ledger_existed, ledger_mtime = _ledger_marker()
    _staging_before = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()

    assert module.main([]) == 0

    assert _git_status() == before_status
    # Staging may exist (legitimate content); verify module didn't modify it
    _staging_after = set(DATA_STAGING.rglob("*")) if DATA_STAGING.exists() else set()
    assert _staging_after == _staging_before, "module must not create/modify staging"
    assert PERMANENT_LEDGER.exists() is ledger_existed
    if ledger_existed:
        assert PERMANENT_LEDGER.stat().st_mtime_ns == ledger_mtime


def test_cleanup_review_makefile_target_exists_and_is_non_destructive() -> None:
    text = MAKEFILE.read_text(encoding="utf-8")
    assert "cleanup-review:" in text
    assert "$(PY) scripts/cleanup_review_package.py" in text
    for forbidden_target in [
        "cleanup-apply",
        "cleanup-delete",
        "cleanup-move",
        "cleanup-archive",
    ]:
        assert forbidden_target not in text


def test_cleanup_policy_keeps_rag_local_readonly() -> None:
    config = yaml.safe_load(POLICY_CONFIG.read_text(encoding="utf-8"))
    assert "rag-local" in config["readonly_repos"]
