"""Sabotages du reçu LOT42 après fusion, sans accès GitHub réel."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))

from historical_lot42_review_receipt import (
    HistoricalLot42Refused,
    validate_historical_lot42_receipt,
)
from trusted_human_review import build_challenge


def _case() -> tuple[dict, dict]:
    raw = b"{\"review_id\":\"lot42-test\"}\n"
    digest = hashlib.sha256(raw).hexdigest()
    blob = hashlib.sha1(f"blob {len(raw)}\0".encode() + raw).hexdigest()
    challenge = build_challenge({
        "protocol": "NEXUS-TRUSTED-REVIEW-V1", "repository": "cyranoaladin/RAG",
        "pull_request": 444, "base_ref": "main", "base_sha": "a" * 40,
        "head_sha": "b" * 40, "author": "operator", "reviewer": "abenrhouma",
    })
    receipt = {
        "kind": "NEXUS_LOT42_MERGED_REVIEW_RECEIPT_V1",
        "repository": "cyranoaladin/RAG", "pull_request": 444,
        "base_sha": "a" * 40, "head_sha": "b" * 40,
        "head_tree_sha": "c" * 40, "merge_commit_sha": "e" * 40,
        "author": "operator", "reviewer": "abenrhouma",
        "review_id": 123, "challenge": challenge,
        "review_submitted_at": "2026-10-12T10:00:00Z",
        "trusted_status_context": "trusted-human-review/head-pinned",
        "trusted_status_created_at": "2026-10-12T10:02:00Z",
        "trusted_status_target_url": "https://github.com/cyranoaladin/RAG/actions/runs/333",
        "workflow_run_id": 333, "workflow_run_attempt": 1,
        "review_artifact_path": f"governance/publication-reviews/lot42-test-{digest}.json",
        "review_artifact_sha256": digest,
        "review_artifact_blob_sha1": blob,
    }
    evidence = {
        "pull_request": {
            "number": 444, "state": "closed", "merged": True,
            "merge_commit_sha": "e" * 40,
            "merged_at": "2026-10-12T10:04:00Z",
            "head": {"sha": "b" * 40, "repo": {"full_name": "cyranoaladin/RAG"}},
            "base": {"ref": "main"}, "user": {"login": "operator"},
        },
        "review_decision": {
            "approved": True, "reason": "approved",
            "repository": "cyranoaladin/RAG", "pull_request": 444,
            "base_sha": "a" * 40, "head_sha": "b" * 40,
            "reviewer": "abenrhouma", "review_id": 123,
            "challenge": challenge,
            "submitted_at": "2026-10-12T10:00:00Z",
        },
        "trusted_status": {
            "context": "trusted-human-review/head-pinned", "state": "success",
            "created_at": "2026-10-12T10:02:00Z",
            "target_url": "https://github.com/cyranoaladin/RAG/actions/runs/333",
        },
        "workflow_run": {
            "id": 333, "run_attempt": 1, "event": "issue_comment",
            "name": "Trusted human review",
            "path": ".github/workflows/trusted-human-review.yml",
            "head_sha": "a" * 40, "status": "completed", "conclusion": "success",
            "created_at": "2026-10-12T10:00:30Z",
        },
        "workflow_attempt": {
            "id": 333, "run_attempt": 1, "event": "issue_comment",
            "head_sha": "a" * 40, "status": "completed", "conclusion": "success",
            "run_started_at": "2026-10-12T10:01:00Z",
            "updated_at": "2026-10-12T10:03:00Z",
        },
        "head_tree_sha": "c" * 40, "merge_tree_sha": "c" * 40,
        "merge_parent_sha": "a" * 40, "checkout_head_sha": "f" * 40,
        "github_main_sha": "f" * 40, "merge_is_ancestor": True,
        "reviewed_head_blob": raw, "main_blob": raw,
    }
    return receipt, evidence


def test_historical_lot42_receipt_requires_exact_merged_review_and_blob() -> None:
    receipt, evidence = _case()
    assert validate_historical_lot42_receipt(receipt, **evidence) == (
        receipt["base_sha"], receipt["head_sha"], receipt["head_tree_sha"],
        receipt["review_id"], receipt["challenge"], receipt["reviewer"],
    )
    for name, change in (
        ("blob", {"reviewed_head_blob": b"substituted"}),
        ("tree", {"merge_tree_sha": "0" * 40}),
        ("head", {"review_decision": {**evidence["review_decision"], "head_sha": "0" * 40}}),
        ("review", {"review_decision": {**evidence["review_decision"], "approved": False}}),
        ("status", {"trusted_status": {**evidence["trusted_status"], "state": "failure"}}),
        ("merge", {"pull_request": {**evidence["pull_request"], "merged": False}}),
        ("ancestor", {"merge_is_ancestor": False}),
        ("challenge", {"review_decision": {**evidence["review_decision"], "challenge": "wrong"}}),
        ("attempt", {"workflow_attempt": {**evidence["workflow_attempt"], "run_attempt": 2}}),
    ):
        with pytest.raises(HistoricalLot42Refused):
            validate_historical_lot42_receipt(receipt, **{**evidence, **change})


def test_historical_lot42_ignores_later_failed_rerun_but_not_forged_attempt() -> None:
    receipt, evidence = _case()
    evidence["workflow_run"] = {
        **evidence["workflow_run"], "run_attempt": 2,
        "status": "completed", "conclusion": "failure",
    }
    assert validate_historical_lot42_receipt(receipt, **evidence)[3] == 123
    receipt["workflow_run_attempt"] = 2
    with pytest.raises(HistoricalLot42Refused):
        validate_historical_lot42_receipt(receipt, **evidence)
