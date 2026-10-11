"""L'orchestrateur d'émission refuse toute écriture avant les deux gates live."""

# ruff: noqa: E402

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

import emit_student_public_scopes as issuer
from build_public_successor_content_anchor import canonical_bytes
from check_public_successor_preissuance import (
    PreissuanceVerdict,
    build_preissuance_receipt,
)

ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
MANIFEST = ROOT / (
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_successor_v1/release-fcc84331e7700042/"
    "profile_gate/production-profile-gate.release.json"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_remote_main_check_allows_slow_valid_git_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La latence TLS de GitHub ne doit pas écarter un main exact vérifié live."""
    expected = "a" * 40 + "\trefs/heads/main"

    def slow_remote(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert args == ["git", "ls-remote", "--exit-code", "origin", "refs/heads/main"]
        if kwargs["timeout"] < 60:
            raise subprocess.TimeoutExpired(args, kwargs["timeout"])
        return subprocess.CompletedProcess(args, 0, expected + "\n", "")

    monkeypatch.setattr(issuer.subprocess, "run", slow_remote)
    assert issuer._git(ROOT, "ls-remote", "--exit-code", "origin", "refs/heads/main") == expected


def test_remote_main_check_still_refuses_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == issuer.REMOTE_MAIN_CHECK_TIMEOUT_SECONDS
        raise subprocess.TimeoutExpired(args, kwargs["timeout"])

    monkeypatch.setattr(issuer.subprocess, "run", unavailable)
    with pytest.raises(issuer.StudentPublicScopeEmissionError, match="unavailable"):
        issuer._git(ROOT, "ls-remote", "--exit-code", "origin", "refs/heads/main")


def _inputs(tmp_path: Path) -> dict[str, object]:
    return {
        "anchor_path": ANCHOR,
        "anchor_sha256": _sha(ANCHOR),
        "subject_release": MANIFEST,
        "subject_release_sha256": _sha(MANIFEST),
        "preissuance_receipt": tmp_path / "receipt.json",
        "preissuance_receipt_sha256": "a" * 64,
        "private_cas_root": tmp_path / "cas",
        "policy_registry": tmp_path / "policy.yml",
        "policy_registry_sha256": "b" * 64,
        "successor_authority": tmp_path / "names.yml",
        "successor_authority_sha256": "c" * 64,
        "artifacts_dir": tmp_path / "scopes",
        "repo_root": ROOT,
    }


def _preissuance(expires: datetime) -> PreissuanceVerdict:
    anchor = json.loads(ANCHOR.read_bytes())
    return PreissuanceVerdict(
        _sha(ANCHOR), _sha(MANIFEST),
        {row["collection"]: row["subject_sha256"] for row in anchor["subjects"]},
        expires, True, False,
    )


def _review() -> issuer.ScopePolicyReviewEvidence:
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    tree = subprocess.check_output(["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True).strip()
    return issuer.ScopePolicyReviewEvidence(
        head_sha="a" * 40,
        tree_sha=tree,
        checkout_head_sha=head,
        reviewer="abenrhouma",
        policy_registry_sha256="b" * 64,
        successor_authority_sha256="c" * 64,
        content_anchor_sha256=_sha(ANCHOR),
    )


def test_verified_preissuance_and_exact_review_reach_v3_builder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = []
    now = datetime.now(UTC)
    params = _inputs(tmp_path)
    monkeypatch.setattr(
        issuer, "_require_current_clean_main", lambda _root: _review().checkout_head_sha,
    )

    def preissuance(*_args: object) -> PreissuanceVerdict:
        calls.append("preissuance")
        return _preissuance(now + timedelta(hours=1))

    def review(*_args: object) -> issuer.ScopePolicyReviewEvidence:
        calls.append("review")
        return _review()

    def emit(**kwargs: object) -> str:
        calls.append("emit")
        evidence = kwargs["student_scope_evidence"]
        assert evidence.content_manifest_sha256 == _sha(MANIFEST)
        assert len(evidence.subject_sha256_by_collection) == 11
        assert evidence.reviewed_policy_registry_sha256 == "b" * 64
        return "V3_BUILDER_CALLED"

    assert issuer.emit_student_public_scopes(
        **params, now_utc=now, preissuance_verifier=preissuance,
        policy_review_verifier=review, scope_emitter=emit,
    ) == "V3_BUILDER_CALLED"
    assert calls == ["preissuance", "review", "emit"]


def test_source_currentness_expiring_during_review_refuses_before_scope_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    current = [now]
    calls: list[str] = []
    params = _inputs(tmp_path)
    monkeypatch.setattr(issuer, "_utc_now", lambda: current[0], raising=False)
    monkeypatch.setattr(
        issuer, "_require_current_clean_main", lambda _root: _review().checkout_head_sha,
    )

    def preissuance(*_args: object) -> PreissuanceVerdict:
        calls.append("preissuance")
        return _preissuance(now + timedelta(seconds=1))

    def review(*_args: object) -> issuer.ScopePolicyReviewEvidence:
        calls.append("review")
        current[0] = now + timedelta(seconds=2)
        return _review()

    with pytest.raises(issuer.StudentPublicScopeEmissionError, match="expired"):
        issuer.emit_student_public_scopes(
            **params, now_utc=now, preissuance_verifier=preissuance,
            policy_review_verifier=review,
            scope_emitter=lambda **_kwargs: calls.append("emit"),
        )
    assert calls == ["preissuance", "review"]
    assert not params["artifacts_dir"].exists()


def test_origin_main_moving_during_review_refuses_before_scope_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    params = _inputs(tmp_path)
    checkout = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    calls: list[str] = []

    def git(_root: Path, *args: str) -> str:
        if args == ("rev-parse", "HEAD"):
            return checkout
        if args == ("rev-parse", "origin/main"):
            return checkout
        if args == ("ls-remote", "--exit-code", "origin", "refs/heads/main"):
            return f"{'f' * 40}\trefs/heads/main"
        if args == ("status", "--porcelain"):
            return ""
        raise AssertionError(args)

    monkeypatch.setattr(issuer, "_git", git)
    with pytest.raises(issuer.StudentPublicScopeEmissionError, match="main"):
        issuer.emit_student_public_scopes(
            **params, now_utc=now,
            preissuance_verifier=lambda *_args: _preissuance(now + timedelta(hours=1)),
            policy_review_verifier=lambda *_args: _review(),
            scope_emitter=lambda **_kwargs: calls.append("emit"),
        )
    assert calls == []


@pytest.mark.parametrize("sabotage", ["missing", "tampered", "expired", "review"])
def test_missing_or_invalid_gate_refuses_before_any_scope_write(
    tmp_path: Path, sabotage: str,
) -> None:
    now = datetime.now(UTC)
    params = _inputs(tmp_path)
    calls = []

    def preissuance(*_args: object) -> PreissuanceVerdict:
        calls.append("preissuance")
        if sabotage in {"missing", "tampered"}:
            raise ValueError("missing or altered receipt")
        expiry = now - timedelta(seconds=1) if sabotage == "expired" else now + timedelta(hours=1)
        return _preissuance(expiry)

    def review(*_args: object) -> issuer.ScopePolicyReviewEvidence:
        calls.append("review")
        if sabotage == "review":
            raise ValueError("exact-head review missing")
        return _review()

    def emit(**_kwargs: object) -> str:
        calls.append("emit")
        return "SHOULD_NOT_EMIT"

    with pytest.raises(issuer.StudentPublicScopeEmissionError):
        issuer.emit_student_public_scopes(
            **params, now_utc=now, preissuance_verifier=preissuance,
            policy_review_verifier=review, scope_emitter=emit,
        )
    assert "emit" not in calls
    assert not params["artifacts_dir"].exists()


@pytest.mark.parametrize("sabotage", ["missing", "tampered", "expired"])
def test_real_preissuance_verifier_rejects_receipt_before_emitter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, sabotage: str,
) -> None:
    params = _inputs(tmp_path)
    cas = params["private_cas_root"]
    assert isinstance(cas, Path)
    cas.mkdir()
    (cas / "index.json").write_bytes(b"{}\n")
    receipt = params["preissuance_receipt"]
    assert isinstance(receipt, Path)
    receipt.write_bytes(canonical_bytes(build_preissuance_receipt(
        ANCHOR, _sha(ANCHOR), MANIFEST, ROOT, cas,
    )))
    params["preissuance_receipt_sha256"] = _sha(receipt)
    if sabotage == "missing":
        receipt.unlink()
    elif sabotage == "tampered":
        document = json.loads(receipt.read_bytes())
        document["subject_sha256_by_collection"][next(iter(
            document["subject_sha256_by_collection"]
        ))] = "f" * 64
        receipt.write_bytes(canonical_bytes(document))
    import check_public_successor_preissuance as pre_module

    monkeypatch.setattr(pre_module, "inspect_content_preparation", lambda *_a, **_k: {
        "inclusion_population_verified": True,
        "private_cas_replay_verified": True,
        "source_currentness_window_open": True,
        "activation_allowed": False,
    })
    monkeypatch.setattr(pre_module, "_require_cas_index_matches", lambda *_a: None)
    now = datetime.now(UTC) + (timedelta(days=3) if sabotage == "expired" else timedelta())
    called = []
    with pytest.raises(issuer.StudentPublicScopeEmissionError):
        issuer.emit_student_public_scopes(
            **params, now_utc=now,
            policy_review_verifier=lambda *_a: _review(),
            scope_emitter=lambda **_k: called.append("emit"),
        )
    assert called == []
    assert not params["artifacts_dir"].exists()


def test_live_review_binds_merged_pr_head_and_current_checkout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pr294_scope_review_receipt as receipt
    import trusted_human_review_github as adapter

    monkeypatch.setattr(adapter, "check_github_review", lambda **_kwargs: (_ for _ in ()).throw(
        issuer.StudentPublicScopeEmissionError("closed PR cannot use open review verifier")
    ))

    checkout = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    original_git = issuer._git
    git_preflight: list[tuple[str, ...]] = []
    def checked_git(root: Path, *args: str) -> str:
        git_preflight.append(args)
        if args == ("rev-parse", "origin/main"):
            return checkout
        if args == ("ls-remote", "--exit-code", "origin", "refs/heads/main"):
            return f"{checkout}\trefs/heads/main"
        if args == ("status", "--porcelain"):
            return ""
        return original_git(root, *args)
    monkeypatch.setattr(issuer, "_git", lambda root, *args: (
        checked_git(root, *args)
    ))
    approved_head = "a" * 40
    merge = "b" * 40
    approved_tree = "c" * 40
    files = {
        "anchor": ANCHOR.read_bytes(),
        "policy": (ROOT / receipt.FILES["policy"]).read_bytes(),
        "names": (ROOT / receipt.FILES["names"]).read_bytes(),
    }
    monkeypatch.setattr(receipt, "_live_evidence", lambda _root: (
        {"head": {"sha": approved_head}, "merge_commit_sha": merge},
        {"approved": True, "reason": "approved", "head_sha": approved_head,
         "reviewer": "abenrhouma"},
        {"state": "success"}, {"event": "pull_request_target"}, approved_tree,
    ))
    monkeypatch.setattr(receipt, "_read_reviewed_files", lambda _root, _head: files)
    review = issuer.verify_live_scope_policy_review(
        ROOT, ROOT / receipt.FILES["policy"], _sha(ROOT / receipt.FILES["policy"]),
        ROOT / receipt.FILES["names"], _sha(ROOT / receipt.FILES["names"]),
        ANCHOR, _sha(ANCHOR),
    )
    assert review.head_sha == approved_head
    assert review.tree_sha == approved_tree
    assert review.checkout_head_sha == checkout
    assert ("ls-remote", "--exit-code", "origin", "refs/heads/main") in git_preflight
    assert ("status", "--porcelain") in git_preflight


@pytest.mark.parametrize("sabotage", ["policy", "head", "remote", "dirty"])
def test_live_review_refuses_changed_reviewed_input_or_checkout(
    monkeypatch: pytest.MonkeyPatch, sabotage: str,
) -> None:
    import pr294_scope_review_receipt as receipt
    import trusted_human_review_github as adapter

    monkeypatch.setattr(adapter, "check_github_review", lambda **_kwargs: (_ for _ in ()).throw(
        issuer.StudentPublicScopeEmissionError("closed PR cannot use open review verifier")
    ))
    checkout = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    original_git = issuer._git
    monkeypatch.setattr(issuer, "_git", lambda root, *args: (
        checkout if args == ("rev-parse", "origin/main") else
        f"{'f' * 40 if sabotage == 'remote' else checkout}\trefs/heads/main"
        if args == ("ls-remote", "--exit-code", "origin", "refs/heads/main") else
        " M scripts/go_live/emit_student_public_scopes.py"
        if args == ("status", "--porcelain") and sabotage == "dirty" else
        "" if args == ("status", "--porcelain") else original_git(root, *args)
    ))

    files = {
        "anchor": ANCHOR.read_bytes(),
        "policy": (ROOT / receipt.FILES["policy"]).read_bytes(),
        "names": (ROOT / receipt.FILES["names"]).read_bytes(),
    }
    if sabotage == "policy":
        files["policy"] += b"\n"
    monkeypatch.setattr(receipt, "_live_evidence", lambda _root: (
        {"head": {"sha": "a" * 40}, "merge_commit_sha": "b" * 40},
        {"approved": True, "reason": "approved", "head_sha":
         "f" * 40 if sabotage == "head" else "a" * 40, "reviewer": "abenrhouma"},
        {"state": "success"}, {"event": "pull_request_target"}, "c" * 40,
    ))
    monkeypatch.setattr(receipt, "_read_reviewed_files", lambda _root, _head: files)
    with pytest.raises(issuer.StudentPublicScopeEmissionError):
        issuer.verify_live_scope_policy_review(
            ROOT, ROOT / receipt.FILES["policy"], _sha(ROOT / receipt.FILES["policy"]),
            ROOT / receipt.FILES["names"], _sha(ROOT / receipt.FILES["names"]),
            ANCHOR, _sha(ANCHOR),
        )
