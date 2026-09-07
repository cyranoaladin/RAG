from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ingestor import r1_attempt_preflight_cli
from ingestor.r1_operator_flow import load_attempt_state

REAL_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "release-registry.json"
)


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """A fixture repo whose initial commit already includes the real sealed
    release registry -- Phase A derives its release-registry path from
    ``--repo-root`` alone now, never accepts it as a separate operator-
    supplied argument, so the registry must live inside the qualified
    checkout's own tree from the start."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _run("git", "init", "-q", cwd=repo)
    _run("git", "config", "user.email", "fixture@example.invalid", cwd=repo)
    _run("git", "config", "user.name", "Fixture", cwd=repo)
    (repo / "README.md").write_text("fixture\n", encoding="utf-8")
    registry = (
        repo / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
    )
    registry.parent.mkdir(parents=True)
    registry.write_bytes(REAL_REGISTRY.read_bytes())
    _run("git", "add", "README.md", str(registry.relative_to(repo)), cwd=repo)
    _run("git", "commit", "-q", "-m", "initial", cwd=repo)
    return repo


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()


@pytest.fixture(autouse=True)
def _bypass_runtime_provenance_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """This file exercises CLI argument plumbing and preflight ordering
    against throwaway temp git repos -- never against the real, currently
    running checkout -- so runtime-provenance attestation (its own,
    dedicated tests live in ``test_r1_operator_flow.py``) is bypassed here."""
    monkeypatch.setattr(
        "ingestor.r1_operator_flow.assert_runtime_bound_to_qualified_checkout",
        lambda repo_root: None,
    )


def test_preflight_succeeds_and_publishes_attempt_state(
    git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _head(git_repo)
    evidence_dir = tmp_path / "evidence"

    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
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
    assert "SEALED_RELEASE_ID=production-profile-gate-2026-2027-v1" in captured.out

    state_path_line = next(
        line for line in captured.out.splitlines() if line.startswith("R1_ATTEMPT_STATE_PATH=")
    )
    state_path = Path(state_path_line.removeprefix("R1_ATTEMPT_STATE_PATH="))
    assert state_path.is_file()
    assert (state_path.stat().st_mode & 0o777) == 0o600

    state = load_attempt_state(state_path)
    assert state.qualified_exporter_commit == head
    assert state.sealed_release_id == "production-profile-gate-2026-2027-v1"


@pytest.mark.parametrize("flag", ["--release-id", "--attempt-id", "--generated-at"])
def test_preflight_never_accepts_governed_facts_as_ordinary_operator_flags(
    git_repo: Path, tmp_path: Path, flag: str
) -> None:
    head = _head(git_repo)
    with pytest.raises(SystemExit):
        r1_attempt_preflight_cli.main(
            [
                "--repo-root",
                str(git_repo),
                "--qualified-exporter-commit",
                head,
                "--evidence-dir",
                str(tmp_path / "evidence"),
                flag,
                "irrelevant",
            ]
        )


def test_preflight_fails_on_qualified_commit_mismatch_before_any_secret(
    git_repo: Path, tmp_path: Path
) -> None:
    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            "0" * 40,
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ]
    )
    assert result == 2


def test_preflight_fails_on_dirty_worktree(git_repo: Path, tmp_path: Path) -> None:
    (git_repo / "README.md").write_text("dirty\n", encoding="utf-8")
    head = _head(git_repo)

    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ]
    )
    assert result == 2


def test_preflight_fails_on_release_registry_digest_mismatch(
    git_repo: Path, tmp_path: Path
) -> None:
    registry = (
        git_repo
        / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
    )
    registry.write_bytes(b'{"tampered": true}')
    _run("git", "commit", "-a", "-q", "-m", "tamper", cwd=git_repo)
    head = _head(git_repo)

    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ]
    )
    assert result == 2


def test_preflight_fails_when_evidence_dir_is_inside_the_repo(git_repo: Path) -> None:
    head = _head(git_repo)

    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
            "--evidence-dir",
            str(git_repo / "evidence"),
        ]
    )
    assert result == 2


def test_second_invocation_without_explicit_attempt_id_gets_distinct_paths(
    git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _head(git_repo)
    evidence_dir = tmp_path / "evidence"
    args = [
        "--repo-root",
        str(git_repo),
        "--qualified-exporter-commit",
        head,
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


def test_test_only_attempt_id_flag_is_honored_and_labeled_test_only(
    git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    head = _head(git_repo)
    fixed_id = "a" * 32

    result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
            "--evidence-dir",
            str(tmp_path / "evidence"),
            "--test-only-attempt-id",
            fixed_id,
        ]
    )

    assert result == 0
    captured = capsys.readouterr()
    assert f"R1_ATTEMPT_ID={fixed_id}" in captured.out


def test_test_only_attempt_id_help_text_warns_against_real_use(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        r1_attempt_preflight_cli.main(["--help"])
    assert "TEST-ONLY" in capsys.readouterr().out


def test_actual_cli_refuses_a_qualified_commit_mismatch_across_a_real_subprocess_boundary(
    git_repo: Path, tmp_path: Path
) -> None:
    """Section 19: at least one test must exercise the actual CLI through a
    real subprocess/CLI boundary, not only direct Python function calls.
    A wrong ``--qualified-exporter-commit`` is used deliberately -- it fails
    before the runtime-provenance check, so this genuinely spawned
    subprocess (which, unlike an in-process call, cannot have that check
    monkeypatched) still exercises a real, meaningful refusal path."""
    rag_engine_root = Path(__file__).resolve().parents[1]
    wrapper_script = rag_engine_root / "scripts" / "r1_attempt_preflight_cli.py"
    result = subprocess.run(
        [
            sys.executable,
            str(wrapper_script),
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            "0" * 40,
            "--evidence-dir",
            str(tmp_path / "evidence"),
        ],
        cwd=rag_engine_root,
        env=os.environ.copy(),
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "R1_OPERATOR_FLOW_ERROR=" in result.stderr
    assert "not the qualified exporter commit" in result.stderr
