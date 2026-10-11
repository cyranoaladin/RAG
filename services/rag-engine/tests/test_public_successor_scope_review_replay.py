"""Le signer C rejoue la revue exacte correspondant au reçu B scellé."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/rag-engine/scripts"))
sys.path.insert(0, str(ROOT / "packages/release-chain/src"))
sys.path.insert(0, str(ROOT / "packages/contracts/src"))

import public_successor_signing_replay as replay  # noqa: E402

SHA = "a" * 64


def _receipt(tmp_path: Path, *, kind: str, pull_request: int) -> None:
    authorities = tmp_path / "authorities"
    authorities.mkdir()
    (authorities / "exact_head_scope_review_receipt_sha256.bin").write_text(
        json.dumps({"kind": kind, "pull_request": pull_request}), encoding="utf-8",
    )


def test_signer_replays_fresh_scope_review_with_explicit_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _receipt(tmp_path, kind="PR330_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1", pull_request=330)
    calls: list[int] = []

    def check(*_args: object, review_binding: object) -> dict[str, object]:
        calls.append(review_binding.pull_request)
        return {
            "PR330_SCOPE_REVIEW_PASS": True, "PUBLICATION_AUTHORIZED": False,
            "PUBLIC_SCOPE_AUTHORITY_SHA256": SHA, "SCOPE_COUNT": 11,
        }

    monkeypatch.setattr(replay, "_checkout_module", lambda _name: SimpleNamespace(
        REVIEW_BINDINGS={330: SimpleNamespace(pull_request=330)},
        check_scope_review_receipt=check,
    ))
    replay._replay_live_scope_review(ROOT, tmp_path, SHA, 11)
    assert calls == [330]


def test_signer_refuses_kind_pr_mismatch_before_checker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _receipt(tmp_path, kind="PR330_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1", pull_request=294)
    monkeypatch.setattr(
        replay, "_checkout_module", lambda _name: pytest.fail("checker called on mismatch"),
    )
    with pytest.raises(replay.PublicationSigningReplayRefused):
        replay._replay_live_scope_review(ROOT, tmp_path, SHA, 11)
