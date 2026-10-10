"""L'orchestrateur d'émission refuse toute écriture avant les deux gates live."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

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
        head_sha=head,
        tree_sha=tree,
        reviewer="abenrhouma",
        policy_registry_sha256="b" * 64,
        successor_authority_sha256="c" * 64,
        content_anchor_sha256=_sha(ANCHOR),
    )


def test_verified_preissuance_and_exact_review_reach_v3_builder(
    tmp_path: Path,
) -> None:
    calls = []
    now = datetime.now(UTC)
    params = _inputs(tmp_path)

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


@pytest.mark.parametrize("status", ["success", "failure"])
def test_live_review_requires_current_exact_head_and_trusted_status(
    monkeypatch: pytest.MonkeyPatch, status: str,
) -> None:
    github = ROOT / "scripts/github"
    if str(github) not in sys.path:
        sys.path.insert(0, str(github))
    import trusted_human_review_github as adapter

    head = "a" * 40
    base = "b" * 40
    tree = "c" * 40
    checked_files = []
    monkeypatch.setattr(issuer, "_require_file_at_head", lambda *_a: checked_files.append(1))
    monkeypatch.setattr(issuer, "_git", lambda _root, *args: tree if args[-1] == "HEAD^{tree}" else head)
    decision = SimpleNamespace(
        approved=True, reason="approved", head_sha=head, base_sha=base,
        reviewer="abenrhouma", submitted_at="2026-10-10T10:00:00Z",
    )
    monkeypatch.setattr(adapter, "check_github_review", lambda **_k: SimpleNamespace(
        decision=decision,
    ))
    def api(argv: list[str]) -> dict[str, object]:
        if argv[-1].endswith("/status"):
            return {"statuses": [{
                "context": "trusted-human-review/head-pinned",
                "state": status, "created_at": "2026-10-10T10:01:00Z",
                "target_url": "https://github.com/cyranoaladin/RAG/actions/runs/123",
            }]}
        return {
            "id": 123, "name": "Trusted human review",
            "path": ".github/workflows/trusted-human-review.yml",
            "event": "issue_comment", "status": "completed", "conclusion": "success",
            "head_sha": base,
        }
    monkeypatch.setattr(adapter, "run_gh_api", api)
    args = (
        ROOT, ROOT / "policy.yml", "d" * 64,
        ROOT / "names.yml", "e" * 64,
        ANCHOR, _sha(ANCHOR),
    )
    if status == "failure":
        with pytest.raises(issuer.StudentPublicScopeEmissionError, match="status"):
            issuer.verify_live_scope_policy_review(*args)
    else:
        review = issuer.verify_live_scope_policy_review(*args)
        assert review.head_sha == head
        assert review.tree_sha == tree
        assert review.reviewer == "abenrhouma"
        assert review.policy_registry_sha256 == "d" * 64
    assert len(checked_files) == 3
