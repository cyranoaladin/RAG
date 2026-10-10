"""L'approbation GitHub de #300 lie exactement le pack privé scellé."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from pr300_authority_receipt import (  # noqa: E402
    AuthorityReceiptError,
    PACK_FILES,
    validate_pr300_authority_receipt,
)


def _fixture(tmp_path: Path) -> tuple[dict, dict, dict, dict, str]:
    files = PACK_FILES
    digests = {}
    for key, relative in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key.encode())
        digests[key] = hashlib.sha256(key.encode()).hexdigest()
    head = "a" * 40
    base = "b" * 40
    merge = "c" * 40
    tree = "d" * 40
    challenge = "NEXUS-TRUSTED-REVIEW-V1:" + "e" * 64
    receipt = {
        "kind": "PR300_DELEGATED_STUDENT_RIGHTS_APPROVAL_V1",
        "repository": "cyranoaladin/RAG",
        "pull_request": 300,
        "base_sha": base,
        "head_sha": head,
        "head_tree_sha": tree,
        "merge_commit_sha": merge,
        "reviewer": "abenrhouma",
        "review_id": 17,
        "challenge": challenge,
        "files": files,
        "sha256": digests,
    }
    pr = {"number": 300, "merged": True,
          "merged_at": "2026-10-10T07:09:11Z", "base": {"sha": base},
          "head": {"sha": head}, "merge_commit_sha": merge}
    review = {"approved": True, "reason": "approved", "base_sha": base,
              "head_sha": head, "reviewer": "abenrhouma", "review_id": 17,
              "challenge": challenge, "submitted_at": "2026-10-10T07:06:54Z"}
    status = {"state": "success", "context": "trusted-human-review/head-pinned",
              "created_at": "2026-10-10T07:08:51Z"}
    return receipt, pr, review, status, tree


def test_approved_exact_head_and_pack_pass(tmp_path: Path):
    receipt, pr, review, status, tree = _fixture(tmp_path)
    result = validate_pr300_authority_receipt(
        tmp_path, receipt, pull_request=pr, review_decision=review,
        trusted_status=status, head_tree_sha=tree,
    )
    assert result["PR300_AUTHORITY_APPROVAL_PASS"] is True


@pytest.mark.parametrize("mutation", [
    "unapproved", "stale_head", "wrong_reviewer", "failed_status",
    "altered_sheet", "wrong_tree", "wrong_merge", "late_review", "late_status",
])
def test_pr300_authority_fails_closed(tmp_path: Path, mutation: str):
    receipt, pr, review, status, tree = _fixture(tmp_path)
    if mutation == "unapproved":
        review["approved"] = False
    elif mutation == "stale_head":
        review["head_sha"] = "f" * 40
    elif mutation == "wrong_reviewer":
        review["reviewer"] = "someone-else"
    elif mutation == "failed_status":
        status["state"] = "failure"
    elif mutation == "altered_sheet":
        (tmp_path / receipt["files"]["decision_sheet"]).write_text("tampered")
    elif mutation == "wrong_tree":
        tree = "f" * 40
    elif mutation == "wrong_merge":
        pr["merge_commit_sha"] = "f" * 40
    elif mutation == "late_review":
        review["submitted_at"] = "2026-10-10T07:10:00Z"
    elif mutation == "late_status":
        status["created_at"] = "2026-10-10T07:10:00Z"
    with pytest.raises(AuthorityReceiptError):
        validate_pr300_authority_receipt(
            tmp_path, receipt, pull_request=pr, review_decision=review,
            trusted_status=status, head_tree_sha=tree,
        )
