#!/usr/bin/env python3
"""Rejouer après fusion la review exacte du reçu LOT42 public.

Le reçu n'est qu'un pointeur : GitHub, Git et le blob revu sont relus. Le
rapprochement des 377 attestations DB appartient ensuite au fournisseur C.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import quote

from nexus_contracts.authority_artifacts import git_blob_sha1
from pr300_authority_receipt import (
    REPOSITORY,
    REVIEWER,
    STATUS_CONTEXT,
    TRUSTED_WORKFLOW_PATH,
    _git,
    _read_gh,
    _select_trusted_status_at_merge,
    _utc,
)

GITHUB_DIR = Path(__file__).resolve().parents[1] / "github"
if str(GITHUB_DIR) not in sys.path:
    sys.path.insert(0, str(GITHUB_DIR))
from trusted_human_review import build_challenge

KIND = "NEXUS_LOT42_MERGED_REVIEW_RECEIPT_V1"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
RUN_URL = re.compile(r"https://github\.com/cyranoaladin/RAG/actions/runs/([1-9][0-9]*)\Z")
FIELDS = frozenset({
    "kind", "repository", "pull_request", "base_sha", "head_sha",
    "head_tree_sha", "merge_commit_sha", "author", "reviewer",
    "review_id", "challenge", "review_submitted_at", "trusted_status_context",
    "trusted_status_created_at", "trusted_status_target_url",
    "workflow_run_id", "workflow_run_attempt", "review_artifact_path",
    "review_artifact_sha256", "review_artifact_blob_sha1",
})


class HistoricalLot42Refused(ValueError):
    """Le reçu historique ne concorde pas avec la review et le blob relus."""


def canonical_receipt(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _artifact_path(value: object, digest: object) -> str:
    if (not isinstance(value, str) or not isinstance(digest, str)
            or SHA64.fullmatch(digest) is None):
        raise HistoricalLot42Refused("LOT42 artifact path/digest absent")
    path = Path(value)
    if (path.is_absolute() or ".." in path.parts
            or path.parent != Path("governance/publication-reviews")
            or not path.name.endswith(f"-{digest}.json")):
        raise HistoricalLot42Refused("LOT42 artifact outside governed directory")
    return value


def validate_historical_lot42_receipt(
    receipt: Mapping[str, object], *, pull_request: Mapping[str, Any],
    review_decision: Mapping[str, Any], trusted_status: Mapping[str, Any],
    workflow_run: Mapping[str, Any], workflow_attempt: Mapping[str, Any],
    head_tree_sha: str, merge_tree_sha: str, merge_parent_sha: str,
    checkout_head_sha: str, github_main_sha: str, merge_is_ancestor: bool,
    reviewed_head_blob: bytes, main_blob: bytes,
    run_pr_candidates: object = None,
) -> tuple[str, str, str, int, str, str]:
    """Valider indépendamment le HEAD, challenge, run trusted et blob LOT42."""
    r = receipt
    if (set(r) != FIELDS or r.get("kind") != KIND
            or r.get("repository") != REPOSITORY or r.get("reviewer") != REVIEWER
            or type(r.get("pull_request")) is not int or r["pull_request"] <= 0
            or type(r.get("review_id")) is not int or r["review_id"] <= 0
            or type(r.get("workflow_run_id")) is not int or r["workflow_run_id"] <= 0
            or type(r.get("workflow_run_attempt")) is not int
            or r["workflow_run_attempt"] <= 0
            or any(not isinstance(r.get(key), str) or SHA40.fullmatch(r[key]) is None
                   for key in ("base_sha", "head_sha", "head_tree_sha", "merge_commit_sha",
                               "review_artifact_blob_sha1"))
            or not isinstance(r.get("review_artifact_sha256"), str)
            or SHA64.fullmatch(r["review_artifact_sha256"]) is None
            or not isinstance(r.get("author"), str) or not r["author"]):
        raise HistoricalLot42Refused("LOT42 historical receipt shape invalid")
    _artifact_path(r["review_artifact_path"], r["review_artifact_sha256"])
    expected_challenge = build_challenge({
        "protocol": "NEXUS-TRUSTED-REVIEW-V1", "repository": REPOSITORY,
        "pull_request": r["pull_request"], "base_ref": "main",
        "base_sha": r["base_sha"], "head_sha": r["head_sha"],
        "author": r["author"], "reviewer": REVIEWER,
    })
    if r.get("challenge") != expected_challenge:
        raise HistoricalLot42Refused("LOT42 exact-head challenge differs")
    if (not isinstance(reviewed_head_blob, bytes)
            or reviewed_head_blob != main_blob
            or hashlib.sha256(reviewed_head_blob).hexdigest() != r["review_artifact_sha256"]
            or git_blob_sha1(reviewed_head_blob) != r["review_artifact_blob_sha1"]
            or head_tree_sha != r["head_tree_sha"]
            or merge_tree_sha != head_tree_sha
            or merge_parent_sha != r["base_sha"]
            or checkout_head_sha != github_main_sha
            or SHA40.fullmatch(checkout_head_sha) is None
            or merge_is_ancestor is not True):
        raise HistoricalLot42Refused("LOT42 reviewed blob/tree/main differs")
    pr = pull_request
    base = pr.get("base")
    head = pr.get("head")
    user = pr.get("user")
    if (pr.get("number") != r["pull_request"] or pr.get("state") != "closed"
            or pr.get("merged") is not True
            or pr.get("merge_commit_sha") != r["merge_commit_sha"]
            or not isinstance(base, Mapping) or base.get("ref") != "main"
            or not isinstance(head, Mapping) or head.get("sha") != r["head_sha"]
            or not isinstance(head.get("repo"), Mapping)
            or head["repo"].get("full_name") != REPOSITORY
            or not isinstance(user, Mapping) or user.get("login") != r["author"]):
        raise HistoricalLot42Refused("LOT42 merged PR differs")
    decision = review_decision
    if (decision.get("approved") is not True or decision.get("reason") != "approved"
            or any(decision.get(key) != r[key] for key in (
                "repository", "pull_request", "base_sha", "head_sha",
                "reviewer", "review_id", "challenge",
            )) or decision.get("submitted_at") != r["review_submitted_at"]):
        raise HistoricalLot42Refused("LOT42 exact review absent")
    status = trusted_status
    run = workflow_run
    attempt = workflow_attempt
    event = run.get("event")
    expected_workflow_head = (
        r["base_sha"] if event == "issue_comment"
        else r["head_sha"] if event == "pull_request_target" else None
    )
    match = RUN_URL.fullmatch(str(r.get("trusted_status_target_url")))
    if (status.get("context") != r["trusted_status_context"] == STATUS_CONTEXT
            or status.get("state") != "success"
            or status.get("created_at") != r["trusted_status_created_at"]
            or status.get("target_url") != r["trusted_status_target_url"]
            or match is None or int(match.group(1)) != r["workflow_run_id"]
            or run.get("id") != r["workflow_run_id"]
            or type(run.get("run_attempt")) is not int
            or run["run_attempt"] < r["workflow_run_attempt"]
            or run.get("name") != "Trusted human review"
            or run.get("path") != TRUSTED_WORKFLOW_PATH
            or run.get("head_sha") != expected_workflow_head
            or attempt.get("id") != r["workflow_run_id"]
            or attempt.get("run_attempt") != r["workflow_run_attempt"]
            or attempt.get("event") != event
            or attempt.get("head_sha") != expected_workflow_head
            or attempt.get("status") != "completed"
            or attempt.get("conclusion") != "success"):
        raise HistoricalLot42Refused("LOT42 trusted workflow absent")
    if event == "pull_request_target":
        pr_head = pr.get("head")
        head_ref = pr_head.get("ref") if isinstance(pr_head, Mapping) else None
        if (not isinstance(head_ref, str) or not head_ref
                or run.get("head_branch") != head_ref
                or not isinstance(run_pr_candidates, list)
                or not run_pr_candidates or len(run_pr_candidates) >= 100):
            raise HistoricalLot42Refused("LOT42 trusted PR branch ambiguous")
        try:
            started = _utc(attempt["run_started_at"])
            active = [
                (candidate["number"], candidate["head"]["sha"])
                for candidate in run_pr_candidates
                if _utc(candidate["created_at"]) <= started
                and (candidate.get("closed_at") is None
                     or started <= _utc(candidate["closed_at"]))
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise HistoricalLot42Refused("LOT42 trusted PR candidates invalid") from error
        if active != [(r["pull_request"], r["head_sha"])]:
            raise HistoricalLot42Refused("LOT42 trusted PR not unique")
    try:
        reviewed = _utc(r["review_submitted_at"])
        started = _utc(attempt["run_started_at"])
        status_at = _utc(status["created_at"])
        finished = _utc(attempt["updated_at"])
        merged = _utc(pr["merged_at"])
        run_created = _utc(run["created_at"])
    except (KeyError, TypeError, ValueError) as error:
        raise HistoricalLot42Refused("LOT42 review/run chronology invalid") from error
    # A rerun keeps the original run's creation time. The successful attempt,
    # not that earlier creation, must have evaluated the approved review.
    if not run_created <= started or not reviewed <= started <= status_at <= finished <= merged:
        raise HistoricalLot42Refused("LOT42 review/run occurred after merge")
    return (
        str(r["base_sha"]), str(r["head_sha"]), str(r["head_tree_sha"]),
        int(r["review_id"]), str(r["challenge"]), REVIEWER,
    )


def _git_blob(root: Path, ref: str, relative: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{ref}:{relative}"],
        capture_output=True, check=False, timeout=20,
    )
    if result.returncode != 0:
        raise HistoricalLot42Refused("LOT42 reviewed Git blob unavailable")
    return result.stdout


def _live_evidence(
    root: Path, pull_request: int, artifact_path: str,
    *, expected_attempt: int | None = None,
) -> dict[str, Any]:
    """Relire GitHub et Git sans jamais se fier à l'état du reçu."""
    from trusted_human_review_github import (
        DEFAULT_CONFIG_PATH,
        _evaluate_snapshot,
        load_config,
        run_gh_api,
    )

    pr = _read_gh(f"repos/{REPOSITORY}/pulls/{pull_request}")
    if not isinstance(pr, dict) or pr.get("state") != "closed" or pr.get("merged") is not True:
        raise HistoricalLot42Refused("LOT42 PR not merged")
    head = pr.get("head", {}).get("sha")
    merge = pr.get("merge_commit_sha")
    if (not isinstance(head, str) or SHA40.fullmatch(head) is None
            or not isinstance(merge, str) or SHA40.fullmatch(merge) is None):
        raise HistoricalLot42Refused("LOT42 Git identities unavailable")
    statuses_doc = _read_gh(f"repos/{REPOSITORY}/commits/{head}/status")
    statuses = statuses_doc.get("statuses") if isinstance(statuses_doc, dict) else None
    if not isinstance(statuses, list):
        raise HistoricalLot42Refused("LOT42 trusted status unavailable")
    trusted = _select_trusted_status_at_merge(statuses, str(pr.get("merged_at")))
    run_match = RUN_URL.fullmatch(str(trusted.get("target_url", "")))
    if run_match is None:
        raise HistoricalLot42Refused("LOT42 trusted run URL absent")
    run_id = run_match.group(1)
    run = _read_gh(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    if (not isinstance(run, dict) or type(run.get("run_attempt")) is not int
            or not 1 <= run["run_attempt"] <= 100):
        raise HistoricalLot42Refused("LOT42 trusted run invalid")
    if expected_attempt is not None:
        if (type(expected_attempt) is not int or not 1 <= expected_attempt <= run["run_attempt"]):
            raise HistoricalLot42Refused("LOT42 historical attempt unavailable")
        attempt = _read_gh(
            f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{expected_attempt}"
        )
    else:
        # Le run global peut avoir été relancé après merge. Sélectionner
        # uniquement l'attempt dont le statut trusted pré-merge témoigne.
        status_at = _utc(trusted.get("created_at"))
        merged_at = _utc(pr.get("merged_at"))
        candidates = [
            candidate
            for index in range(1, run["run_attempt"] + 1)
            if isinstance((candidate := _read_gh(
                f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{index}"
            )), dict)
            and candidate.get("run_attempt") == index
            and candidate.get("status") == "completed"
            and candidate.get("conclusion") == "success"
            and _utc(candidate.get("run_started_at")) <= status_at
                <= _utc(candidate.get("updated_at")) <= merged_at
        ]
        if len(candidates) != 1:
            raise HistoricalLot42Refused("LOT42 pre-merge attempt not unique")
        attempt = candidates[0]
    if not isinstance(attempt, dict) or not isinstance(pr.get("base"), dict):
        raise HistoricalLot42Refused("LOT42 trusted attempt/base invalid")
    merge_parent = _git(root, "rev-parse", f"{merge}^")
    historical_pr = {
        **pr, "state": "open", "draft": False,
        "base": {**pr["base"], "sha": merge_parent},
    }
    decision = _evaluate_snapshot(
        pull_request=historical_pr, repository=REPOSITORY,
        pull_request_number=pull_request,
        config=load_config(DEFAULT_CONFIG_PATH), runner=run_gh_api,
    ).decision
    readback = _read_gh(f"repos/{REPOSITORY}/pulls/{pull_request}")
    if not isinstance(readback, dict) or any(
        readback.get(key) != pr.get(key)
        for key in ("state", "merged", "merge_commit_sha", "base", "head", "user")
    ):
        raise HistoricalLot42Refused("LOT42 PR changed during replay")
    branch_candidates = None
    if run.get("event") == "pull_request_target":
        head_ref = pr.get("head", {}).get("ref")
        if not isinstance(head_ref, str) or not head_ref:
            raise HistoricalLot42Refused("LOT42 PR head branch absent")
        branch = quote(f"{REPOSITORY.split('/')[0]}:{head_ref}", safe="")
        branch_candidates = _read_gh(
            f"repos/{REPOSITORY}/pulls?state=all&head={branch}&base=main&per_page=100&page=1"
        )
    checkout_head = _git(root, "rev-parse", "HEAD")
    github_main = _read_gh(f"repos/{REPOSITORY}/branches/main")
    if not isinstance(github_main, dict) or not isinstance(github_main.get("commit"), dict):
        raise HistoricalLot42Refused("LOT42 GitHub main unavailable")
    ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", merge, "HEAD"],
        capture_output=True, check=False, timeout=10,
    ).returncode == 0
    return {
        "pull_request": pr, "review_decision": asdict(decision), "trusted_status": trusted,
        "workflow_run": run, "workflow_attempt": attempt,
        "head_tree_sha": _git(root, "rev-parse", f"{head}^{{tree}}"),
        "merge_tree_sha": _git(root, "rev-parse", f"{merge}^{{tree}}"),
        "merge_parent_sha": merge_parent,
        "checkout_head_sha": checkout_head,
        "github_main_sha": github_main["commit"].get("sha"),
        "merge_is_ancestor": ancestor,
        "reviewed_head_blob": _git_blob(root, head, artifact_path),
        "main_blob": _git_blob(root, checkout_head, artifact_path),
        "run_pr_candidates": branch_candidates,
    }


def build_historical_lot42_receipt(
    root: Path, pull_request: int, artifact_path: str,
) -> dict[str, object]:
    """Produire le reçu seulement depuis les observations après fusion."""
    evidence = _live_evidence(root, pull_request, artifact_path)
    pr = evidence["pull_request"]
    decision = evidence["review_decision"]
    status = evidence["trusted_status"]
    run = evidence["workflow_run"]
    raw = evidence["reviewed_head_blob"]
    receipt = {
        "kind": KIND, "repository": REPOSITORY, "pull_request": pull_request,
        "base_sha": evidence["merge_parent_sha"], "head_sha": pr["head"]["sha"],
        "head_tree_sha": evidence["head_tree_sha"],
        "merge_commit_sha": pr["merge_commit_sha"],
        "author": pr["user"]["login"], "reviewer": REVIEWER,
        "review_id": decision["review_id"], "challenge": decision["challenge"],
        "review_submitted_at": decision["submitted_at"],
        "trusted_status_context": status["context"],
        "trusted_status_created_at": status["created_at"],
        "trusted_status_target_url": status["target_url"],
        "workflow_run_id": run["id"],
        "workflow_run_attempt": evidence["workflow_attempt"]["run_attempt"],
        "review_artifact_path": artifact_path,
        "review_artifact_sha256": hashlib.sha256(raw).hexdigest(),
        "review_artifact_blob_sha1": git_blob_sha1(raw),
    }
    validate_historical_lot42_receipt(receipt, **evidence)
    return receipt


def check_historical_lot42_receipt(
    root: Path, receipt_path: Path, pull_request: int,
    artifact_path: str, expected_raw: bytes,
) -> tuple[str, str, str, int, str, str]:
    """Relire la PR fusionnée et le blob, puis comparer au reçu canonique."""
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise HistoricalLot42Refused("LOT42 historical receipt absent or symlink")
    raw = receipt_path.read_bytes()
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HistoricalLot42Refused("LOT42 historical receipt JSON invalid") from error
    if (not isinstance(receipt, dict) or canonical_receipt(receipt) != raw
            or receipt.get("pull_request") != pull_request
            or receipt.get("review_artifact_path") != artifact_path
            or receipt.get("review_artifact_sha256") != hashlib.sha256(expected_raw).hexdigest()):
        raise HistoricalLot42Refused("LOT42 historical receipt differs from C")
    evidence = _live_evidence(
        root, pull_request, artifact_path,
        expected_attempt=receipt["workflow_run_attempt"],
    )
    if evidence["reviewed_head_blob"] != expected_raw:
        raise HistoricalLot42Refused("LOT42 historical reviewed blob differs from C")
    return validate_historical_lot42_receipt(receipt, **evidence)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--artifact-path", required=True)
    parser.add_argument("--artifact-file", type=Path, required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--write-receipt", type=Path)
    operation.add_argument("--check-receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.artifact_file.is_symlink() or not args.artifact_file.is_file():
            raise HistoricalLot42Refused("LOT42 artifact file absent")
        expected_raw = args.artifact_file.read_bytes()
        if args.write_receipt is not None:
            if args.write_receipt.exists() or args.write_receipt.is_symlink():
                raise HistoricalLot42Refused("LOT42 historical output already exists")
            receipt = build_historical_lot42_receipt(
                args.repo_root, args.pull_request, args.artifact_path,
            )
            if hashlib.sha256(expected_raw).hexdigest() != receipt["review_artifact_sha256"]:
                raise HistoricalLot42Refused("LOT42 artifact differs from C")
            args.write_receipt.parent.mkdir(parents=True, exist_ok=True)
            args.write_receipt.write_bytes(canonical_receipt(receipt))
            path = args.write_receipt
        else:
            path = args.check_receipt
        binding = check_historical_lot42_receipt(
            args.repo_root, path, args.pull_request,
            args.artifact_path, expected_raw,
        )
    except (HistoricalLot42Refused, KeyError, TypeError, ValueError, OSError,
            subprocess.TimeoutExpired):
        print("HISTORICAL_LOT42_REVIEW_PASS=false", file=sys.stderr)
        return 1
    print(json.dumps({"HISTORICAL_LOT42_REVIEW_PASS": True,
                      "HEAD_SHA": binding[1], "REVIEW_ID": binding[3]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
