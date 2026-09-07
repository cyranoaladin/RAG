from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from nexus_contracts import (
    BootstrapChunk,
    BootstrapResourceVersion,
    ResourceRegistryBootstrapPayload,
    seal_resource_registry_bootstrap,
)

from ingestor import r1_attempt_preflight_cli, r1_export_and_verify_cli
from ingestor.r1_evidence_verifier import R1EvidenceReport
from ingestor.r1_operator_flow import (
    ATTEMPT_STATE_PROTOCOL_VERSION,
    EXPECTED_SEALED_RELEASE_REGISTRY_SHA256,
    R1AttemptState,
    R1OperatorFlowError,
    build_attempt_state,
    canonical_attempt_output_paths,
    canonical_attempt_state_path,
    generate_attempt_id,
    list_repo_worktrees,
    load_attempt_state,
    write_attempt_state,
)

SHA_A = "a" * 64
SHA_B = "b" * 64

REAL_REGISTRY = (
    Path(__file__).resolve().parents[2]
    / "rag-pedago"
    / "data"
    / "releases"
    / "prerentree_2026_2027"
    / "release-registry.json"
)

FIXED_GENERATED_AT = datetime(2026, 8, 30, 12, tzinfo=UTC)


def _run(*args: str, cwd: Path) -> None:
    subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True)


@pytest.fixture(autouse=True)
def _bypass_runtime_provenance_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "ingestor.r1_operator_flow.assert_runtime_bound_to_qualified_checkout",
        lambda repo_root: None,
    )


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


def _build_state(repo: Path, evidence_dir: Path, *, attempt_id: str | None = None) -> R1AttemptState:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    return build_attempt_state(
        repo_root=repo,
        qualified_exporter_commit=_head(repo),
        evidence_dir=evidence_dir,
        attempt_id=attempt_id,
    )


def _write_state(evidence_dir: Path, state: R1AttemptState) -> Path:
    path: Path = canonical_attempt_state_path(evidence_dir, state.attempt_id)
    write_attempt_state(path, state)
    return path


def _inventory(*, producer_commit: str) -> object:
    return seal_resource_registry_bootstrap(
        ResourceRegistryBootstrapPayload.model_validate(
            {
                "protocol_version": "1",
                "producer_repository": "cyranoaladin/RAG",
                "producer_commit": producer_commit,
                "package_version": "0.15.0",
                "source_snapshot_sha256": SHA_B,
                "generated_at": FIXED_GENERATED_AT,
                "resources": [
                    BootstrapResourceVersion(
                        resource_id="11111111-1111-4111-8111-111111111111",
                        resource_version_id="22222222-2222-4222-8222-222222222222",
                        content_sha256=SHA_A,
                        rag_artifact_id=SHA_A,
                        size_bytes=42,
                        mime_type="application/pdf",
                        source_label="Programme officiel",
                        source_uri="https://eduscol.education.fr/programme.pdf",
                        rights="officiel_public",
                        official=True,
                        source_kind="eduscol.education.fr",
                        type_doc="programme_officiel",
                        placements=[
                            {
                                "tenant": "nexus",
                                "collection": "terminale_maths",
                                "niveau": "terminale",
                                "voie": "generale",
                                "matiere": "mathematiques",
                                "statut_enseignement": "specialite",
                                "candidat": "scolarise",
                                "audience": ["aefe"],
                                "visibility": "internal",
                                "school_year": "2026-2027",
                                "programme_version": "fr-national-2026",
                            }
                        ],
                        chunks=[
                            BootstrapChunk(
                                chunk_id="chunk-001",
                                locator={"chunk_index": 0, "page": 1},
                            )
                        ],
                    )
                ],
            }
        )
    )


class _ConnectionContext:
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


class _ReleaseRegistry:
    collections = ("terminale_maths",)
    manifests = (
        type(
            "ManifestBinding",
            (),
            {
                "expectation": type(
                    "ReleaseExpectation",
                    (),
                    {
                        "artifacts": (
                            type(
                                "Artifact",
                                (),
                                {"collection": "terminale_maths", "content_sha256": SHA_A},
                            )(),
                        )
                    },
                )()
            },
        )(),
    )


PASSING_REPORT = R1EvidenceReport(ready=True, gates={"BOOTSTRAP_RESOURCE_ROWS": 1})


def _patch_export_layer(
    monkeypatch: pytest.MonkeyPatch,
    *,
    connect_dsn_should_be: str | None = None,
    export_side_effect=None,
    verify_side_effect=None,
) -> dict[str, object]:
    captured: dict[str, object] = {}

    def _connect(dsn: str) -> _ConnectionContext:
        if connect_dsn_should_be is not None:
            assert dsn == connect_dsn_should_be
        return _ConnectionContext()

    monkeypatch.setattr(r1_export_and_verify_cli.psycopg, "connect", _connect)

    def _export(*_a: object, **kwargs: object) -> object:
        captured["export_kwargs"] = kwargs
        if export_side_effect is not None:
            return export_side_effect(**kwargs)
        return _inventory(producer_commit=str(kwargs["producer_commit"]))

    monkeypatch.setattr(
        r1_export_and_verify_cli, "export_resource_registry_bootstrap_inventory", _export
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli.metadata,
        "version",
        lambda package: "0.15.0" if package == "nexus-contracts" else "",
    )
    monkeypatch.setattr(
        r1_export_and_verify_cli,
        "load_release_registry_file",
        lambda path, digest: _ReleaseRegistry()
        if digest == EXPECTED_SEALED_RELEASE_REGISTRY_SHA256
        else None,
    )

    def _verify(**kwargs: object) -> R1EvidenceReport:
        captured["verify_kwargs"] = kwargs
        captured["dsn_present_during_verify"] = r1_export_and_verify_cli.DSN_ENV in os.environ
        if verify_side_effect is not None:
            return verify_side_effect(**kwargs)
        return PASSING_REPORT

    monkeypatch.setattr(r1_export_and_verify_cli, "verify_r1_evidence", _verify)
    return captured


def test_dsn_is_gone_from_environment_before_the_verifier_runs(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    secret_dsn = "postgresql://operator:super-secret@example.invalid/rag"
    state = _build_state(git_repo, tmp_path / "evidence")
    captured = _patch_export_layer(monkeypatch, connect_dsn_should_be=secret_dsn)

    inventory_sha256, resource_count, report = r1_export_and_verify_cli.run_governed_attempt(
        state, dsn=secret_dsn, clock=lambda: FIXED_GENERATED_AT
    )

    assert report.ready is True
    assert resource_count == 1
    assert inventory_sha256
    assert captured["dsn_present_during_verify"] is False
    assert r1_export_and_verify_cli.DSN_ENV not in os.environ
    assert Path(state.bootstrap_out).exists()
    assert Path(state.report_out).exists()


def test_generated_at_is_captured_at_call_time_via_the_injectable_clock(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    state = _build_state(git_repo, tmp_path / "evidence")
    captured = _patch_export_layer(monkeypatch)

    r1_export_and_verify_cli.run_governed_attempt(
        state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
    )

    export_kwargs = captured["export_kwargs"]
    assert export_kwargs["generated_at"] == FIXED_GENERATED_AT  # type: ignore[index]


def test_producer_commit_passed_to_exporter_is_the_freshly_revalidated_actual_head(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    head = _head(git_repo)
    state = _build_state(git_repo, tmp_path / "evidence")
    captured = _patch_export_layer(monkeypatch)

    r1_export_and_verify_cli.run_governed_attempt(
        state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
    )

    export_kwargs = captured["export_kwargs"]
    assert export_kwargs["producer_commit"] == head  # type: ignore[index]


def test_exporter_failure_means_verifier_is_never_invoked(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    state = _build_state(git_repo, tmp_path / "evidence")

    def _export_fails(**_kwargs: object) -> object:
        raise RuntimeError("simulated BootstrapInventoryError")

    _patch_export_layer(monkeypatch, export_side_effect=_export_fails)

    def _verify_must_never_be_called(**_kwargs: object) -> R1EvidenceReport:
        raise AssertionError("verify_r1_evidence must never run when the exporter failed")

    monkeypatch.setattr(
        r1_export_and_verify_cli, "verify_r1_evidence", _verify_must_never_be_called
    )

    with pytest.raises(RuntimeError, match="simulated BootstrapInventoryError"):
        r1_export_and_verify_cli.run_governed_attempt(
            state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )

    assert not Path(state.bootstrap_out).exists()
    assert not Path(state.report_out).exists()


def test_existing_bootstrap_output_refused_before_touching_the_database(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    state = _build_state(git_repo, tmp_path / "evidence")
    Path(state.bootstrap_out).write_bytes(b"already published")

    def _connect_must_never_be_called(dsn: str) -> None:
        raise AssertionError("psycopg.connect must never be called: bootstrap_out already exists")

    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", _connect_must_never_be_called
    )

    with pytest.raises(R1OperatorFlowError, match="already exists"):
        r1_export_and_verify_cli.run_governed_attempt(
            state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )

    assert Path(state.bootstrap_out).read_bytes() == b"already published"


def test_toctou_fails_before_db_after_checkout_changed_since_preflight(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    state = _build_state(git_repo, tmp_path / "evidence")

    (git_repo / "README.md").write_text("changed after preflight\n", encoding="utf-8")
    _run("git", "add", "README.md", cwd=git_repo)
    _run("git", "commit", "-q", "-m", "second", cwd=git_repo)

    def _connect_must_never_be_called(dsn: str) -> None:
        raise AssertionError("psycopg.connect must never be called after HEAD moved")

    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", _connect_must_never_be_called
    )

    with pytest.raises(R1OperatorFlowError, match="not the qualified exporter commit"):
        r1_export_and_verify_cli.run_governed_attempt(
            state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_toctou_fails_before_db_after_tracked_edit_since_preflight(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    state = _build_state(git_repo, tmp_path / "evidence")
    (git_repo / "README.md").write_text("dirtied after preflight\n", encoding="utf-8")

    def _connect_must_never_be_called(dsn: str) -> None:
        raise AssertionError("psycopg.connect must never be called on a dirty tree")

    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", _connect_must_never_be_called
    )

    with pytest.raises(R1OperatorFlowError, match="not clean"):
        r1_export_and_verify_cli.run_governed_attempt(
            state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_toctou_fails_before_db_after_untracked_file_since_preflight(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    state = _build_state(git_repo, tmp_path / "evidence")
    (git_repo / "untracked-after-preflight.txt").write_text("x\n", encoding="utf-8")

    def _connect_must_never_be_called(dsn: str) -> None:
        raise AssertionError("psycopg.connect must never be called on an untracked file")

    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", _connect_must_never_be_called
    )

    with pytest.raises(R1OperatorFlowError, match="not clean"):
        r1_export_and_verify_cli.run_governed_attempt(
            state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def _tamper_state_file(state_path: Path, **overrides: object) -> Path:
    """Simulates an attacker directly editing the published JSON artifact
    (bypassing the atomic no-clobber writer, which real tooling never
    would) -- writes the tampered copy to a sibling path since the real
    artifact itself must stay untouched and no-clobber. Use this only for
    scenarios that specifically test the noncanonical-location refusal;
    for scenarios that test a single-field mismatch downstream in
    revalidation, use :func:`_tamper_state_file_in_place` instead so the
    canonical-location check does not mask the field being tested."""
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    raw.update(overrides)
    tampered_path = state_path.with_name(state_path.stem + "-tampered.json")
    tampered_path.write_text(json.dumps(raw), encoding="utf-8")
    return tampered_path


def _tamper_state_file_in_place(state_path: Path, **overrides: object) -> None:
    """Simulates an attacker with raw filesystem write access overwriting
    the published JSON artifact's bytes in place -- the no-clobber writer
    only protects against a second *publish* through the official API, not
    against a determined attacker editing the file directly. Kept at its
    own canonical location so the resulting state, when loaded, is caught
    by whichever *field*-level revalidation check this attack is meant to
    exercise, rather than by the (separate) canonical-location check."""
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    raw.update(overrides)
    state_path.write_text(json.dumps(raw), encoding="utf-8")


def test_tampered_qualified_commit_field_is_refused(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    evidence_dir = tmp_path / "evidence"
    state = _build_state(git_repo, evidence_dir)
    state_path = _write_state(evidence_dir, state)

    other_commit = "f" * 40
    _tamper_state_file_in_place(state_path, qualified_exporter_commit=other_commit)
    tampered_state = load_attempt_state(state_path)

    def _connect_must_never_be_called(dsn: str) -> None:
        raise AssertionError("psycopg.connect must never be called for a tampered commit")

    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", _connect_must_never_be_called
    )

    with pytest.raises(R1OperatorFlowError, match="not the qualified exporter commit"):
        r1_export_and_verify_cli.run_governed_attempt(
            tampered_state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_tampered_release_registry_sha256_field_is_refused(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    evidence_dir = tmp_path / "evidence"
    state = _build_state(git_repo, evidence_dir)
    state_path = _write_state(evidence_dir, state)

    other_valid_sha = "c" * 64
    _tamper_state_file_in_place(state_path, sealed_release_registry_sha256=other_valid_sha)
    tampered_state = load_attempt_state(state_path)

    def _connect_must_never_be_called(dsn: str) -> None:
        raise AssertionError("psycopg.connect must never be called for a tampered digest")

    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", _connect_must_never_be_called
    )

    with pytest.raises(R1OperatorFlowError, match="digest changed"):
        r1_export_and_verify_cli.run_governed_attempt(
            tampered_state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_tampered_bootstrap_out_path_is_refused_at_load_time(
    git_repo: Path, tmp_path: Path
) -> None:
    evidence_dir = tmp_path / "evidence"
    state = _build_state(git_repo, evidence_dir)
    state_path = _write_state(evidence_dir, state)

    escaped_target = tmp_path / "outside-evidence-dir.json"
    tampered_path = _tamper_state_file(state_path, bootstrap_out=str(escaped_target))

    with pytest.raises(R1OperatorFlowError, match="not direct children"):
        load_attempt_state(tampered_path)


def _craft_self_consistent_state(
    real_state: R1AttemptState, *, evidence_dir: Path, attempt_id: str | None = None
) -> R1AttemptState:
    """Builds and publishes an attempt state that is entirely self-
    consistent (every field, including the output filenames and the
    state file's own location, is derived correctly from the OTHER
    fields) but whose ``evidence_dir`` is a value Phase A itself would
    never have accepted. This is the shape R1E's own direct-child check
    cannot catch -- it only proves internal consistency, never that
    ``evidence_dir`` itself is a legitimate location. Simulates an
    attacker who has read this module's own canonical-derivation rules
    and crafted a state file by hand, bypassing Phase A entirely."""
    resolved_attempt_id = attempt_id or generate_attempt_id()
    bootstrap_out, report_out = canonical_attempt_output_paths(
        evidence_dir,
        release_id=real_state.sealed_release_id,
        qualified_exporter_commit=real_state.qualified_exporter_commit,
        attempt_id=resolved_attempt_id,
    )
    crafted = R1AttemptState(
        protocol_version=ATTEMPT_STATE_PROTOCOL_VERSION,
        attempt_id=resolved_attempt_id,
        qualified_exporter_commit=real_state.qualified_exporter_commit,
        repo_root=real_state.repo_root,
        sealed_release_id=real_state.sealed_release_id,
        sealed_release_registry_path=real_state.sealed_release_registry_path,
        sealed_release_registry_sha256=real_state.sealed_release_registry_sha256,
        evidence_dir=str(evidence_dir.resolve()),
        bootstrap_out=str(bootstrap_out),
        report_out=str(report_out),
        created_at=real_state.created_at,
    )
    evidence_dir.mkdir(parents=True, exist_ok=True)
    state_path = canonical_attempt_state_path(evidence_dir, resolved_attempt_id)
    state_path.write_text(
        json.dumps(crafted.to_json(), ensure_ascii=False), encoding="utf-8"
    )
    return load_attempt_state(state_path)


def _assert_connect_never_called(monkeypatch: pytest.MonkeyPatch) -> None:
    def _connect_must_never_be_called(dsn: str) -> None:
        raise AssertionError("psycopg.connect must never be called before revalidation passes")

    monkeypatch.setattr(
        r1_export_and_verify_cli.psycopg, "connect", _connect_must_never_be_called
    )


def test_self_consistent_state_redirection_into_current_worktree_fails_before_db(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """R1F: a state whose evidence_dir, bootstrap_out, and report_out are
    all mutually consistent -- but whose evidence_dir is inside the
    repository's own primary worktree -- must still fail, and must fail
    before any database connection. The evidence directory this attack
    creates would itself dirty the worktree; ``assert_clean_worktree`` is
    bypassed here so the exclusion gate under test is exercised in
    isolation rather than incidentally caught by an unrelated one."""
    monkeypatch.setattr("ingestor.r1_operator_flow.assert_clean_worktree", lambda repo_root: None)
    real_state = _build_state(git_repo, tmp_path / "real-evidence")
    tampered_state = _craft_self_consistent_state(
        real_state, evidence_dir=git_repo / "evil-evidence-inside-worktree"
    )
    _assert_connect_never_called(monkeypatch)

    with pytest.raises(R1OperatorFlowError, match="repository worktree"):
        r1_export_and_verify_cli.run_governed_attempt(
            tampered_state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_self_consistent_state_redirection_into_another_linked_worktree_fails_before_db(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """Same attack, but the redirection targets a DIFFERENT (linked)
    worktree of the same repository -- not merely the one the operator
    happens to be standing in. Multi-worktree exclusion must be re-derived
    live in Phase B, not assumed from Phase A's own (now stale) check."""
    real_state = _build_state(git_repo, tmp_path / "real-evidence")
    linked_worktree = tmp_path / "linked-worktree"
    _run("git", "worktree", "add", str(linked_worktree), "-b", "other-branch", cwd=git_repo)
    assert linked_worktree.resolve() in list_repo_worktrees(git_repo)

    tampered_state = _craft_self_consistent_state(
        real_state, evidence_dir=linked_worktree / "evil-evidence"
    )
    _assert_connect_never_called(monkeypatch)

    with pytest.raises(R1OperatorFlowError, match="repository worktree"):
        r1_export_and_verify_cli.run_governed_attempt(
            tampered_state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_symlink_evidence_dir_resolving_into_another_worktree_fails_before_db(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """The evidence_dir path itself may sit outside every worktree
    lexically while being a symlink that RESOLVES into one -- resolution,
    not the raw string, is what must be checked. As above, the directory
    this attack creates inside the worktree would itself dirty it, so
    ``assert_clean_worktree`` is bypassed to isolate the exclusion gate."""
    monkeypatch.setattr("ingestor.r1_operator_flow.assert_clean_worktree", lambda repo_root: None)
    real_state = _build_state(git_repo, tmp_path / "real-evidence")
    target_inside_worktree = git_repo / "evil-target"
    target_inside_worktree.mkdir(parents=True)
    symlinked_evidence_dir = tmp_path / "looks-external"
    symlinked_evidence_dir.symlink_to(target_inside_worktree)

    tampered_state = _craft_self_consistent_state(
        real_state, evidence_dir=symlinked_evidence_dir
    )
    _assert_connect_never_called(monkeypatch)

    with pytest.raises(R1OperatorFlowError, match="repository worktree"):
        r1_export_and_verify_cli.run_governed_attempt(
            tampered_state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_tampered_canonical_bootstrap_filename_fails_before_db(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """bootstrap_out is changed to a different (still direct-child,
    still-nonexistent) filename that does not match the canonical stem
    derived from this attempt's own release id, commit, and attempt id."""
    evidence_dir = tmp_path / "evidence"
    state = _build_state(git_repo, evidence_dir)
    state_path = _write_state(evidence_dir, state)

    noncanonical_bootstrap = evidence_dir / "not-the-canonical-bootstrap-name.json"
    _tamper_state_file_in_place(state_path, bootstrap_out=str(noncanonical_bootstrap))
    tampered_state = load_attempt_state(state_path)
    _assert_connect_never_called(monkeypatch)

    with pytest.raises(R1OperatorFlowError, match="bootstrap_out is not the canonical path"):
        r1_export_and_verify_cli.run_governed_attempt(
            tampered_state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_tampered_canonical_report_filename_fails_before_db(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    evidence_dir = tmp_path / "evidence"
    state = _build_state(git_repo, evidence_dir)
    state_path = _write_state(evidence_dir, state)

    noncanonical_report = evidence_dir / "not-the-canonical-report-name.json"
    _tamper_state_file_in_place(state_path, report_out=str(noncanonical_report))
    tampered_state = load_attempt_state(state_path)
    _assert_connect_never_called(monkeypatch)

    with pytest.raises(R1OperatorFlowError, match="report_out is not the canonical path"):
        r1_export_and_verify_cli.run_governed_attempt(
            tampered_state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_attempt_state_copied_to_noncanonical_path_fails_before_db(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """A byte-for-byte copy of a genuinely valid attempt state, placed
    anywhere other than its own canonical location, must never be
    trusted -- regardless of how correct its contents are."""
    evidence_dir = tmp_path / "evidence"
    state = _build_state(git_repo, evidence_dir)
    state_path = _write_state(evidence_dir, state)
    copied_path = state_path.with_name("copied-" + state_path.name)
    copied_path.write_bytes(state_path.read_bytes())

    monkeypatch.setenv(r1_export_and_verify_cli.DSN_ENV, "postgresql://fixture")
    _assert_connect_never_called(monkeypatch)

    with pytest.raises(SystemExit, match="not the canonical location"):
        r1_export_and_verify_cli.main(["--attempt-state", str(copied_path)])


def test_release_registry_path_changed_to_byte_identical_external_copy_fails_before_db(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """The state must not be able to redirect Phase B toward a copied
    release-registry file outside the qualified checkout, even when that
    copy's bytes -- and therefore its digest and release id -- are
    identical to the real one."""
    evidence_dir = tmp_path / "evidence"
    state = _build_state(git_repo, evidence_dir)
    state_path = _write_state(evidence_dir, state)

    external_copy = tmp_path / "external-copy-release-registry.json"
    external_copy.write_bytes(Path(state.sealed_release_registry_path).read_bytes())
    assert external_copy.read_bytes() == Path(state.sealed_release_registry_path).read_bytes()

    _tamper_state_file_in_place(state_path, sealed_release_registry_path=str(external_copy))
    tampered_state = load_attempt_state(state_path)
    _assert_connect_never_called(monkeypatch)

    with pytest.raises(R1OperatorFlowError, match="not the canonical path"):
        r1_export_and_verify_cli.run_governed_attempt(
            tampered_state, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
        )


def test_evidence_directory_containing_spaces_end_to_end_succeeds(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path
) -> None:
    """R1F Section 8: an evidence directory is a filesystem path, not an
    identifier -- it must remain valid even when it contains an ordinary
    space. Safe-scalar validation must never be applied to it."""
    evidence_dir = tmp_path / "R1 evidence" / "sub dir"
    state = _build_state(git_repo, evidence_dir)
    state_path = _write_state(evidence_dir, state)
    loaded = load_attempt_state(state_path)

    captured = _patch_export_layer(monkeypatch)
    inventory_sha256, resource_count, report = r1_export_and_verify_cli.run_governed_attempt(
        loaded, dsn="postgresql://fixture", clock=lambda: FIXED_GENERATED_AT
    )

    assert report.ready is True
    assert resource_count == 1
    assert inventory_sha256
    assert captured["export_kwargs"] is not None
    assert Path(loaded.bootstrap_out).exists()
    assert Path(loaded.report_out).exists()


def test_main_refuses_attempt_state_that_fails_to_load(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(r1_export_and_verify_cli.DSN_ENV, "postgresql://fixture")
    bogus_state_path = tmp_path / "not-a-real-state.json"
    bogus_state_path.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit, match="attempt state is not sound"):
        r1_export_and_verify_cli.main(["--attempt-state", str(bogus_state_path)])


def test_main_requires_the_dsn_env_var_and_never_accepts_it_on_argv(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match=r1_export_and_verify_cli.DSN_ENV):
        r1_export_and_verify_cli.main(["--attempt-state", str(tmp_path / "irrelevant.json")])


def test_end_to_end_real_phase_a_then_phase_b_via_the_attempt_state_file(
    monkeypatch: pytest.MonkeyPatch, git_repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The Phase A CLI runs for real and publishes a real attempt-state
    file; Phase B's ``main`` loads exactly that file (as an operator would,
    via ``--attempt-state``) -- only the database layer itself is mocked."""
    evidence_dir = tmp_path / "evidence"
    head = _head(git_repo)

    phase_a_result = r1_attempt_preflight_cli.main(
        [
            "--repo-root",
            str(git_repo),
            "--qualified-exporter-commit",
            head,
            "--evidence-dir",
            str(evidence_dir),
        ]
    )
    assert phase_a_result == 0
    phase_a_output = capsys.readouterr().out
    state_path_line = next(
        line for line in phase_a_output.splitlines() if line.startswith("R1_ATTEMPT_STATE_PATH=")
    )
    state_path = state_path_line.removeprefix("R1_ATTEMPT_STATE_PATH=")

    _patch_export_layer(monkeypatch)
    monkeypatch.setenv(r1_export_and_verify_cli.DSN_ENV, "postgresql://fixture")

    phase_b_result = r1_export_and_verify_cli.main(["--attempt-state", state_path])

    assert phase_b_result == 0
    phase_b_output = capsys.readouterr().out
    assert "R1_EVIDENCE_READY=YES" in phase_b_output
    assert r1_export_and_verify_cli.DSN_ENV not in os.environ
