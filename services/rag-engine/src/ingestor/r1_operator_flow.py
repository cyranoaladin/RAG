"""Non-secret preflight and attempt-identity resolution for a governed R1
export event.

Extracted into pure, unit-testable functions specifically because the
runbook this replaces demonstrated the failure mode this module exists to
prevent: hand-copy-pasted shell commands assigning event state (an attempt
identity, resolved output paths) *inside* a subshell opened only for
credential entry, then relying on that state in a later shell block where
it was never visible -- shell subshells never propagate variable
assignments back to their parent. No amount of runbook prose review caught
that; only executing the described flow would have. These functions are
that flow, now something `pytest` actually runs.

Every function here is safe to call with no PostgreSQL connection and no
credential in scope -- this module is the "before the secret is ever
touched" half of a governed R1 attempt. See ``r1_export_and_verify_cli.py``
for the half that actually opens a database connection, deliberately kept
in a separate module so it is obvious by import graph alone which half can
possibly see a DSN.
"""

from __future__ import annotations

import hashlib
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path

#: The sealed release-registry's own SHA256, established once when
#: production-profile-gate-2026-2027-v1 was sealed and recorded identically
#: across RAG issue #155 and every R1A/R1B/R1C PR description. This is an
#: INDEPENDENT expected authority, hardcoded here -- never derived from the
#: very file being checked, which would make the comparison tautological
#: (compute X from the file, then "verify" the file hashes to X).
EXPECTED_SEALED_RELEASE_REGISTRY_SHA256 = (
    "c9a844d4d2cc15caf9694b24ac53e77d65d50608d8a0daaef4963183d7d374fa"
)


class R1OperatorFlowError(RuntimeError):
    """A precondition for a governed R1 export attempt is not met."""


def _git(repo_root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), *args],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise R1OperatorFlowError(f"git {' '.join(args)} failed to run: {exc}") from exc
    except subprocess.CalledProcessError as exc:
        raise R1OperatorFlowError(
            f"git {' '.join(args)} failed: {exc.stderr.strip() or exc.stdout.strip()}"
        ) from exc
    return completed.stdout


def assert_qualified_commit(repo_root: Path, expected_commit: str) -> str:
    """Refuses unless ``repo_root`` is checked out exactly at
    ``expected_commit`` -- never "at or after" it. A governed export runs
    from a specific, previously test-qualified commit; a newer, unqualified
    descendant is a different, unqualified commit, however trivial the
    difference looks."""
    actual = _git(repo_root, "rev-parse", "HEAD").strip()
    if actual != expected_commit:
        raise R1OperatorFlowError(
            f"refusing to proceed: HEAD is {actual}, not the qualified exporter "
            f"commit {expected_commit} recorded for this R1 event"
        )
    return actual


def assert_clean_worktree(repo_root: Path) -> None:
    status = _git(repo_root, "status", "--porcelain")
    if status.strip():
        raise R1OperatorFlowError(
            "refusing to proceed: worktree is not clean (git status --porcelain "
            "is non-empty) -- a governed export must run from exactly the "
            "qualified commit's own tree, with no local edits"
        )


def assert_sealed_release_registry_digest(release_registry_path: Path) -> str:
    """Compares the ACTUAL file's digest against the hardcoded, independent
    sealed authority above -- never against a digest derived from this same
    file, which would always trivially pass."""
    try:
        raw = release_registry_path.read_bytes()
    except OSError as exc:
        raise R1OperatorFlowError(f"cannot read release registry: {exc}") from exc
    actual = hashlib.sha256(raw).hexdigest()
    if actual != EXPECTED_SEALED_RELEASE_REGISTRY_SHA256:
        raise R1OperatorFlowError(
            f"refusing to proceed: release-registry.json sha256 {actual} does not "
            f"match the sealed authority {EXPECTED_SEALED_RELEASE_REGISTRY_SHA256} "
            "-- do not reseal or update this expected value; the sealed release is "
            "immutable, so a mismatch means the wrong file, not a stale constant"
        )
    return actual


def assert_evidence_dir_outside_repo(evidence_dir: Path, repo_root: Path) -> None:
    """Resolves both paths (following symlinks) before comparing, so a
    symlink that only *appears* to sit outside the repository but actually
    resolves back into it is caught too."""
    resolved_evidence = evidence_dir.resolve()
    resolved_repo = repo_root.resolve()
    if resolved_evidence == resolved_repo:
        raise R1OperatorFlowError(
            f"refusing to proceed: evidence directory {resolved_evidence} IS the "
            "repository root"
        )
    try:
        resolved_evidence.relative_to(resolved_repo)
    except ValueError:
        return
    raise R1OperatorFlowError(
        f"refusing to proceed: evidence directory {resolved_evidence} resolves "
        f"inside the repository {resolved_repo}"
    )


def generate_attempt_id() -> str:
    """Collision-resistant, never a timestamp alone (two attempts started
    in the same second, or an operator clock skew, must never collide)."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class R1AttemptPaths:
    attempt_id: str
    short_sha: str
    bootstrap_out: Path
    report_out: Path


def resolve_attempt_paths(
    *,
    evidence_dir: Path,
    release_id: str,
    qualified_commit: str,
    attempt_id: str | None = None,
) -> R1AttemptPaths:
    """Deterministic given the same inputs (including ``attempt_id``, when
    provided) -- this is what lets a Phase B invocation reuse the exact
    paths a Phase A invocation already resolved and validated, by passing
    the same attempt id back, rather than rediscovering "the latest file"
    or otherwise guessing."""
    attempt = attempt_id or generate_attempt_id()
    short_sha = qualified_commit[:12]
    stem = f"{release_id}-{short_sha}-{attempt}"
    return R1AttemptPaths(
        attempt_id=attempt,
        short_sha=short_sha,
        bootstrap_out=evidence_dir / f"resource-registry-bootstrap-{stem}.json",
        report_out=evidence_dir / f"r1-evidence-{stem}.json",
    )


def run_preflight(
    *,
    repo_root: Path,
    qualified_commit: str,
    release_registry_path: Path,
    evidence_dir: Path,
) -> None:
    """Every non-secret check, in the required order, before any
    credential is ever requested. Raises :class:`R1OperatorFlowError` on
    the first failure -- never accumulates and reports multiple, since a
    single failure is already sufficient reason to stop before touching a
    production DSN."""
    assert_qualified_commit(repo_root, qualified_commit)
    assert_clean_worktree(repo_root)
    assert_sealed_release_registry_digest(release_registry_path)
    assert_evidence_dir_outside_repo(evidence_dir, repo_root)


__all__ = [
    "EXPECTED_SEALED_RELEASE_REGISTRY_SHA256",
    "R1AttemptPaths",
    "R1OperatorFlowError",
    "assert_clean_worktree",
    "assert_evidence_dir_outside_repo",
    "assert_qualified_commit",
    "assert_sealed_release_registry_digest",
    "generate_attempt_id",
    "resolve_attempt_paths",
    "run_preflight",
]
