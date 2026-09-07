from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ingestor import r1_attempt_preflight_cli
from ingestor.r1_operator_flow import EXPECTED_SEALED_RELEASE_REGISTRY_SHA256


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git", "init", "-q", cwd=repo)
    _run("git", "config", "user.email", "fixture@example.invalid", cwd=repo)
    _run("git", "config", "user.name", "Fixture", cwd=repo)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    _run("git", "add", "README.md", cwd=repo)
    _run("git", "commit", "-q", "-m", "initial", cwd=repo)
    return repo


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


def _sealed_release_registry(tmp_path: Path) -> Path:
    real_registry = (
        Path(__file__).resolve().parents[2]
        / "rag-pedago"
        / "data"
        / "releases"
        / "prerentree_2026_2027"
        / "release-registry.json"
    )
    target = tmp_path / "release-registry.json"
    target.write_bytes(real_registry.read_bytes())
    return target


def test_preflight_succeeds_and_prints_attempt_state(
    git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _head(git_repo)
    registry = _sealed_release_registry(tmp_path)
    evidence_dir = tmp_path / "evidence"

    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
            "--release-registry-path",
            str(registry),
            "--release-id",
            "production-profile-gate-2026-2027-v1",
            "--evidence-dir",
            str(evidence_dir),
        ]
    )

    assert result == 0
    captured = capsys.readouterr()
    assert "R1_PREFLIGHT_READY=YES" in captured.out
    assert "R1_ATTEMPT_ID=" in captured.out
    assert "BOOTSTRAP_OUT=" in captured.out
    assert "REPORT_OUT=" in captured.out
    assert evidence_dir.is_dir()


def test_preflight_fails_on_qualified_commit_mismatch_before_any_secret(
    git_repo: Path, tmp_path: Path
) -> None:
    registry = _sealed_release_registry(tmp_path)
    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            "0" * 40,
            "--release-registry-path",
            str(registry),
            "--release-id",
            "production-profile-gate-2026-2027-v1",
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ]
    )
    assert result == 2


def test_preflight_fails_on_dirty_worktree(git_repo: Path, tmp_path: Path) -> None:
    (git_repo / "README.md").write_text("dirty\n", encoding="utf-8")
    head = _head(git_repo)
    registry = _sealed_release_registry(tmp_path)

    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
            "--release-registry-path",
            str(registry),
            "--release-id",
            "production-profile-gate-2026-2027-v1",
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ]
    )
    assert result == 2


def test_preflight_fails_on_release_registry_digest_mismatch(
    git_repo: Path, tmp_path: Path
) -> None:
    head = _head(git_repo)
    tampered = tmp_path / "release-registry.json"
    tampered.write_bytes(b'{"tampered": true}')
    assert EXPECTED_SEALED_RELEASE_REGISTRY_SHA256  # sanity: constant is set

    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
            "--release-registry-path",
            str(tampered),
            "--release-id",
            "production-profile-gate-2026-2027-v1",
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ]
    )
    assert result == 2


def test_preflight_fails_when_evidence_dir_is_inside_the_repo(
    git_repo: Path, tmp_path: Path
) -> None:
    head = _head(git_repo)
    registry = _sealed_release_registry(tmp_path)

    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
            "--release-registry-path",
            str(registry),
            "--release-id",
            "production-profile-gate-2026-2027-v1",
            "--evidence-dir",
            str(git_repo / "evidence"),
        ]
    )
    assert result == 2
    assert not (git_repo / "evidence").exists()


def test_second_invocation_without_explicit_attempt_id_gets_distinct_paths(
    git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _head(git_repo)
    registry = _sealed_release_registry(tmp_path)
    evidence_dir = tmp_path / "evidence"
    args = [
        "--repo-root",
        str(git_repo),
        "--qualified-exporter-commit",
        head,
        "--release-registry-path",
        str(registry),
        "--release-id",
        "production-profile-gate-2026-2027-v1",
        "--evidence-dir",
        str(evidence_dir),
    ]

    r1_attempt_preflight_cli.main(args)
    first = capsys.readouterr().out
    r1_attempt_preflight_cli.main(args)
    second = capsys.readouterr().out

    def _bootstrap_out(output: str) -> str:
        return next(line for line in output.splitlines() if line.startswith("BOOTSTRAP_OUT="))

    assert _bootstrap_out(first) != _bootstrap_out(second)
