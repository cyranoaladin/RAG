"""Un pin approuvé avant fusion doit rester opposable après fusion sans PR OPEN."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "go_live"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "github"))
from historical_staging_target_pin_receipt import (  # noqa: E402
    HistoricalPinRefused,
    build_historical_pin_receipt,
    canonical_receipt,
    check_historical_pin_receipt,
    validate_historical_pin_receipt,
)
from independent_staging_target_pin import LiveTargetObservation, canonical  # noqa: E402


NOW = datetime(2026, 10, 10, 20, 0, tzinfo=UTC)
BASE = "a" * 40
HEAD = "b" * 40
TREE = "c" * 40
MERGE = "d" * 40
MAIN = "e" * 40
ANCHOR = "f" * 64
CONTAINER = "1" * 64
PIN_SHA = ""
CHALLENGE = ""


def fixture(tmp_path: Path) -> dict[str, object]:
    from trusted_human_review import build_challenge  # noqa: PLC0415

    destination = tmp_path / "destination"
    destination.mkdir()
    pin = {
        "kind": "NEXUS_STAGING_QUALIFIED_TARGET_PIN_V1",
        "content_anchor_sha256": ANCHOR,
        "release_id": "student-public-successor-fixture",
        "target_identity": f"docker:{CONTAINER}",
        "hostname": "staging", "host_machine_id_sha256": "2" * 64,
        "postgres_system_identifier": "12345678901234567890",
        "database_name": "nexus_rag", "destination_realpath": str(destination),
        "pinned_at_utc": (NOW - timedelta(hours=2, minutes=10)).isoformat().replace("+00:00", "Z"),
        "expires_at_utc": (NOW + timedelta(hours=2)).isoformat().replace("+00:00", "Z"),
    }
    raw = canonical(pin)
    pin_sha = hashlib.sha256(raw).hexdigest()
    challenge = build_challenge({
        "protocol": "NEXUS-TRUSTED-REVIEW-V1", "repository": "cyranoaladin/RAG",
        "pull_request": 999, "base_ref": "main", "base_sha": BASE,
        "head_sha": HEAD, "author": "nexus-agent", "reviewer": "abenrhouma",
    })
    receipt = {
        "kind": "NEXUS_STAGING_TARGET_PIN_MERGED_REVIEW_RECEIPT_V1",
        "status": "APPROVED_PIN_NOT_PUBLICATION_AUTHORITY",
        "repository": "cyranoaladin/RAG", "pull_request": 999,
        "base_ref": "main", "base_sha": BASE, "head_sha": HEAD,
        "head_tree_sha": TREE, "merge_commit_sha": MERGE,
        "author": "nexus-agent", "reviewer": "abenrhouma",
        "review_id": 42, "challenge": challenge,
        "review_submitted_at": "2026-10-10T18:00:00Z",
        "trusted_status_context": "trusted-human-review/head-pinned",
        "trusted_status_created_at": "2026-10-10T18:02:00Z",
        "trusted_status_target_url": "https://github.com/cyranoaladin/RAG/actions/runs/123",
        "workflow_run_id": 123, "workflow_run_attempt": 1,
        "content_anchor_sha256": ANCHOR,
        "target_pin_path": "governance/staging_target_pins/target.json",
        "target_pin_sha256": pin_sha,
    }
    pr = {
        "number": 999, "state": "closed", "merged": True,
        "merged_at": "2026-10-10T18:05:00Z", "merge_commit_sha": MERGE,
        "base": {"ref": "main", "sha": "9" * 40},
        "head": {"sha": HEAD, "repo": {"full_name": "cyranoaladin/RAG"}},
        "user": {"login": "nexus-agent"},
    }
    decision = {
        "approved": True, "reason": "approved", "repository": "cyranoaladin/RAG",
        "pull_request": 999, "base_sha": BASE, "head_sha": HEAD,
        "reviewer": "abenrhouma", "review_id": 42, "challenge": challenge,
        "submitted_at": "2026-10-10T18:00:00Z",
    }
    status = {
        "context": "trusted-human-review/head-pinned", "state": "success",
        "created_at": "2026-10-10T18:02:00Z",
        "target_url": "https://github.com/cyranoaladin/RAG/actions/runs/123",
    }
    run = {
        "id": 123, "run_attempt": 1, "name": "Trusted human review",
        "path": ".github/workflows/trusted-human-review.yml",
        "event": "issue_comment", "head_sha": BASE,
        "status": "completed", "conclusion": "success",
        "created_at": "2026-10-10T18:01:00Z",
    }
    attempt = {
        "id": 123, "run_attempt": 1, "event": "issue_comment",
        "head_sha": BASE, "status": "completed", "conclusion": "success",
        "run_started_at": "2026-10-10T18:01:00Z",
        "updated_at": "2026-10-10T18:03:00Z",
    }
    observation = LiveTargetObservation(
        hostname="staging", host_machine_id_sha256="2" * 64,
        container_id=CONTAINER, postgres_system_identifier="12345678901234567890",
        database_name="nexus_rag", destination_realpath=str(destination),
    )
    return dict(
        receipt=receipt, pin_raw=raw, destination_root=destination,
        expected_pin_path="governance/staging_target_pins/target.json",
        observation=observation, expected_content_anchor_sha256=ANCHOR, now=NOW,
        pull_request=pr, review_decision=decision, trusted_status=status,
        workflow_run=run, workflow_attempt=attempt, head_tree_sha=TREE,
        merge_tree_sha=TREE, reviewed_head_pin_blob=raw, main_pin_blob=raw,
        checkout_head_sha=MAIN, github_main_sha=MAIN, merge_is_ancestor=True,
    )


def test_postmerge_receipt_accepts_historical_base_not_current_pr_base(tmp_path: Path) -> None:
    evidence = fixture(tmp_path)
    verdict = validate_historical_pin_receipt(**evidence)
    assert verdict["HISTORICAL_STAGING_TARGET_PIN_PASS"] is True
    assert verdict["EXPECTED_TARGET_PIN_SHA256"] == evidence["receipt"]["target_pin_sha256"]
    assert canonical_receipt(evidence["receipt"]).endswith(b"\n")


@pytest.mark.parametrize("part,key,value", [
    ("receipt", "base_sha", "0" * 40),
    ("receipt", "head_sha", "0" * 40),
    ("receipt", "head_tree_sha", "0" * 40),
    ("receipt", "merge_commit_sha", "0" * 40),
    ("receipt", "review_id", 43),
    ("receipt", "challenge", "stale"),
    ("receipt", "target_pin_sha256", "0" * 64),
    ("pull_request", "merge_commit_sha", "0" * 40),
    ("review_decision", "approved", False),
    ("review_decision", "review_id", 43),
    ("trusted_status", "state", "failure"),
    ("workflow_run", "head_sha", "0" * 40),
    ("workflow_attempt", "conclusion", "failure"),
])
def test_receipt_sabotage_refused(tmp_path: Path, part: str, key: str, value: object) -> None:
    evidence = fixture(tmp_path)
    evidence[part][key] = value
    with pytest.raises(HistoricalPinRefused):
        validate_historical_pin_receipt(**evidence)


@pytest.mark.parametrize("key,value", [
    ("reviewed_head_pin_blob", b"changed reviewed blob"),
    ("main_pin_blob", b"changed main blob"),
    ("merge_tree_sha", "0" * 40),
    ("github_main_sha", "0" * 40),
    ("merge_is_ancestor", False),
])
def test_repository_binding_sabotage_refused(tmp_path: Path, key: str, value: object) -> None:
    evidence = fixture(tmp_path)
    evidence[key] = value
    with pytest.raises(HistoricalPinRefused):
        validate_historical_pin_receipt(**evidence)


def test_expired_pin_refused_even_with_valid_historical_review(tmp_path: Path) -> None:
    evidence = fixture(tmp_path)
    evidence["now"] = NOW + timedelta(hours=3)
    with pytest.raises(HistoricalPinRefused):
        validate_historical_pin_receipt(**evidence)


def test_receipt_canonicalization_refuses_manual_row_edit(tmp_path: Path) -> None:
    evidence = fixture(tmp_path)
    raw = canonical_receipt(evidence["receipt"])
    assert json.loads(raw)["target_pin_sha256"] == evidence["receipt"]["target_pin_sha256"]
    evidence["receipt"]["target_pin_path"] = "governance/staging_target_pins/other.json"
    with pytest.raises(HistoricalPinRefused):
        validate_historical_pin_receipt(**evidence)


def test_historical_replay_reads_live_github_and_main_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence = fixture(tmp_path)
    root = tmp_path / "repo"
    pin_path = Path("governance/staging_target_pins/target.json")
    (root / pin_path).parent.mkdir(parents=True)
    (root / pin_path).write_bytes(evidence["pin_raw"])
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", str(pin_path)], check=True)
    commit = ["git", "-C", str(root), "-c", "user.name=Fixture",
              "-c", "user.email=fixture@example.invalid", "commit", "-qm"]
    subprocess.run([*commit, "approved head"], check=True)
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run([*commit, "merged tree", "--allow-empty"], check=True)
    merge = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run([*commit, "main advanced", "--allow-empty"], check=True)
    main_sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    pr = evidence["pull_request"]
    pr["head"]["sha"] = head
    pr["merge_commit_sha"] = merge
    run = evidence["workflow_run"]
    status = evidence["trusted_status"]
    attempt = evidence["workflow_attempt"]
    decision = evidence["review_decision"]
    decision["head_sha"] = head
    from trusted_human_review import build_challenge  # noqa: PLC0415

    decision["challenge"] = build_challenge({
        "protocol": "NEXUS-TRUSTED-REVIEW-V1", "repository": "cyranoaladin/RAG",
        "pull_request": 999, "base_ref": "main", "base_sha": BASE,
        "head_sha": head, "author": "nexus-agent", "reviewer": "abenrhouma",
    })
    by_endpoint = {
        "repos/cyranoaladin/RAG/pulls/999": pr,
        f"repos/cyranoaladin/RAG/commits/{head}/status": {"statuses": [status]},
        "repos/cyranoaladin/RAG/actions/runs/123": run,
        "repos/cyranoaladin/RAG/actions/runs/123/attempts/1": attempt,
        "repos/cyranoaladin/RAG/branches/main": {"commit": {"sha": main_sha}},
    }
    monkeypatch.setattr("historical_staging_target_pin_receipt._read_gh",
                        lambda endpoint: by_endpoint[endpoint])
    monkeypatch.setattr("historical_staging_target_pin_receipt.observe_live_target",
                        lambda **_: evidence["observation"])
    import historical_staging_target_pin_receipt as module  # noqa: PLC0415

    class FixedClock:
        @staticmethod
        def now(_: object) -> datetime:
            return NOW

    monkeypatch.setattr(module, "datetime", FixedClock)
    import trusted_human_review_github as github  # noqa: PLC0415
    from trusted_human_review import TrustedReviewDecision  # noqa: PLC0415

    def replay(*, pull_request: dict[str, object], **_: object) -> object:
        assert pull_request["state"] == "open"
        assert pull_request["base"]["sha"] == BASE
        assert pr["base"]["sha"] != BASE
        from types import SimpleNamespace  # noqa: PLC0415

        return SimpleNamespace(decision=TrustedReviewDecision(**decision))

    monkeypatch.setattr(github, "_evaluate_snapshot", replay)
    receipt = build_historical_pin_receipt(
        root, pin_path, 999, ANCHOR, evidence["destination_root"], "unused-secret",
    )
    assert receipt["head_sha"] == head
    assert receipt["merge_commit_sha"] == merge
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_bytes(canonical_receipt(receipt))
    assert check_historical_pin_receipt(
        root, receipt_path, pin_path, 999, ANCHOR,
        evidence["destination_root"], "unused-secret",
    )["HISTORICAL_STAGING_TARGET_PIN_PASS"] is True
