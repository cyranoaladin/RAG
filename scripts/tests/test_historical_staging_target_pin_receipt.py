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
    _run_pr_candidates_endpoint,
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
    physical = destination.stat()
    pin = {
        "kind": "NEXUS_STAGING_QUALIFIED_TARGET_PIN_V1",
        "content_anchor_sha256": ANCHOR,
        "release_id": "student-public-successor-fixture",
        "target_identity": f"docker:{CONTAINER}",
        "hostname": "staging", "host_machine_id_sha256": "2" * 64,
        "postgres_system_identifier": "12345678901234567890",
        "database_name": "nexus_rag", "destination_realpath": str(destination),
        "destination_device": physical.st_dev,
        "destination_inode": physical.st_ino,
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
        "head": {"sha": HEAD, "ref": "feature", "repo": {"full_name": "cyranoaladin/RAG"}},
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
        "head_branch": "feature",
        "head_repository": {"full_name": "cyranoaladin/RAG"},
        "repository": {"full_name": "cyranoaladin/RAG"},
        "pull_requests": [],
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
        destination_device=physical.st_dev, destination_inode=physical.st_ino,
    )
    candidate = {
        "number": 999, "created_at": "2026-10-10T17:00:00Z",
        "closed_at": "2026-10-10T18:05:00Z",
        "head": {"ref": "feature", "sha": HEAD,
                 "repo": {"full_name": "cyranoaladin/RAG"}},
        "base": {"ref": "main"},
    }
    return dict(
        receipt=receipt, pin_raw=raw, destination_root=destination,
        expected_pin_path="governance/staging_target_pins/target.json",
        observation=observation, expected_content_anchor_sha256=ANCHOR, now=NOW,
        pull_request=pr, review_decision=decision, trusted_status=status,
        workflow_run=run, workflow_attempt=attempt, head_tree_sha=TREE,
        merge_tree_sha=TREE, merge_parent_sha=BASE,
        reviewed_head_pin_blob=raw, main_pin_blob=raw,
        checkout_head_sha=MAIN, github_main_sha=MAIN, merge_is_ancestor=True,
        run_pr_candidates=[candidate],
    )


def test_postmerge_receipt_accepts_historical_base_not_current_pr_base(tmp_path: Path) -> None:
    evidence = fixture(tmp_path)
    evidence["run_pr_candidates"] = None  # issue_comment ne dépend pas du binding PR du rerun
    verdict = validate_historical_pin_receipt(**evidence)
    assert verdict["HISTORICAL_STAGING_TARGET_PIN_PASS"] is True
    assert verdict["EXPECTED_TARGET_PIN_SHA256"] == evidence["receipt"]["target_pin_sha256"]
    assert canonical_receipt(evidence["receipt"]).endswith(b"\n")


def test_postmerge_receipt_accepts_trusted_pull_request_target_rerun(tmp_path: Path) -> None:
    evidence = fixture(tmp_path)
    evidence["receipt"]["workflow_run_attempt"] = 2
    evidence["workflow_run"]["event"] = "pull_request_target"
    evidence["workflow_run"]["head_sha"] = HEAD
    evidence["workflow_run"]["run_attempt"] = 2
    evidence["workflow_attempt"]["event"] = "pull_request_target"
    evidence["workflow_attempt"]["head_sha"] = HEAD
    evidence["workflow_attempt"]["run_attempt"] = 2
    verdict = validate_historical_pin_receipt(**evidence)
    assert verdict["HISTORICAL_STAGING_TARGET_PIN_PASS"] is True


@pytest.mark.parametrize("part,key,value", [
    ("workflow_run", "event", "workflow_dispatch"),
    ("workflow_attempt", "event", "issue_comment"),
    ("workflow_run", "head_sha", BASE),
    ("workflow_attempt", "head_sha", BASE),
    ("receipt", "base_sha", "0" * 40),
    ("workflow_run", "id", 124),
    ("workflow_attempt", "id", 124),
    ("workflow_run", "run_attempt", 3),
    ("workflow_run", "name", "Different workflow"),
    ("workflow_run", "path", ".github/workflows/other.yml"),
    ("workflow_run", "created_at", "2026-10-10T18:04:00Z"),
    ("workflow_run", "head_branch", "other-branch"),
    ("workflow_run", "head_repository", {"full_name": "other/repo"}),
    ("workflow_run", "pull_requests", [{"number": 998}]),
    ("workflow_attempt", "run_started_at", "2026-10-10T17:59:00Z"),
])
def test_postmerge_rerun_sabotage_refused(
    tmp_path: Path, part: str, key: str, value: object,
) -> None:
    evidence = fixture(tmp_path)
    evidence["receipt"]["workflow_run_attempt"] = 2
    evidence["workflow_run"]["event"] = "pull_request_target"
    evidence["workflow_run"]["head_sha"] = HEAD
    evidence["workflow_run"]["run_attempt"] = 2
    evidence["workflow_attempt"]["event"] = "pull_request_target"
    evidence["workflow_attempt"]["head_sha"] = HEAD
    evidence["workflow_attempt"]["run_attempt"] = 2
    evidence[part][key] = value
    with pytest.raises(HistoricalPinRefused):
        validate_historical_pin_receipt(**evidence)


@pytest.mark.parametrize("candidate_change", [
    "missing", "other_pr_same_head", "other_pr_same_branch_different_head",
    "other_branch_same_head",
    "wrong_number", "wrong_head", "missing_page", "created_after_run",
    "closed_before_run", "full_page",
])
def test_rerun_requires_unique_active_pr_on_same_branch(
    tmp_path: Path, candidate_change: str,
) -> None:
    evidence = fixture(tmp_path)
    evidence["workflow_run"]["event"] = "pull_request_target"
    evidence["workflow_run"]["head_sha"] = HEAD
    evidence["workflow_attempt"]["event"] = "pull_request_target"
    evidence["workflow_attempt"]["head_sha"] = HEAD
    candidate = evidence["run_pr_candidates"][0]
    if candidate_change == "missing":
        evidence["run_pr_candidates"] = []
    elif candidate_change == "other_pr_same_head":
        evidence["run_pr_candidates"].append({**candidate, "number": 998})
    elif candidate_change == "other_pr_same_branch_different_head":
        evidence["run_pr_candidates"].append({
            **candidate, "number": 998,
            "head": {**candidate["head"], "sha": BASE},
        })
    elif candidate_change == "other_branch_same_head":
        candidate["head"] = {**candidate["head"], "ref": "other-branch"}
    elif candidate_change == "wrong_number":
        candidate["number"] = 998
    elif candidate_change == "wrong_head":
        candidate["head"] = {**candidate["head"], "sha": BASE}
    elif candidate_change == "missing_page":
        evidence["run_pr_candidates"] = None
    elif candidate_change == "created_after_run":
        candidate["created_at"] = "2026-10-10T18:02:00Z"
    elif candidate_change == "closed_before_run":
        candidate["closed_at"] = "2026-10-10T18:00:00Z"
    elif candidate_change == "full_page":
        evidence["run_pr_candidates"] = [candidate] * 100
    with pytest.raises(HistoricalPinRefused):
        validate_historical_pin_receipt(**evidence)


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
    ("merge_parent_sha", "0" * 40),
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


@pytest.mark.parametrize("b2_empty_commit", [False, True])
@pytest.mark.parametrize("event", ["issue_comment", "pull_request_target"])
def test_historical_replay_reads_live_github_and_main_blob(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, b2_empty_commit: bool,
    event: str,
) -> None:
    evidence = fixture(tmp_path)
    root = tmp_path / "repo"
    pin_path = Path("governance/staging_target_pins/target.json")
    root.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    commit = ["git", "-C", str(root), "-c", "user.name=Fixture",
              "-c", "user.email=fixture@example.invalid", "commit", "-qm"]
    (root / "README").write_text("base\n")
    subprocess.run(["git", "-C", str(root), "add", "README"], check=True)
    subprocess.run([*commit, "approved base"], check=True)
    base = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(root), "checkout", "-qb", "feature"], check=True)
    (root / pin_path).parent.mkdir(parents=True)
    (root / pin_path).write_bytes(evidence["pin_raw"])
    subprocess.run(["git", "-C", str(root), "add", str(pin_path)], check=True)
    subprocess.run([*commit, "approved head"], check=True)
    head = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "main"], check=True)
    if b2_empty_commit:
        subprocess.run([*commit, "B2 empty base", "--allow-empty"], check=True)
    subprocess.run(["git", "-C", str(root), "checkout", "-q", "feature", "--", str(pin_path)], check=True)
    subprocess.run([*commit, "squash merge"], check=True)
    merge = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    merge_parent = subprocess.check_output(
        ["git", "-C", str(root), "rev-parse", "HEAD^"], text=True,
    ).strip()
    subprocess.run([*commit, "main advanced", "--allow-empty"], check=True)
    main_sha = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    pr = evidence["pull_request"]
    pr["head"]["sha"] = head
    pr["merge_commit_sha"] = merge
    run = evidence["workflow_run"]
    status = evidence["trusted_status"]
    attempt = evidence["workflow_attempt"]
    decision = evidence["review_decision"]
    candidate = evidence["run_pr_candidates"][0]
    candidate["head"]["sha"] = head
    run["event"] = event
    attempt["event"] = event
    run["head_sha"] = base if event == "issue_comment" else head
    attempt["head_sha"] = base if event == "issue_comment" else head
    if event == "pull_request_target":
        run["run_attempt"] = 2
        attempt["run_attempt"] = 2
    decision["base_sha"] = base
    decision["head_sha"] = head
    from trusted_human_review import build_challenge  # noqa: PLC0415

    decision["challenge"] = build_challenge({
        "protocol": "NEXUS-TRUSTED-REVIEW-V1", "repository": "cyranoaladin/RAG",
        "pull_request": 999, "base_ref": "main", "base_sha": base,
        "head_sha": head, "author": "nexus-agent", "reviewer": "abenrhouma",
    })
    by_endpoint = {
        "repos/cyranoaladin/RAG/pulls/999": pr,
        f"repos/cyranoaladin/RAG/commits/{head}/status": {"statuses": [status]},
        "repos/cyranoaladin/RAG/actions/runs/123": run,
        f"repos/cyranoaladin/RAG/actions/runs/123/attempts/{run['run_attempt']}": attempt,
        "repos/cyranoaladin/RAG/branches/main": {"commit": {"sha": main_sha}},
        _run_pr_candidates_endpoint("feature"): [candidate],
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
    from trusted_human_review import evaluate_trusted_review  # noqa: PLC0415

    def replay(*, pull_request: dict[str, object], config: object, **_: object) -> object:
        assert pull_request["state"] == "open"
        assert pull_request["base"]["sha"] == merge_parent
        assert pr["base"]["sha"] != merge_parent
        from types import SimpleNamespace  # noqa: PLC0415

        review = {
            "id": 42, "state": "APPROVED", "body": decision["challenge"],
            "commit_id": head, "submitted_at": decision["submitted_at"],
            "user": {"login": "abenrhouma"},
        }
        verdict = evaluate_trusted_review(
            pull_request=pull_request, reviews=[review],
            permissions={"abenrhouma": {"permission": "write", "role_name": "write"}},
            config=config, reviews_complete=True,
        )
        return SimpleNamespace(decision=verdict)

    monkeypatch.setattr(github, "_evaluate_snapshot", replay)
    if b2_empty_commit:
        with pytest.raises(HistoricalPinRefused):
            build_historical_pin_receipt(
                root, pin_path, 999, ANCHOR, evidence["destination_root"], "unused-secret",
            )
        return
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
