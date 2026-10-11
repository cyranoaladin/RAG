"""Une nouvelle release A exige une nouvelle revue exacte, distincte de #294."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))
sys.path.insert(0, str(ROOT / "scripts/tests"))

import pr294_scope_review_receipt as receipt  # noqa: E402
import emit_student_public_scopes as issuer  # noqa: E402
from test_pr294_scope_review_receipt import _fixture  # noqa: E402
from trusted_human_review import build_challenge  # noqa: E402


def _new_receipt(tmp_path: Path) -> tuple:
    parts = list(_fixture(tmp_path))
    doc = parts[0]
    doc["kind"] = "PR330_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1"
    doc["pull_request"] = 330
    doc["challenge"] = build_challenge({
        "protocol": "NEXUS-TRUSTED-REVIEW-V1",
        "repository": doc["repository"], "pull_request": 330,
        "base_ref": doc["base_ref"], "base_sha": doc["base_sha"],
        "head_sha": doc["head_sha"], "author": doc["author"],
        "reviewer": doc["reviewer"],
    })
    parts[2]["number"] = 330
    parts[3]["challenge"] = doc["challenge"]
    return tuple(parts)


def test_fresh_review_binding_accepts_only_its_own_exact_challenge(tmp_path: Path) -> None:
    doc, registry, pr, decision, status, run, files, bundle = _new_receipt(tmp_path)
    result = receipt.validate_scope_review_receipt(
        doc, registry, files, bundle, review_binding=receipt.PR330_BINDING,
        pull_request=pr, review_decision=decision, trusted_status=status,
        workflow_run=run, head_tree_sha=doc["head_tree_sha"],
    )
    assert result["PR330_SCOPE_REVIEW_PASS"] is True
    assert result["PUBLICATION_AUTHORIZED"] is False
    with pytest.raises(receipt.ScopeReviewReceiptError):
        receipt.validate_pr294_scope_receipt(
            doc, registry, files, bundle, pull_request=pr,
            review_decision=decision, trusted_status=status,
            workflow_run=run, head_tree_sha=doc["head_tree_sha"],
        )


@pytest.mark.parametrize("sabotage", ["pr", "challenge", "kind", "attempt", "base"])
def test_fresh_binding_refuses_cross_release_or_stale_review(tmp_path: Path, sabotage: str) -> None:
    parts = list(_new_receipt(tmp_path))
    doc = parts[0]
    if sabotage == "pr":
        doc["pull_request"] = 294
    elif sabotage == "challenge":
        doc["challenge"] = "NEXUS-TRUSTED-REVIEW-V1:" + "f" * 64
    elif sabotage == "kind":
        doc["kind"] = receipt.KIND
    elif sabotage == "attempt":
        doc["workflow_run_attempt"] = 1
    else:
        doc["base_sha"] = "f" * 40
    with pytest.raises(receipt.ScopeReviewReceiptError):
        receipt.validate_scope_review_receipt(
            doc, parts[1], parts[6], parts[7], review_binding=receipt.PR330_BINDING,
            pull_request=parts[2], review_decision=parts[3],
            trusted_status=parts[4], workflow_run=parts[5],
            head_tree_sha="c" * 40,
        )


def test_fresh_binding_uses_new_anchor_path() -> None:
    assert receipt.PR330_BINDING.files["anchor"] == (
        "docs/reports/go_live/student_public_successor_content_anchor_20261011.json"
    )
    assert receipt.PR330_BINDING.files["policy"] == receipt.FILES["policy"]
    assert receipt.PR330_BINDING.files["names"] == receipt.FILES["names"]


def test_scope_emitter_must_request_fresh_review_explicitly() -> None:
    import inspect

    params = inspect.signature(issuer.emit_student_public_scopes).parameters
    assert "scope_review_pr_number" in params
    assert params["scope_review_pr_number"].default == 294
    assert 330 in receipt.REVIEW_BINDINGS
