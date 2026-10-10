"""La revue exacte de #312 lie le candidat textuel entier, sans l'activer."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))

from pr312_authority_receipt import (
    EXPECTED_COUNTS,
    PACK_FILES,
    AuthorityReceiptError,
    _select_trusted_status_at_merge,
    _validate_trusted_workflow_attempt,
    require_pack_matches_approved_tree,
    validate_pr312_authority_receipt,
)

REPO = Path(__file__).resolve().parents[2]
BASE = "2b1f3b04cf84defc7f828da6f3362df7677e8ca3"
HEAD = "6eab012c0c763fe73302c3a40e9646c42b5d213f"
MERGE = "fc6b7da6254eb67e7a2b26ec555b5edf17316a96"
TREE = "93e9f382fb12bd49ee3489056e0536f4d66c1976"
CHALLENGE = "NEXUS-TRUSTED-REVIEW-V1:10981a19e1424efca1e40e9697b3b3a00cf406e75ad06d8284277cfa5d86da8e"


def _fixture(tmp_path: Path) -> tuple[dict, dict, dict, dict]:
    digests = {}
    for label, relative in PACK_FILES.items():
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / relative, target)
        digests[label] = hashlib.sha256(target.read_bytes()).hexdigest()
    receipt = {
        "kind": "PR312_STUDENT_PUBLIC_CANDIDATE_APPROVAL_V1",
        "repository": "cyranoaladin/RAG", "pull_request": 312,
        "base_sha": BASE, "head_sha": HEAD, "head_tree_sha": TREE,
        "merge_commit_sha": MERGE, "reviewer": "abenrhouma",
        "review_id": 5479062236, "challenge": CHALLENGE,
        "release_id": "student-public-20261010-v1-eb39f6cd0423e184",
        "expected_counts": EXPECTED_COUNTS,
        "files": PACK_FILES, "sha256": digests,
    }
    pr = {"number": 312, "merged": True, "state": "closed",
          "merged_at": "2026-10-10T13:13:43Z", "base": {"sha": BASE},
          "head": {"sha": HEAD}, "merge_commit_sha": MERGE}
    review = {"approved": True, "reason": "approved", "base_sha": BASE,
              "head_sha": HEAD, "reviewer": "abenrhouma",
              "review_id": 5479062236, "challenge": CHALLENGE,
              "submitted_at": "2026-10-10T13:11:44Z"}
    status = {"context": "trusted-human-review/head-pinned", "state": "success",
              "created_at": "2026-10-10T13:12:57Z",
              "target_url": "https://github.com/cyranoaladin/RAG/actions/runs/38048845833"}
    return receipt, pr, review, status


def test_exact_head_review_binds_full_candidate_without_activation(tmp_path: Path) -> None:
    receipt, pr, review, status = _fixture(tmp_path)
    result = validate_pr312_authority_receipt(
        tmp_path, receipt, pull_request=pr, review_decision=review,
        trusted_status=status, head_tree_sha=TREE,
    )
    assert result["PR312_AUTHORITY_APPROVAL_PASS"] is True
    assert result["AGGREGATE_SHA256"] == receipt["sha256"]["aggregate"]
    assert result["EXPECTED_COUNTS"] == EXPECTED_COUNTS
    assert result["CANDIDATE_ACTIVATION_ALLOWED"] is False


@pytest.mark.parametrize("mutation", [
    "unapproved", "stale_head", "wrong_reviewer", "wrong_challenge",
    "failed_status", "post_merge_status", "post_merge_review", "wrong_tree",
    "wrong_merge", "changed_aggregate", "changed_subject", "changed_registry",
    "omitted_subject", "extra_file", "changed_counts", "claim_activation",
])
def test_exact_head_receipt_fails_closed(tmp_path: Path, mutation: str) -> None:
    receipt, pr, review, status = _fixture(tmp_path)
    tree = TREE
    if mutation == "unapproved":
        review["approved"] = False
    elif mutation == "stale_head":
        review["head_sha"] = "f" * 40
    elif mutation == "wrong_reviewer":
        review["reviewer"] = "someone-else"
    elif mutation == "wrong_challenge":
        review["challenge"] = "NEXUS-TRUSTED-REVIEW-V1:" + "f" * 64
    elif mutation == "failed_status":
        status["state"] = "failure"
    elif mutation == "post_merge_status":
        status["created_at"] = "2026-10-10T13:14:00Z"
    elif mutation == "post_merge_review":
        review["submitted_at"] = "2026-10-10T13:14:00Z"
    elif mutation == "wrong_tree":
        tree = "f" * 40
    elif mutation == "wrong_merge":
        pr["merge_commit_sha"] = "f" * 40
    elif mutation == "changed_aggregate":
        (tmp_path / PACK_FILES["aggregate"]).write_bytes(b"changed")
    elif mutation == "changed_subject":
        (tmp_path / PACK_FILES["subject_ses_premiere_specialite"]).write_bytes(b"changed")
    elif mutation == "changed_registry":
        (tmp_path / PACK_FILES["artifacts"]).write_bytes(b"changed")
    elif mutation == "omitted_subject":
        receipt["sha256"].pop("subject_ses_premiere_specialite")
    elif mutation == "extra_file":
        receipt["files"] = {**receipt["files"], "unknown": "unknown.json"}
    elif mutation == "changed_counts":
        receipt["expected_counts"] = {**EXPECTED_COUNTS, "placements": 479}
    elif mutation == "claim_activation":
        aggregate_path = tmp_path / PACK_FILES["aggregate"]
        aggregate = json.loads(aggregate_path.read_bytes())
        aggregate["release_mode"] = "production"
        aggregate_path.write_text(json.dumps(aggregate))
        receipt["sha256"]["aggregate"] = hashlib.sha256(aggregate_path.read_bytes()).hexdigest()
    with pytest.raises(AuthorityReceiptError):
        validate_pr312_authority_receipt(
            tmp_path, receipt, pull_request=pr, review_decision=review,
            trusted_status=status, head_tree_sha=tree,
        )


def test_status_selection_uses_last_premerge_result() -> None:
    before = {"context": "trusted-human-review/head-pinned", "state": "success",
              "created_at": "2026-10-10T13:12:57Z"}
    after = {**before, "state": "failure", "created_at": "2026-10-10T13:14:00Z"}
    assert _select_trusted_status_at_merge(
        [after, before], "2026-10-10T13:13:43Z",
    ) == before


@pytest.mark.parametrize("mutation", [
    "wrong_event", "wrong_head", "wrong_path", "wrong_run_id",
    "wrong_attempt_window", "failed_run",
])
def test_trusted_workflow_attempt_is_exact_and_premerge(mutation: str) -> None:
    status = {"context": "trusted-human-review/head-pinned", "state": "success",
              "created_at": "2026-10-10T13:12:57Z",
              "target_url": "https://github.com/cyranoaladin/RAG/actions/runs/38048845833"}
    run = {"id": 38048845833, "name": "Trusted human review",
           "path": ".github/workflows/trusted-human-review.yml",
           "event": "pull_request_target", "status": "completed", "conclusion": "success",
           "head_sha": HEAD, "run_attempt": 2}
    attempt = {"id": 38048845833, "run_attempt": 2,
               "event": "pull_request_target", "head_sha": HEAD,
               "status": "completed", "conclusion": "success",
               "run_started_at": "2026-10-10T13:12:37Z",
               "updated_at": "2026-10-10T13:13:01Z"}
    if mutation == "wrong_event":
        run["event"] = "issue_comment"
    elif mutation == "wrong_head":
        run["head_sha"] = "f" * 40
    elif mutation == "wrong_path":
        run["path"] = ".github/workflows/other.yml"
    elif mutation == "wrong_run_id":
        attempt["id"] = 1
    elif mutation == "wrong_attempt_window":
        attempt["run_started_at"] = "2026-10-10T13:13:30Z"
    elif mutation == "failed_run":
        attempt["conclusion"] = "failure"
    with pytest.raises(AuthorityReceiptError):
        _validate_trusted_workflow_attempt(
            status, run, attempt, expected_head_sha=HEAD,
            review_submitted_at="2026-10-10T13:11:44Z",
            merged_at="2026-10-10T13:13:43Z",
        )


def test_later_file_substitution_cannot_borrow_approved_head(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    candidate = tmp_path / "candidate.json"
    candidate.write_text('{"approved": true}\n')
    subprocess.run(["git", "add", "candidate.json"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
         "commit", "-qm", "Add approved candidate"], cwd=tmp_path, check=True,
    )
    approved_head = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=tmp_path, text=True,
    ).strip()
    require_pack_matches_approved_tree(
        tmp_path, approved_head, {"candidate": "candidate.json"},
    )
    candidate.write_text('{"approved": false}\n')
    with pytest.raises(AuthorityReceiptError, match="APPROVED_HEAD"):
        require_pack_matches_approved_tree(
            tmp_path, approved_head, {"candidate": "candidate.json"},
        )
