"""Non-secret preflight, runtime-provenance attestation, and immutable
attempt-state binding for a governed R1 export event.

R1D closed a real subshell variable-continuity bug by splitting the flow
into two Python programs. A further audit of that split found the
hand-off between them was still unsafe: Phase A printed raw
``KEY=value`` lines meant to be ``eval``'d by the operator's shell,
which is unsafe for any value containing shell metacharacters (a path
with a space, a semicolon, a `$()`), and neither program re-proved, at
the moment it actually mattered, that the code running IS the exact
qualified commit it claims to be, that the checkout is still clean, that
the sealed release file has not changed since Phase A looked at it, or
that the running interpreter's own editable packages come from this exact
checkout rather than some other one on disk.

This module closes those gaps:

- :class:`R1AttemptState` is a versioned, JSON-serializable record of
  everything both phases must agree on. It contains no secret. Phase A
  builds and publishes it (atomically, no-clobber, ``0600``, outside every
  worktree); Phase B loads it back and independently re-validates every
  field's format AND re-checks the live facts it represents (actual HEAD,
  clean worktree, release digest, runtime origin) rather than trusting the
  file's content as already-proven. Nothing here is ever passed as
  ``eval``-able shell text between the two phases.
- Every identifier that becomes part of a filename (``release_id``,
  the qualified commit, the attempt id) is validated against a narrow
  pattern before use -- no path separators, no ``..``, no control
  characters, no shell metacharacter semantics.
- Runtime-provenance attestation (:func:`assert_runtime_origin_bound_to_repo`,
  :func:`assert_nexus_contracts_metadata_version_matches`) proves the
  interpreter actually running this code imports its local editable
  packages from the qualified checkout, not a sibling one on the same
  machine, and that installed package metadata is not stale relative to
  the qualified checkout's own ``pyproject.toml``.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tomllib
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from importlib import metadata
from pathlib import Path
from typing import Any

#: The sealed release-registry's own SHA256, established once when
#: production-profile-gate-2026-2027-v1 was sealed and recorded identically
#: across RAG issue #155 and every R1A/R1B/R1C/R1D PR description. This is
#: an INDEPENDENT expected authority, hardcoded here -- never derived from
#: the very file being checked, which would make the comparison
#: tautological (compute X from the file, then "verify" the file hashes to
#: X).
EXPECTED_SEALED_RELEASE_REGISTRY_SHA256 = (
    "c9a844d4d2cc15caf9694b24ac53e77d65d50608d8a0daaef4963183d7d374fa"
)

#: Repository-relative paths that are canonical for this R1 event. Never
#: accepted as operator-supplied CLI strings for the governed path (an
#: alternate value could only ever redirect the export toward an
#: unqualified target, never legitimately toward a different one).
_RELEASE_REGISTRY_RELATIVE_PATH = (
    "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
)
_PROFILE_ROOT_RELATIVE_PATH = "services/rag-engine/configs/ingestion_profiles/v2_livraison_319"
_PROFILE_MANIFEST_RELATIVE_PATH = (
    "services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml"
)
_INGESTOR_PACKAGE_RELATIVE_PATH = "services/rag-engine/src/ingestor"
_NEXUS_CONTRACTS_PACKAGE_RELATIVE_PATH = "packages/contracts/src/nexus_contracts"
_NEXUS_CONTRACTS_PYPROJECT_RELATIVE_PATH = "packages/contracts/pyproject.toml"

_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
_ATTEMPT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
#: A safe filesystem/identifier scalar: no ``/``, no ``..``, no control
#: characters, no shell metacharacters. Applied to every value ever
#: interpolated into an output filename.
_SAFE_SCALAR_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,127})$")

ATTEMPT_STATE_PROTOCOL_VERSION = "1"


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


# ---------------------------------------------------------------------------
# Safe-scalar validation -- every identifier that becomes part of a path.
# ---------------------------------------------------------------------------


def assert_safe_scalar(value: str, *, label: str) -> str:
    if _SAFE_SCALAR_PATTERN.fullmatch(value) is None:
        raise R1OperatorFlowError(
            f"{label} {value!r} is not a safe identifier "
            f"(must match {_SAFE_SCALAR_PATTERN.pattern!r})"
        )
    return value


def assert_commit_format(value: str, *, label: str = "commit") -> str:
    if _COMMIT_PATTERN.fullmatch(value) is None:
        raise R1OperatorFlowError(
            f"{label} {value!r} is not 40 lowercase hexadecimal characters"
        )
    return value


def assert_attempt_id_format(value: str) -> str:
    if _ATTEMPT_ID_PATTERN.fullmatch(value) is None:
        raise R1OperatorFlowError(
            f"attempt id {value!r} is not a canonical 32-character hex token"
        )
    return value


# ---------------------------------------------------------------------------
# Git-state preconditions.
# ---------------------------------------------------------------------------


def assert_qualified_commit(repo_root: Path, expected_commit: str) -> str:
    """Refuses unless ``repo_root`` is checked out exactly at
    ``expected_commit`` -- never "at or after" it. Returns the actual HEAD
    on success, so a caller never has to trust a separately supplied
    producer-commit string again once this has run."""
    assert_commit_format(expected_commit, label="qualified exporter commit")
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
            "qualified commit's own tree, with no local edits, tracked or untracked"
        )


def list_repo_worktrees(repo_root: Path) -> list[Path]:
    """Every worktree ``git`` itself knows about for this repository
    (the primary checkout and every ``git worktree add`` linked one),
    resolved. Used so evidence-directory exclusion covers all of them, not
    only the one ``repo_root`` this invocation happens to run from."""
    porcelain = _git(repo_root, "worktree", "list", "--porcelain")
    paths: list[Path] = []
    for line in porcelain.splitlines():
        if line.startswith("worktree "):
            paths.append(Path(line[len("worktree ") :]).resolve())
    if not paths:
        raise R1OperatorFlowError("git worktree list returned no worktrees at all")
    return paths


def assert_evidence_dir_outside_all_worktrees(evidence_dir: Path, worktrees: list[Path]) -> None:
    """Resolves the evidence directory (following symlinks) before
    comparing, so a symlink that only *appears* to sit outside every
    worktree but actually resolves back into one is caught too."""
    resolved_evidence = evidence_dir.resolve()
    for worktree in worktrees:
        if resolved_evidence == worktree:
            raise R1OperatorFlowError(
                f"refusing to proceed: evidence directory {resolved_evidence} IS "
                f"a repository worktree ({worktree})"
            )
        try:
            resolved_evidence.relative_to(worktree)
        except ValueError:
            continue
        raise R1OperatorFlowError(
            f"refusing to proceed: evidence directory {resolved_evidence} resolves "
            f"inside repository worktree {worktree}"
        )


# ---------------------------------------------------------------------------
# Sealed release identity -- derived from the authority, never operator text.
# ---------------------------------------------------------------------------


def sealed_release_registry_path(repo_root: Path) -> Path:
    return repo_root / _RELEASE_REGISTRY_RELATIVE_PATH


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


def derive_sealed_release_id(release_registry_path: Path) -> str:
    """Reads the release id FROM the sealed registry itself -- an operator
    never supplies this as free text for the governed path, closing off
    using an arbitrary CLI string as filesystem-path material."""
    try:
        document = json.loads(release_registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R1OperatorFlowError(f"cannot parse release registry: {exc}") from exc
    releases = document.get("releases")
    if not isinstance(releases, list) or len(releases) != 1:
        raise R1OperatorFlowError(
            "release registry must declare exactly one release for this event"
        )
    release_id = releases[0].get("release_id")
    if not isinstance(release_id, str):
        raise R1OperatorFlowError("release registry entry has no string release_id")
    return assert_safe_scalar(release_id, label="sealed release id")


# ---------------------------------------------------------------------------
# Canonical, non-operator-supplied paths for the profile authority.
# ---------------------------------------------------------------------------


def canonical_profile_paths(repo_root: Path) -> tuple[Path, Path]:
    """Derived from the validated repository root, never from an operator-
    supplied ``--profile-root``/``--profile-manifest-path`` for the
    governed event -- a user-supplied alternate profile tree must not
    become authoritative merely because its own hashes form some
    internally coherent (but different) universe."""
    return (
        repo_root / _PROFILE_ROOT_RELATIVE_PATH,
        repo_root / _PROFILE_MANIFEST_RELATIVE_PATH,
    )


# ---------------------------------------------------------------------------
# Runtime-provenance attestation.
# ---------------------------------------------------------------------------


def _module_origin(module_name: str) -> Path:
    module = sys.modules.get(module_name)
    if module is None:
        try:
            module = __import__(module_name)
        except ImportError as exc:
            raise R1OperatorFlowError(f"cannot import {module_name}: {exc}") from exc
    origin = getattr(module, "__file__", None)
    if not origin:
        raise R1OperatorFlowError(f"{module_name} has no resolvable __file__")
    return Path(origin).resolve()


def assert_runtime_origin_bound_to_repo(repo_root: Path) -> None:
    """Git HEAD alone does not prove the *imported Python code* comes from
    that checkout -- an editable install's ``.pth`` file can point
    anywhere on disk. Proves the actually-imported ``ingestor`` and
    ``nexus_contracts`` modules resolve underneath this exact repository
    root, not a sibling checkout sharing the same venv."""
    resolved_root = repo_root.resolve()
    expected_ingestor_root = (resolved_root / _INGESTOR_PACKAGE_RELATIVE_PATH).resolve()
    expected_contracts_root = (
        resolved_root / _NEXUS_CONTRACTS_PACKAGE_RELATIVE_PATH
    ).resolve()

    ingestor_origin = _module_origin("ingestor")
    try:
        ingestor_origin.relative_to(expected_ingestor_root)
    except ValueError as exc:
        raise R1OperatorFlowError(
            f"refusing to proceed: ingestor module resolves to {ingestor_origin}, "
            f"not beneath the qualified checkout's {expected_ingestor_root}"
        ) from exc

    contracts_origin = _module_origin("nexus_contracts")
    try:
        contracts_origin.relative_to(expected_contracts_root)
    except ValueError as exc:
        raise R1OperatorFlowError(
            f"refusing to proceed: nexus_contracts module resolves to "
            f"{contracts_origin}, not beneath the qualified checkout's "
            f"{expected_contracts_root}"
        ) from exc

    if "nexus_release_chain" in sys.modules:
        expected_release_chain_root = (
            resolved_root / "packages/release-chain/src/nexus_release_chain"
        ).resolve()
        release_chain_origin = _module_origin("nexus_release_chain")
        try:
            release_chain_origin.relative_to(expected_release_chain_root)
        except ValueError as exc:
            raise R1OperatorFlowError(
                f"refusing to proceed: nexus_release_chain module resolves to "
                f"{release_chain_origin}, not beneath the qualified checkout's "
                f"{expected_release_chain_root}"
            ) from exc


def assert_nexus_contracts_metadata_version_matches(repo_root: Path) -> None:
    """Installed dist-info/egg-info metadata can go stale relative to an
    editable checkout's own ``pyproject.toml`` (an old ``.dist-info``
    directory left behind by a previous install, for instance) --
    confirmed reproducible, not a hypothetical: this exact staleness was
    found and fixed in this repository's own development environment while
    building this check. Never write a governed artifact's provenance
    metadata from a value that might already be lying about itself."""
    pyproject_path = repo_root / _NEXUS_CONTRACTS_PYPROJECT_RELATIVE_PATH
    try:
        document = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise R1OperatorFlowError(f"cannot read {pyproject_path}: {exc}") from exc
    declared = document.get("project", {}).get("version")
    if not isinstance(declared, str):
        raise R1OperatorFlowError(f"{pyproject_path} has no [project].version")
    try:
        installed = metadata.version("nexus-contracts")
    except metadata.PackageNotFoundError as exc:
        raise R1OperatorFlowError("nexus-contracts is not installed in this interpreter") from exc
    if installed != declared:
        raise R1OperatorFlowError(
            f"refusing to proceed: installed nexus-contracts metadata reports "
            f"{installed!r}, but the qualified checkout's pyproject.toml declares "
            f"{declared!r} -- reinstall (pip install -e) before proceeding"
        )


def assert_runtime_bound_to_qualified_checkout(repo_root: Path) -> None:
    assert_runtime_origin_bound_to_repo(repo_root)
    assert_nexus_contracts_metadata_version_matches(repo_root)


# ---------------------------------------------------------------------------
# Attempt identity and immutable attempt-state artifact.
# ---------------------------------------------------------------------------


def generate_attempt_id() -> str:
    """Collision-resistant, never a timestamp alone."""
    return uuid.uuid4().hex


@dataclass(frozen=True)
class R1AttemptState:
    """Everything both phases must agree on for one governed R1 export
    attempt. No secret is ever a field here. Serialized to/from JSON via
    :func:`write_attempt_state`/:func:`load_attempt_state` -- never
    executed as shell source."""

    protocol_version: str
    attempt_id: str
    qualified_exporter_commit: str
    repo_root: str
    sealed_release_id: str
    sealed_release_registry_path: str
    sealed_release_registry_sha256: str
    evidence_dir: str
    bootstrap_out: str
    report_out: str
    created_at: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def build_attempt_state(
    *,
    repo_root: Path,
    qualified_exporter_commit: str,
    evidence_dir: Path,
    attempt_id: str | None = None,
    now: datetime | None = None,
) -> R1AttemptState:
    """Runs every preflight check as a side effect of building the state --
    a state object is never constructed for an attempt that failed
    preflight."""
    resolved_repo = repo_root.resolve()
    assert_qualified_commit(resolved_repo, qualified_exporter_commit)
    assert_clean_worktree(resolved_repo)
    assert_runtime_bound_to_qualified_checkout(resolved_repo)

    registry_path = sealed_release_registry_path(resolved_repo)
    registry_sha256 = assert_sealed_release_registry_digest(registry_path)
    release_id = derive_sealed_release_id(registry_path)

    worktrees = list_repo_worktrees(resolved_repo)
    assert_evidence_dir_outside_all_worktrees(evidence_dir, worktrees)

    resolved_attempt_id = (
        assert_attempt_id_format(attempt_id) if attempt_id else generate_attempt_id()
    )
    short_sha = assert_commit_format(qualified_exporter_commit)[:12]
    assert_safe_scalar(release_id, label="sealed release id")
    assert_safe_scalar(short_sha, label="short commit")
    assert_safe_scalar(resolved_attempt_id, label="attempt id")

    resolved_evidence_dir = evidence_dir.resolve()
    stem = f"{release_id}-{short_sha}-{resolved_attempt_id}"
    bootstrap_out = resolved_evidence_dir / f"resource-registry-bootstrap-{stem}.json"
    report_out = resolved_evidence_dir / f"r1-evidence-{stem}.json"
    if bootstrap_out.parent != resolved_evidence_dir or report_out.parent != resolved_evidence_dir:
        raise R1OperatorFlowError("resolved output paths escaped the evidence directory")

    created_at = (now or datetime.now(UTC)).isoformat()

    return R1AttemptState(
        protocol_version=ATTEMPT_STATE_PROTOCOL_VERSION,
        attempt_id=resolved_attempt_id,
        qualified_exporter_commit=qualified_exporter_commit,
        repo_root=str(resolved_repo),
        sealed_release_id=release_id,
        sealed_release_registry_path=str(registry_path),
        sealed_release_registry_sha256=registry_sha256,
        evidence_dir=str(resolved_evidence_dir),
        bootstrap_out=str(bootstrap_out),
        report_out=str(report_out),
        created_at=created_at,
    )


def _validate_attempt_state_fields(state: R1AttemptState) -> None:
    """Re-validates format on every field, whether the state was just
    built or loaded back from disk -- a loaded file is never trusted
    merely for having the right shape; each identifier is re-checked
    against the exact same patterns used when it was first produced."""
    if state.protocol_version != ATTEMPT_STATE_PROTOCOL_VERSION:
        raise R1OperatorFlowError(
            f"unsupported attempt-state protocol_version {state.protocol_version!r}"
        )
    assert_attempt_id_format(state.attempt_id)
    assert_commit_format(state.qualified_exporter_commit, label="qualified_exporter_commit")
    assert_safe_scalar(state.sealed_release_id, label="sealed_release_id")
    if len(state.sealed_release_registry_sha256) != 64 or not all(
        c in "0123456789abcdef" for c in state.sealed_release_registry_sha256
    ):
        raise R1OperatorFlowError("sealed_release_registry_sha256 is not a valid sha256")

    evidence_dir = Path(state.evidence_dir)
    bootstrap_out = Path(state.bootstrap_out)
    report_out = Path(state.report_out)
    if bootstrap_out.parent != evidence_dir or report_out.parent != evidence_dir:
        raise R1OperatorFlowError(
            "attempt state is internally inconsistent: bootstrap/report paths are "
            "not direct children of its own evidence_dir"
        )
    if bootstrap_out == report_out:
        raise R1OperatorFlowError("attempt state's bootstrap_out and report_out are identical")


def write_attempt_state(path: Path, state: R1AttemptState) -> None:
    from ingestor.atomic_artifact import publish_atomic_no_clobber

    _validate_attempt_state_fields(state)
    serialized = json.dumps(state.to_json(), indent=2, sort_keys=True, ensure_ascii=False)
    publish_atomic_no_clobber(path, (serialized + "\n").encode("utf-8"))


def load_attempt_state(path: Path) -> R1AttemptState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise R1OperatorFlowError(f"cannot read attempt state {path}: {exc}") from exc
    try:
        state = R1AttemptState(**raw)
    except TypeError as exc:
        raise R1OperatorFlowError(f"attempt state {path} has an unexpected shape: {exc}") from exc
    _validate_attempt_state_fields(state)
    return state


def revalidate_attempt_state_against_live_repo(state: R1AttemptState) -> str:
    """Phase B's TOCTOU closure: re-runs every check that could have gone
    stale since Phase A produced ``state`` -- HEAD may have moved, the tree
    may be dirty, the sealed release file may have been swapped, the
    runtime may not actually be bound to this checkout. Returns the actual,
    freshly re-verified HEAD, which callers must use as the producer commit
    -- never the state's own (now merely claimed) value on its own."""
    repo_root = Path(state.repo_root)
    actual_head = assert_qualified_commit(repo_root, state.qualified_exporter_commit)
    assert_clean_worktree(repo_root)
    assert_runtime_bound_to_qualified_checkout(repo_root)

    registry_path = Path(state.sealed_release_registry_path)
    actual_digest = assert_sealed_release_registry_digest(registry_path)
    if actual_digest != state.sealed_release_registry_sha256:
        raise R1OperatorFlowError(
            "refusing to proceed: sealed release-registry digest changed since "
            "Phase A produced this attempt state"
        )
    actual_release_id = derive_sealed_release_id(registry_path)
    if actual_release_id != state.sealed_release_id:
        raise R1OperatorFlowError(
            "refusing to proceed: sealed release id changed since Phase A produced "
            "this attempt state"
        )

    bootstrap_out = Path(state.bootstrap_out)
    report_out = Path(state.report_out)
    if bootstrap_out.exists() or bootstrap_out.is_symlink():
        raise R1OperatorFlowError(f"bootstrap output already exists: {bootstrap_out}")
    if report_out.exists() or report_out.is_symlink():
        raise R1OperatorFlowError(f"report output already exists: {report_out}")

    return actual_head


__all__ = [
    "ATTEMPT_STATE_PROTOCOL_VERSION",
    "EXPECTED_SEALED_RELEASE_REGISTRY_SHA256",
    "R1AttemptState",
    "R1OperatorFlowError",
    "assert_attempt_id_format",
    "assert_clean_worktree",
    "assert_commit_format",
    "assert_evidence_dir_outside_all_worktrees",
    "assert_nexus_contracts_metadata_version_matches",
    "assert_qualified_commit",
    "assert_runtime_bound_to_qualified_checkout",
    "assert_runtime_origin_bound_to_repo",
    "assert_safe_scalar",
    "assert_sealed_release_registry_digest",
    "build_attempt_state",
    "canonical_profile_paths",
    "derive_sealed_release_id",
    "generate_attempt_id",
    "list_repo_worktrees",
    "load_attempt_state",
    "revalidate_attempt_state_against_live_repo",
    "sealed_release_registry_path",
    "write_attempt_state",
]
