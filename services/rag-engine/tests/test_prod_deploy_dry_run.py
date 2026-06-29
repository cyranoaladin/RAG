from __future__ import annotations

import os
import subprocess
from pathlib import Path

ENGINE_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ENGINE_ROOT.parents[1]
SCRIPT_PATH = ENGINE_ROOT / "scripts" / "prod_deploy_dry_run.sh"


def _fake_git_bin(tmp_path: Path, *, branch: str = "main", status: str = "", sha: str = "abc123") -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git_script = bin_dir / "git"
    git_script.write_text(
        f"""#!/usr/bin/env sh
set -eu
if [ "$1" = "branch" ] && [ "${{2:-}}" = "--show-current" ]; then
  printf '%s\\n' "{branch}"
elif [ "$1" = "status" ] && [ "${{2:-}}" = "--short" ]; then
  printf '%s' "{status}"
elif [ "$1" = "rev-parse" ] && [ "${{2:-}}" = "HEAD" ]; then
  printf '%s\\n' "{sha}"
elif [ "$1" = "rev-parse" ] && [ "${{2:-}}" = "--show-toplevel" ]; then
  printf '%s\\n' "{REPO_ROOT}"
else
  echo "unexpected git invocation: $*" >&2
  exit 2
fi
""",
        encoding="utf-8",
    )
    git_script.chmod(0o755)
    return bin_dir


def _run_script(
    tmp_path: Path,
    *,
    branch: str = "main",
    status: str = "",
    sha: str = "abc123",
    extra_args: list[str] | None = None,
    prod_target: str | None = "/srv/nexusreussite/rag-ui/compose",
) -> subprocess.CompletedProcess[str]:
    bin_dir = _fake_git_bin(tmp_path, branch=branch, status=status, sha=sha)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    if prod_target is not None:
        env["PROD_TARGET"] = prod_target
    else:
        env.pop("PROD_TARGET", None)
    return subprocess.run(  # noqa: UP022 - tests inspect stdout/stderr separately.
        [
            "bash",
            str(SCRIPT_PATH),
            "--confirm-readonly",
            "--expected-sha",
            sha,
            *(extra_args or []),
        ],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )


def test_dry_run_generates_only_rsync_nci_commands(tmp_path: Path) -> None:
    result = _run_script(tmp_path)

    assert result.returncode == 0
    assert "rsync -nci" in result.stdout
    assert "--delete" not in result.stdout
    assert "services/rag-engine/src/ingestor/api.py" in result.stdout
    assert "services/rag-engine/src/ingestor/admin_api.py" in result.stdout
    assert "services/rag-engine/src/ingestor/collection_config.py" in result.stdout
    assert "services/rag-engine/src/ingestor/retrieval_contract_adapter.py" in result.stdout
    assert "services/rag-engine/src/ui/app_v2.py" in result.stdout
    assert "services/rag-engine/configs/rag_collections.yml" in result.stdout
    assert "services/rag-engine/configs/legacy_collection_mapping.yml" in result.stdout
    assert ".env" not in result.stdout
    assert "creds" not in result.stdout
    assert "chroma" not in result.stdout.lower()
    assert "catalog.sqlite" not in result.stdout


def test_dry_run_refuses_non_main_branch(tmp_path: Path) -> None:
    result = _run_script(tmp_path, branch="lot-20-prod-preflight-rag-ui")

    assert result.returncode != 0
    assert "main" in result.stderr


def test_dry_run_refuses_dirty_workspace(tmp_path: Path) -> None:
    result = _run_script(tmp_path, status=" M README.md\n")

    assert result.returncode != 0
    assert "workspace" in result.stderr.lower()


def test_dry_run_refuses_missing_target(tmp_path: Path) -> None:
    result = _run_script(tmp_path, prod_target=None)

    assert result.returncode != 0
    assert "PROD_TARGET" in result.stderr


def test_dry_run_refuses_without_readonly_confirmation(tmp_path: Path) -> None:
    bin_dir = _fake_git_bin(tmp_path)
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}:{env['PATH']}"
    env["PROD_TARGET"] = "/srv/nexusreussite/rag-ui/compose"

    result = subprocess.run(  # noqa: UP022 - tests inspect stdout/stderr separately.
        ["bash", str(SCRIPT_PATH), "--expected-sha", "abc123"],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--confirm-readonly" in result.stderr


def test_dry_run_refuses_sha_mismatch(tmp_path: Path) -> None:
    result = _run_script(tmp_path, sha="actual", extra_args=["--expected-sha", "expected"])

    assert result.returncode != 0
    assert "SHA" in result.stderr
