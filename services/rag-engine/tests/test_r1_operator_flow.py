from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from ingestor.r1_operator_flow import (
    EXPECTED_SEALED_RELEASE_REGISTRY_SHA256,
    R1OperatorFlowError,
    assert_clean_worktree,
    assert_evidence_dir_outside_repo,
    assert_qualified_commit,
    assert_sealed_release_registry_digest,
    generate_attempt_id,
    resolve_attempt_paths,
    run_preflight,
)


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


# ---------------------------------------------------------------------------
# assert_qualified_commit
# ---------------------------------------------------------------------------


def test_assert_qualified_commit_passes_on_exact_match(git_repo: Path) -> None:
    head = _head(git_repo)
    assert assert_qualified_commit(git_repo, head) == head


def test_assert_qualified_commit_fails_on_mismatch(git_repo: Path) -> None:
    with pytest.raises(R1OperatorFlowError, match="not the qualified exporter commit"):
        assert_qualified_commit(git_repo, "0" * 40)


# ---------------------------------------------------------------------------
# assert_clean_worktree
# ---------------------------------------------------------------------------


def test_assert_clean_worktree_passes_when_clean(git_repo: Path) -> None:
    assert_clean_worktree(git_repo)  # must not raise


def test_assert_clean_worktree_fails_when_dirty(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("edited\n", encoding="utf-8")
    with pytest.raises(R1OperatorFlowError, match="not clean"):
        assert_clean_worktree(git_repo)


def test_assert_clean_worktree_fails_with_untracked_file(git_repo: Path) -> None:
    (git_repo / "untracked.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(R1OperatorFlowError, match="not clean"):
        assert_clean_worktree(git_repo)


# ---------------------------------------------------------------------------
# assert_sealed_release_registry_digest
# ---------------------------------------------------------------------------


def test_assert_sealed_release_registry_digest_passes_for_matching_content(
    tmp_path: Path,
) -> None:
    # A file whose real sha256 is the pinned sealed value is required to
    # exercise the PASS path without depending on the real, large release
    # registry: construct bytes and confirm the constant is what it claims
    # to be, then verify against a fixture we know matches.
    import hashlib

    target = tmp_path / "release-registry.json"
    # Brute-search is infeasible; instead assert the function compares
    # against the real repo's real release registry, which is the actual
    # sealed artifact this constant was pinned against.
    real_registry = (
        Path(__file__).resolve().parents[2]
        / "rag-pedago"
        / "data"
        / "releases"
        / "prerentree_2026_2027"
        / "release-registry.json"
    )
    target.write_bytes(real_registry.read_bytes())
    actual = hashlib.sha256(target.read_bytes()).hexdigest()
    assert actual == EXPECTED_SEALED_RELEASE_REGISTRY_SHA256
    assert assert_sealed_release_registry_digest(target) == EXPECTED_SEALED_RELEASE_REGISTRY_SHA256


def test_assert_sealed_release_registry_digest_fails_for_wrong_content(tmp_path: Path) -> None:
    target = tmp_path / "release-registry.json"
    target.write_bytes(b'{"tampered": true}')
    with pytest.raises(R1OperatorFlowError, match="does not match the sealed authority"):
        assert_sealed_release_registry_digest(target)


# ---------------------------------------------------------------------------
# assert_evidence_dir_outside_repo
# ---------------------------------------------------------------------------


def test_assert_evidence_dir_outside_repo_passes(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    assert_evidence_dir_outside_repo(evidence, repo)  # must not raise


def test_assert_evidence_dir_outside_repo_fails_when_equal(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    with pytest.raises(R1OperatorFlowError, match="IS the repository root"):
        assert_evidence_dir_outside_repo(repo, repo)


def test_assert_evidence_dir_outside_repo_fails_when_nested(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    nested = repo / "evidence"
    nested.mkdir()
    with pytest.raises(R1OperatorFlowError, match="resolves inside the repository"):
        assert_evidence_dir_outside_repo(nested, repo)


def test_assert_evidence_dir_outside_repo_fails_for_symlink_into_repo(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "evidence").mkdir()
    outside = tmp_path / "looks-external"
    outside.symlink_to(repo / "evidence")
    with pytest.raises(R1OperatorFlowError, match="resolves inside the repository"):
        assert_evidence_dir_outside_repo(outside, repo)


# ---------------------------------------------------------------------------
# attempt identity + path resolution
# ---------------------------------------------------------------------------


def test_generate_attempt_id_is_collision_resistant() -> None:
    first = generate_attempt_id()
    second = generate_attempt_id()
    assert first != second
    assert len(first) == 32  # uuid4 hex


def test_resolve_attempt_paths_deterministic_with_explicit_attempt_id(tmp_path: Path) -> None:
    first = resolve_attempt_paths(
        evidence_dir=tmp_path,
        release_id="production-profile-gate-2026-2027-v1",
        qualified_commit="6b9ef7a75fa8dd0a34efa1d61bc7d5e8f604f73b",
        attempt_id="fixedattemptid0000000000000000",
    )
    second = resolve_attempt_paths(
        evidence_dir=tmp_path,
        release_id="production-profile-gate-2026-2027-v1",
        qualified_commit="6b9ef7a75fa8dd0a34efa1d61bc7d5e8f604f73b",
        attempt_id="fixedattemptid0000000000000000",
    )
    assert first == second
    assert first.bootstrap_out != first.report_out


def test_resolve_attempt_paths_generates_distinct_paths_when_attempt_id_omitted(
    tmp_path: Path,
) -> None:
    first = resolve_attempt_paths(
        evidence_dir=tmp_path,
        release_id="production-profile-gate-2026-2027-v1",
        qualified_commit="6b9ef7a75fa8dd0a34efa1d61bc7d5e8f604f73b",
    )
    second = resolve_attempt_paths(
        evidence_dir=tmp_path,
        release_id="production-profile-gate-2026-2027-v1",
        qualified_commit="6b9ef7a75fa8dd0a34efa1d61bc7d5e8f604f73b",
    )
    assert first.attempt_id != second.attempt_id
    assert first.bootstrap_out != second.bootstrap_out
    assert first.report_out != second.report_out


# ---------------------------------------------------------------------------
# run_preflight ordering
# ---------------------------------------------------------------------------


def test_run_preflight_checks_qualified_commit_before_worktree_cleanliness(
    git_repo: Path, tmp_path: Path
) -> None:
    """Both would fail here (wrong commit AND, incidentally, a dirty tree
    would also fail if reached) -- the commit check must fire first, so the
    operator is never told to clean a tree they should not even be using."""
    (git_repo / "README.md").write_text("dirty\n", encoding="utf-8")
    release_registry = tmp_path / "release-registry.json"
    release_registry.write_bytes(b"irrelevant, never reached")

    with pytest.raises(R1OperatorFlowError, match="not the qualified exporter commit"):
        run_preflight(
            repo_root=git_repo,
            qualified_commit="0" * 40,
            release_registry_path=release_registry,
            evidence_dir=tmp_path / "evidence",
        )
