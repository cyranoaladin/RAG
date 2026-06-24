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

POLICY_DOC = REPO_ROOT / "docs/CLEANUP_POLICY.md"
POLICY_CONFIG = REPO_ROOT / "configs/cleanup_policy.yml"
SCRIPT = REPO_ROOT / "scripts/cleanup_dry_run.py"
DATA_STAGING = REPO_ROOT / "data/staging"
PERMANENT_LEDGER = REPO_ROOT / "data/ledger/rag_pedago.sqlite"


def _load_cleanup_module():
    spec = importlib.util.spec_from_file_location("cleanup_dry_run", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


def _write_file(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _mini_workspace_config(tmp_path: Path) -> Path:
    workspace = tmp_path
    pedago = workspace / "rag-pedago"
    local = workspace / "rag-local"

    _write_file(pedago / "data/reports/codex_lot_1.md", "# Codex lot 1\n")
    _write_file(
        pedago / "data/reports/manifest_directory_import_batch-test.md",
        "# Runtime report\n",
    )
    _write_file(pedago / "docs/CLEANUP_POLICY.md", "# Cleanup policy\n")
    _write_file(pedago / "tests/sample.py", "print('sample')\n")
    _write_file(pedago / "__pycache__/sample.pyc", "compiled")
    _write_file(pedago / ".git/config", "[core]\n    repositoryformatversion = 0\n")

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


def _run_mini_dry_run(tmp_path: Path, capsys) -> str:  # noqa: ANN001
    module = _load_cleanup_module()
    config = _mini_workspace_config(tmp_path)

    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 0
    return output


def _counts_from_output(output: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in output.splitlines():
        if "_count:" not in line:
            continue
        name, value = line.split(":", maxsplit=1)
        counts[name.strip()] = int(value.strip())
    return counts


def test_cleanup_policy_files_exist() -> None:
    assert POLICY_DOC.is_file()
    assert POLICY_CONFIG.is_file()
    assert SCRIPT.is_file()


def test_cleanup_script_has_no_destructive_api_or_apply_options() -> None:
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
    ]
    assert not any(token in text for token in forbidden_tokens)


def test_cleanup_dry_run_returns_zero_and_reports_non_destructive_counts_on_mini_workspace(
    tmp_path,
    capsys,
) -> None:
    output = _run_mini_dry_run(tmp_path, capsys)

    assert "cleanup dry-run report" in output
    assert "would_delete: 0" in output
    assert "would_move: 0" in output
    assert "readonly_repo: rag-local" in output
    assert "safe_delete_candidates_count" in output
    assert "archive_candidates_count" in output
    assert "never_delete_matches_count" in output
    assert "always_keep_matches_count" in output
    assert "readonly_repo_matches_count" in output
    assert "deep_scan_exclusions_count" in output
    assert "summarize_only_roots_count" in output


def test_cleanup_dry_run_classifies_mini_workspace_candidates(tmp_path, capsys) -> None:  # noqa: ANN001
    output = _run_mini_dry_run(tmp_path, capsys)

    counts = _counts_from_output(output)
    assert counts["safe_delete_candidates_count"] > 0
    assert counts["archive_candidates_count"] > 0
    assert counts["never_delete_matches_count"] >= 2
    assert counts["always_keep_matches_count"] > 0
    assert "rag-pedago/__pycache__/sample.pyc" in output
    assert "rag-pedago/data/reports/manifest_directory_import_batch-test.md" in output
    assert "rag-local/.env" in output
    assert "rag-local/drive_sync_state.db" in output
    assert "rag-pedago/data/reports/codex_lot_1.md" in output


def test_cleanup_dry_run_skips_deep_scan_exclusions(tmp_path, capsys) -> None:  # noqa: ANN001
    output = _run_mini_dry_run(tmp_path, capsys)

    counts = _counts_from_output(output)
    assert counts["deep_scan_exclusions_count"] == 3
    assert counts["summarize_only_roots_count"] == 1
    assert "deep_scan_exclusions_sample:" in output
    assert "summarize_only_roots_sample:" in output
    assert "rag-local/.venv" in output
    assert "rag-local/.venv/ignored.pyc" not in output


def test_cleanup_dry_run_does_not_descend_into_git_directories(tmp_path, capsys) -> None:  # noqa: ANN001
    output = _run_mini_dry_run(tmp_path, capsys)

    counts = _counts_from_output(output)
    assert counts["deep_scan_exclusions_count"] >= 2
    assert "rag-pedago/.git" in output
    assert "rag-local/.git" in output
    assert "rag-pedago/.git/config" not in output
    assert "rag-local/.git/config" not in output
    assert "would_delete: 0" in output
    assert "would_move: 0" in output


def test_cleanup_dry_run_does_not_follow_symlinks(tmp_path, capsys) -> None:  # noqa: ANN001
    workspace = tmp_path / "workspace"
    config = _mini_workspace_config(workspace)
    outside_heavy = tmp_path / "outside-heavy"
    _write_file(outside_heavy / "hidden.pyc", "compiled")
    link_path = workspace / "rag-pedago/link-to-outside-heavy"

    try:
        link_path.symlink_to(outside_heavy, target_is_directory=True)
    except (NotImplementedError, OSError) as exc:
        pytest.skip(f"symlink not supported: {exc}")

    module = _load_cleanup_module()
    status = module.main(["--config", str(config)])

    output = capsys.readouterr().out
    assert status == 0
    assert "hidden.pyc" not in output
    assert "link-to-outside-heavy" not in output
    assert "would_delete: 0" in output
    assert "would_move: 0" in output


def test_cleanup_dry_run_does_not_modify_git_status_staging_or_ledger() -> None:
    module = _load_cleanup_module()
    before_status = _git_status()
    ledger_existed, ledger_mtime = _ledger_marker()

    status = module.main([])

    assert status == 0
    assert _git_status() == before_status
    assert not DATA_STAGING.exists()
    assert PERMANENT_LEDGER.exists() is ledger_existed
    if ledger_existed:
        assert PERMANENT_LEDGER.stat().st_mtime_ns == ledger_mtime


def test_cleanup_dry_run_does_not_read_env_contents(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    module = _load_cleanup_module()
    config = _mini_workspace_config(tmp_path)
    original_builtin_open = builtins.open
    original_path_open = Path.open

    def fail_env_open(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        path_text = str(path)
        name = Path(path_text).name
        if name == ".env" or name.startswith(".env."):
            raise AssertionError("cleanup dry-run must not open .env files")
        return original_builtin_open(path, *args, **kwargs)

    def fail_env_path_open(path, *args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        if path.name == ".env" or path.name.startswith(".env."):
            raise AssertionError("cleanup dry-run must not open .env files")
        return original_path_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_env_open)
    monkeypatch.setattr(Path, "open", fail_env_path_open)

    assert module.main(["--config", str(config)]) == 0


def test_cleanup_policy_config_protects_sensitive_and_project_files() -> None:
    config = yaml.safe_load(POLICY_CONFIG.read_text(encoding="utf-8"))

    never_delete = set(config["never_delete"])
    always_keep = set(config["always_keep"])
    deep_scan_exclusions = set(config["deep_scan_exclusions"])
    summarize_only_roots = set(config["summarize_only_roots"])

    for pattern in [
        "**/.env",
        "**/.env.*",
        "**/*secret*",
        "**/*credential*",
        "**/*creds*",
        "**/*.sqlite",
        "**/*.sqlite3",
        "**/*.db",
        "**/uploads/**",
        "**/raw/**",
        "**/infra/creds/**",
    ]:
        assert pattern in never_delete
    assert "rag-pedago/data/reports/codex_lot_*.md" in always_keep
    for pattern in [
        "rag-local/.venv/**",
        "rag-local/.mypy_cache/**",
        "rag-local/.pytest_cache/**",
        "rag-local/.ruff_cache/**",
        "**/.git/**",
    ]:
        assert pattern in deep_scan_exclusions
    for root in [
        "rag-local/.venv",
        "rag-local/.mypy_cache",
        "rag-local/.pytest_cache",
        "rag-local/.ruff_cache",
    ]:
        assert root in summarize_only_roots
