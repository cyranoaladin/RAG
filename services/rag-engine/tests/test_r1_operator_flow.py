from __future__ import annotations

import json
import subprocess
import sys
import types
from datetime import UTC, datetime
from pathlib import Path

import pytest

import ingestor.r1_operator_flow as flow
from ingestor.r1_operator_flow import (
    EXPECTED_SEALED_RELEASE_REGISTRY_SHA256,
    R1OperatorFlowError,
    assert_attempt_id_format,
    assert_clean_worktree,
    assert_commit_format,
    assert_evidence_dir_outside_all_worktrees,
    assert_nexus_contracts_metadata_version_matches,
    assert_qualified_commit,
    assert_runtime_origin_bound_to_repo,
    assert_safe_scalar,
    assert_sealed_release_registry_digest,
    build_attempt_state,
    canonical_attempt_output_paths,
    canonical_attempt_state_path,
    canonical_profile_paths,
    derive_sealed_release_id,
    generate_attempt_id,
    list_repo_worktrees,
    load_attempt_state,
    revalidate_attempt_state_against_live_repo,
    sealed_release_registry_path,
    write_attempt_state,
)

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


def _sealed_registry(tmp_path: Path) -> Path:
    target = tmp_path / "release-registry.json"
    target.write_bytes(REAL_REGISTRY.read_bytes())
    return target


def _sealed_registry_at(git_repo: Path) -> Path:
    """The ``git_repo`` fixture already commits the real sealed registry
    into the initial commit (so capturing HEAD and asserting a clean
    worktree both remain valid); this just returns its path."""
    target = (
        git_repo
        / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
    )
    assert target.is_file()
    return target


def _no_runtime_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Most tests here are not about runtime-provenance attestation itself
    (that has its own dedicated tests below, with controlled fake modules)
    -- they use throwaway temp git repos as ``repo_root``, which obviously
    is never where the real running ``ingestor``/``nexus_contracts``
    modules live. Bypassing the check here isolates those unrelated tests
    from this repository's own current (possibly dirty, mid-development)
    working state."""
    monkeypatch.setattr(flow, "assert_runtime_bound_to_qualified_checkout", lambda repo_root: None)


# ---------------------------------------------------------------------------
# Safe-scalar / format validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["ok", "ok-value", "ok_value", "ok.value", "a" * 128])
def test_assert_safe_scalar_accepts_safe_values(value: str) -> None:
    assert assert_safe_scalar(value, label="x") == value


@pytest.mark.parametrize(
    "value",
    [
        "../escape",
        "a/b",
        "a b",
        "a;b",
        "$(whoami)",
        "a'b",
        "a\nb",
        "a\x00b",
        "",
        "a" * 129,
    ],
)
def test_assert_safe_scalar_refuses_unsafe_values(value: str) -> None:
    with pytest.raises(R1OperatorFlowError):
        assert_safe_scalar(value, label="x")


def test_assert_commit_format_accepts_exactly_40_hex_chars() -> None:
    assert assert_commit_format("a" * 40) == "a" * 40


@pytest.mark.parametrize("value", ["A" * 40, "a" * 39, "a" * 41, "g" * 40, ""])
def test_assert_commit_format_refuses_everything_else(value: str) -> None:
    with pytest.raises(R1OperatorFlowError):
        assert_commit_format(value)


def test_assert_attempt_id_format_accepts_uuid4_hex() -> None:
    value = generate_attempt_id()
    assert assert_attempt_id_format(value) == value


@pytest.mark.parametrize("value", ["not-hex-and-wrong-length", "a" * 31, "a" * 33, "G" * 32])
def test_assert_attempt_id_format_refuses_everything_else(value: str) -> None:
    with pytest.raises(R1OperatorFlowError):
        assert_attempt_id_format(value)


# ---------------------------------------------------------------------------
# Git-state preconditions
# ---------------------------------------------------------------------------


def test_assert_qualified_commit_passes_on_exact_match(git_repo: Path) -> None:
    head = _head(git_repo)
    assert assert_qualified_commit(git_repo, head) == head


def test_assert_qualified_commit_fails_on_mismatch(git_repo: Path) -> None:
    with pytest.raises(R1OperatorFlowError, match="not the qualified exporter commit"):
        assert_qualified_commit(git_repo, "0" * 40)


def test_assert_clean_worktree_passes_when_clean(git_repo: Path) -> None:
    assert_clean_worktree(git_repo)


def test_assert_clean_worktree_fails_when_dirty(git_repo: Path) -> None:
    (git_repo / "README.md").write_text("edited\n", encoding="utf-8")
    with pytest.raises(R1OperatorFlowError, match="not clean"):
        assert_clean_worktree(git_repo)


def test_assert_clean_worktree_fails_with_untracked_file(git_repo: Path) -> None:
    (git_repo / "untracked.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(R1OperatorFlowError, match="not clean"):
        assert_clean_worktree(git_repo)


def test_list_repo_worktrees_includes_the_primary_checkout(git_repo: Path) -> None:
    worktrees = list_repo_worktrees(git_repo)
    assert git_repo.resolve() in worktrees


def test_list_repo_worktrees_includes_a_linked_worktree(git_repo: Path, tmp_path: Path) -> None:
    linked = tmp_path / "linked"
    _run("git", "-C", str(git_repo), "worktree", "add", str(linked), "-b", "other", cwd=git_repo)
    worktrees = list_repo_worktrees(git_repo)
    assert linked.resolve() in worktrees
    assert len(worktrees) == 2


def test_assert_evidence_dir_outside_all_worktrees_passes(tmp_path: Path) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    assert_evidence_dir_outside_all_worktrees(evidence, [worktree.resolve()])


def test_assert_evidence_dir_outside_all_worktrees_fails_inside_primary(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    evidence = primary / "evidence"
    evidence.mkdir()
    with pytest.raises(R1OperatorFlowError, match="resolves inside repository worktree"):
        assert_evidence_dir_outside_all_worktrees(evidence, [primary.resolve(), linked.resolve()])


def test_assert_evidence_dir_outside_all_worktrees_fails_inside_linked(tmp_path: Path) -> None:
    primary = tmp_path / "primary"
    primary.mkdir()
    linked = tmp_path / "linked"
    linked.mkdir()
    evidence = linked / "evidence"
    evidence.mkdir()
    with pytest.raises(R1OperatorFlowError, match="resolves inside repository worktree"):
        assert_evidence_dir_outside_all_worktrees(evidence, [primary.resolve(), linked.resolve()])


def test_assert_evidence_dir_outside_all_worktrees_fails_for_symlink_into_a_worktree(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "evidence").mkdir()
    outside = tmp_path / "looks-external"
    outside.symlink_to(worktree / "evidence")
    with pytest.raises(R1OperatorFlowError, match="resolves inside repository worktree"):
        assert_evidence_dir_outside_all_worktrees(outside, [worktree.resolve()])


# ---------------------------------------------------------------------------
# Sealed release identity
# ---------------------------------------------------------------------------


def test_assert_sealed_release_registry_digest_passes_for_real_file(tmp_path: Path) -> None:
    target = _sealed_registry(tmp_path)
    assert assert_sealed_release_registry_digest(target) == EXPECTED_SEALED_RELEASE_REGISTRY_SHA256


def test_assert_sealed_release_registry_digest_fails_for_wrong_content(tmp_path: Path) -> None:
    target = tmp_path / "release-registry.json"
    target.write_bytes(b'{"tampered": true}')
    with pytest.raises(R1OperatorFlowError, match="does not match the sealed authority"):
        assert_sealed_release_registry_digest(target)


def test_derive_sealed_release_id_reads_the_real_registry(tmp_path: Path) -> None:
    target = _sealed_registry(tmp_path)
    assert derive_sealed_release_id(target) == "production-profile-gate-2026-2027-v1"


def test_derive_sealed_release_id_refuses_path_traversal_payload(tmp_path: Path) -> None:
    target = tmp_path / "release-registry.json"
    target.write_text(
        json.dumps({"releases": [{"release_id": "../../etc/passwd"}]}), encoding="utf-8"
    )
    with pytest.raises(R1OperatorFlowError):
        derive_sealed_release_id(target)


def test_derive_sealed_release_id_refuses_multiple_releases(tmp_path: Path) -> None:
    target = tmp_path / "release-registry.json"
    target.write_text(
        json.dumps({"releases": [{"release_id": "a"}, {"release_id": "b"}]}), encoding="utf-8"
    )
    with pytest.raises(R1OperatorFlowError, match="exactly one release"):
        derive_sealed_release_id(target)


def test_sealed_release_registry_path_is_derived_not_operator_supplied(tmp_path: Path) -> None:
    resolved = sealed_release_registry_path(tmp_path)
    expected = (
        tmp_path / "services/rag-pedago/data/releases/prerentree_2026_2027/release-registry.json"
    )
    assert resolved == expected


def test_canonical_profile_paths_are_derived_from_repo_root(tmp_path: Path) -> None:
    root, manifest = canonical_profile_paths(tmp_path)
    assert root == tmp_path / "services/rag-engine/configs/ingestion_profiles/v2_livraison_319"
    assert (
        manifest
        == tmp_path
        / "services/rag-engine/configs/ingestion_profiles/ingestion_manifest_v2_livraison_319.yml"
    )


# ---------------------------------------------------------------------------
# Runtime-provenance attestation -- controlled fake modules, never this
# repository's own (possibly mid-development, dirty) real state.
# ---------------------------------------------------------------------------


def _fake_module(origin: Path) -> types.ModuleType:
    module = types.ModuleType("fake")
    module.__file__ = str(origin)
    return module


def test_assert_runtime_origin_bound_to_repo_passes_when_beneath_qualified_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ingestor_dir = tmp_path / "services/rag-engine/src/ingestor"
    ingestor_dir.mkdir(parents=True)
    contracts_dir = tmp_path / "packages/contracts/src/nexus_contracts"
    contracts_dir.mkdir(parents=True)

    monkeypatch.setitem(sys.modules, "ingestor", _fake_module(ingestor_dir / "__init__.py"))
    monkeypatch.setitem(
        sys.modules, "nexus_contracts", _fake_module(contracts_dir / "__init__.py")
    )

    assert_runtime_origin_bound_to_repo(tmp_path)


def test_assert_runtime_origin_bound_to_repo_fails_for_sibling_checkout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    qualified_root = tmp_path / "qualified"
    (qualified_root / "services/rag-engine/src/ingestor").mkdir(parents=True)
    (qualified_root / "packages/contracts/src/nexus_contracts").mkdir(parents=True)

    sibling_root = tmp_path / "sibling"
    sibling_ingestor = sibling_root / "services/rag-engine/src/ingestor"
    sibling_ingestor.mkdir(parents=True)

    monkeypatch.setitem(sys.modules, "ingestor", _fake_module(sibling_ingestor / "__init__.py"))
    monkeypatch.setitem(
        sys.modules,
        "nexus_contracts",
        _fake_module(qualified_root / "packages/contracts/src/nexus_contracts/__init__.py"),
    )

    with pytest.raises(R1OperatorFlowError, match="ingestor module resolves to"):
        assert_runtime_origin_bound_to_repo(qualified_root)


def test_assert_nexus_contracts_metadata_version_matches_passes_when_equal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pyproject = tmp_path / "packages/contracts/pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text(
        '[project]\nname = "nexus-contracts"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    monkeypatch.setattr(flow.metadata, "version", lambda name: "1.2.3")

    assert_nexus_contracts_metadata_version_matches(tmp_path)


def test_assert_nexus_contracts_metadata_version_matches_fails_when_stale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pyproject = tmp_path / "packages/contracts/pyproject.toml"
    pyproject.parent.mkdir(parents=True)
    pyproject.write_text(
        '[project]\nname = "nexus-contracts"\nversion = "1.2.3"\n', encoding="utf-8"
    )
    monkeypatch.setattr(flow.metadata, "version", lambda name: "0.0.1-stale")

    with pytest.raises(R1OperatorFlowError, match="reinstall"):
        assert_nexus_contracts_metadata_version_matches(tmp_path)


def test_runtime_attestation_reflects_this_repositorys_own_real_environment() -> None:
    """Not mocked: the interpreter actually running this test suite genuinely
    is imported from this real, qualified checkout -- proves the check
    passes end-to-end against real (not fabricated) module origins and a
    real, current metadata version, not merely against controlled fakes."""
    real_repo_root = Path(__file__).resolve().parents[3]
    flow.assert_runtime_bound_to_qualified_checkout(real_repo_root)


# ---------------------------------------------------------------------------
# Attempt state: build, write, load, and TOCTOU revalidation
# ---------------------------------------------------------------------------


def test_build_attempt_state_success(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    assert state.qualified_exporter_commit == head
    assert state.sealed_release_id == "production-profile-gate-2026-2027-v1"
    assert Path(state.bootstrap_out).parent == evidence_dir.resolve()
    assert Path(state.report_out).parent == evidence_dir.resolve()
    assert state.bootstrap_out != state.report_out
    datetime.fromisoformat(state.created_at)  # must not raise


def test_write_then_load_attempt_state_round_trips(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )
    state_path = evidence_dir / f"r1-attempt-state-{state.attempt_id}.json"
    write_attempt_state(state_path, state)

    loaded = load_attempt_state(state_path)
    assert loaded == state


def test_write_attempt_state_refuses_to_overwrite_existing(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )
    state_path = evidence_dir / "state.json"
    write_attempt_state(state_path, state)

    from ingestor.atomic_artifact import AtomicArtifactError

    with pytest.raises(AtomicArtifactError, match="already exists"):
        write_attempt_state(state_path, state)


def test_load_attempt_state_refuses_tampered_commit_format(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    payload = {
        "protocol_version": "1",
        "attempt_id": generate_attempt_id(),
        "qualified_exporter_commit": "not-a-commit",
        "repo_root": str(tmp_path),
        "sealed_release_id": "production-profile-gate-2026-2027-v1",
        "sealed_release_registry_path": str(tmp_path / "release-registry.json"),
        "sealed_release_registry_sha256": "a" * 64,
        "evidence_dir": str(tmp_path),
        "bootstrap_out": str(tmp_path / "bootstrap.json"),
        "report_out": str(tmp_path / "report.json"),
        "created_at": datetime.now(UTC).isoformat(),
    }
    state_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(R1OperatorFlowError, match="hexadecimal"):
        load_attempt_state(state_path)


def test_revalidate_attempt_state_fails_after_checkout_changes(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    (git_repo / "README.md").write_text("changed\n", encoding="utf-8")
    _run("git", "add", "README.md", cwd=git_repo)
    _run("git", "commit", "-q", "-m", "second", cwd=git_repo)

    with pytest.raises(R1OperatorFlowError, match="not the qualified exporter commit"):
        revalidate_attempt_state_against_live_repo(state)


def test_revalidate_attempt_state_fails_after_tracked_edit(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    (git_repo / "README.md").write_text("dirtied after preflight\n", encoding="utf-8")

    with pytest.raises(R1OperatorFlowError, match="not clean"):
        revalidate_attempt_state_against_live_repo(state)


def test_revalidate_attempt_state_fails_after_untracked_file(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    (git_repo / "untracked-after-preflight.txt").write_text("x\n", encoding="utf-8")

    with pytest.raises(R1OperatorFlowError, match="not clean"):
        revalidate_attempt_state_against_live_repo(state)


def test_revalidate_attempt_state_fails_when_bootstrap_output_already_exists(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )
    Path(state.bootstrap_out).write_bytes(b"already published")

    with pytest.raises(R1OperatorFlowError, match="already exists"):
        revalidate_attempt_state_against_live_repo(state)


def test_revalidate_attempt_state_succeeds_for_a_genuinely_untouched_attempt(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    assert revalidate_attempt_state_against_live_repo(state) == head


def test_two_attempts_without_explicit_attempt_id_get_distinct_state_and_paths(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"

    first = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )
    second = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    assert first.attempt_id != second.attempt_id
    assert first.bootstrap_out != second.bootstrap_out
    assert first.report_out != second.report_out


# ---------------------------------------------------------------------------
# R1F: canonical output-path and attempt-state-path derivation.
# ---------------------------------------------------------------------------


def test_canonical_attempt_output_paths_is_deterministic(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    args = dict(
        release_id="production-profile-gate-2026-2027-v1",
        qualified_exporter_commit="a" * 40,
        attempt_id=generate_attempt_id(),
    )
    first = canonical_attempt_output_paths(evidence_dir, **args)
    second = canonical_attempt_output_paths(evidence_dir, **args)
    assert first == second
    bootstrap_out, report_out = first
    assert bootstrap_out.parent == evidence_dir.resolve()
    assert report_out.parent == evidence_dir.resolve()
    assert bootstrap_out != report_out


def test_canonical_attempt_output_paths_changes_with_any_input(tmp_path: Path) -> None:
    evidence_dir = tmp_path / "evidence"
    baseline = canonical_attempt_output_paths(
        evidence_dir,
        release_id="production-profile-gate-2026-2027-v1",
        qualified_exporter_commit="a" * 40,
        attempt_id=generate_attempt_id(),
    )
    different_commit = canonical_attempt_output_paths(
        evidence_dir,
        release_id="production-profile-gate-2026-2027-v1",
        qualified_exporter_commit="b" * 40,
        attempt_id=generate_attempt_id(),
    )
    assert baseline != different_commit


def test_canonical_attempt_output_paths_rejects_unsafe_release_id(tmp_path: Path) -> None:
    with pytest.raises(R1OperatorFlowError):
        canonical_attempt_output_paths(
            tmp_path,
            release_id="../escape",
            qualified_exporter_commit="a" * 40,
            attempt_id=generate_attempt_id(),
        )


def test_canonical_attempt_state_path_is_deterministic(tmp_path: Path) -> None:
    attempt_id = generate_attempt_id()
    first = canonical_attempt_state_path(tmp_path, attempt_id)
    second = canonical_attempt_state_path(tmp_path, attempt_id)
    assert first == second
    assert first.name == f"r1-attempt-state-{attempt_id}.json"
    assert first.parent == tmp_path.resolve()


def test_canonical_attempt_state_path_rejects_malformed_attempt_id(tmp_path: Path) -> None:
    with pytest.raises(R1OperatorFlowError):
        canonical_attempt_state_path(tmp_path, "not-a-valid-attempt-id")


# ---------------------------------------------------------------------------
# R1F: load_attempt_state refuses a file loaded from a noncanonical location.
# ---------------------------------------------------------------------------


def test_load_attempt_state_refuses_a_copy_at_a_noncanonical_path(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )
    canonical_path = canonical_attempt_state_path(evidence_dir, state.attempt_id)
    write_attempt_state(canonical_path, state)

    copied_path = evidence_dir / "a-copy-of-the-state.json"
    copied_path.write_bytes(canonical_path.read_bytes())

    with pytest.raises(R1OperatorFlowError, match="not the canonical location"):
        load_attempt_state(copied_path)


def test_load_attempt_state_accepts_its_own_canonical_location(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )
    canonical_path = canonical_attempt_state_path(evidence_dir, state.attempt_id)
    write_attempt_state(canonical_path, state)

    assert load_attempt_state(canonical_path) == state


# ---------------------------------------------------------------------------
# R1F: revalidate_attempt_state_against_live_repo's new canonical-binding
# and multi-worktree re-exclusion checks.
# ---------------------------------------------------------------------------


def test_revalidate_reexcludes_evidence_dir_from_every_worktree(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """A state that is internally self-consistent (evidence_dir and the
    canonical output paths derived from it all agree) but whose
    evidence_dir has been redirected into a worktree that came into
    existence AFTER Phase A ran must still be caught: Phase B re-derives
    the worktree list live, never trusting Phase A's now-stale check."""
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    real_evidence_dir = tmp_path / "real-evidence"
    real_evidence_dir.mkdir()
    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=real_evidence_dir
    )

    new_worktree = tmp_path / "new-worktree"
    subprocess.run(
        ["git", "worktree", "add", str(new_worktree), "-b", "later-branch"],
        cwd=git_repo,
        check=True,
        capture_output=True,
        text=True,
    )
    redirected_evidence_dir = new_worktree / "evidence"
    bootstrap_out, report_out = canonical_attempt_output_paths(
        redirected_evidence_dir,
        release_id=state.sealed_release_id,
        qualified_exporter_commit=state.qualified_exporter_commit,
        attempt_id=state.attempt_id,
    )
    redirected_state = flow.R1AttemptState(
        protocol_version=state.protocol_version,
        attempt_id=state.attempt_id,
        qualified_exporter_commit=state.qualified_exporter_commit,
        repo_root=state.repo_root,
        sealed_release_id=state.sealed_release_id,
        sealed_release_registry_path=state.sealed_release_registry_path,
        sealed_release_registry_sha256=state.sealed_release_registry_sha256,
        evidence_dir=str(redirected_evidence_dir.resolve()),
        bootstrap_out=str(bootstrap_out),
        report_out=str(report_out),
        created_at=state.created_at,
    )

    with pytest.raises(R1OperatorFlowError, match="repository worktree"):
        revalidate_attempt_state_against_live_repo(redirected_state)


def test_revalidate_rejects_bootstrap_out_that_is_not_the_canonical_path(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    tampered = flow.R1AttemptState(
        **{**state.to_json(), "bootstrap_out": str(evidence_dir / "not-canonical.json")}
    )

    with pytest.raises(R1OperatorFlowError, match="bootstrap_out is not the canonical path"):
        revalidate_attempt_state_against_live_repo(tampered)


def test_revalidate_rejects_report_out_that_is_not_the_canonical_path(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    tampered = flow.R1AttemptState(
        **{**state.to_json(), "report_out": str(evidence_dir / "not-canonical.json")}
    )

    with pytest.raises(R1OperatorFlowError, match="report_out is not the canonical path"):
        revalidate_attempt_state_against_live_repo(tampered)


def test_revalidate_rejects_release_registry_path_redirected_to_an_external_copy(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    registry_path = _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    external_copy = tmp_path / "external-copy-release-registry.json"
    external_copy.write_bytes(registry_path.read_bytes())

    tampered = flow.R1AttemptState(
        **{**state.to_json(), "sealed_release_registry_path": str(external_copy)}
    )

    with pytest.raises(R1OperatorFlowError, match="not the canonical path"):
        revalidate_attempt_state_against_live_repo(tampered)


def test_revalidate_still_succeeds_for_a_genuinely_untouched_attempt_with_all_r1f_checks(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """Confirms the new R1F gates (worktree re-exclusion, canonical output
    paths, canonical release-registry path) do not, together, break the
    ordinary successful path any of the R1E-era tests already exercise."""
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )

    assert revalidate_attempt_state_against_live_repo(state) == head


def test_evidence_directory_containing_a_space_is_accepted(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """R1F Section 8: evidence_dir is a filesystem path, not an identifier
    -- safe-scalar validation must never reach it."""
    _no_runtime_check(monkeypatch)
    head = _head(git_repo)
    _sealed_registry_at(git_repo)
    evidence_dir = tmp_path / "R1 evidence" / "sub dir"
    evidence_dir.mkdir(parents=True)

    state = build_attempt_state(
        repo_root=git_repo, qualified_exporter_commit=head, evidence_dir=evidence_dir
    )
    state_path = canonical_attempt_state_path(evidence_dir, state.attempt_id)
    write_attempt_state(state_path, state)
    loaded = load_attempt_state(state_path)

    assert revalidate_attempt_state_against_live_repo(loaded) == head
