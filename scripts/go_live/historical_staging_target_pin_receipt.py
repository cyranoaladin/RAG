#!/usr/bin/env python3
"""Rejoue après merge l'approbation exacte d'un pin staging, sans auto-autorité.

Le reçu est un pointeur vers GitHub, Git et la cible vivante. Il ne permet ni
publication ni signature à lui seul. Son contrôle relit ces trois autorités.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

from independent_staging_target_pin import (
    CONTAINER_IDENTITY,
    PIN_DIRECTORY,
    REPOSITORY,
    REVIEWER,
    SHA40,
    SHA256,
    PinRefused,
    _git_blob,
    observe_live_target,
    verify_target_pin,
)
from pr300_authority_receipt import (
    AuthorityReceiptError,
    _git,
    _read_gh,
    _select_trusted_status_at_merge,
    _utc,
    _validate_trusted_workflow_run,
)


GITHUB_DIR = Path(__file__).resolve().parents[1] / "github"
if str(GITHUB_DIR) not in sys.path:
    sys.path.insert(0, str(GITHUB_DIR))
from trusted_human_review import build_challenge  # noqa: E402


KIND = "NEXUS_STAGING_TARGET_PIN_MERGED_REVIEW_RECEIPT_V1"
STATUS = "APPROVED_PIN_NOT_PUBLICATION_AUTHORITY"
STATUS_CONTEXT = "trusted-human-review/head-pinned"
RUN_URL = re.compile(r"https://github\.com/cyranoaladin/RAG/actions/runs/([1-9][0-9]*)\Z")
FIELDS = frozenset({
    "kind", "status", "repository", "pull_request", "base_ref", "base_sha",
    "head_sha", "head_tree_sha", "merge_commit_sha", "author", "reviewer",
    "review_id", "challenge", "review_submitted_at", "trusted_status_context",
    "trusted_status_created_at", "trusted_status_target_url", "workflow_run_id",
    "workflow_run_attempt", "content_anchor_sha256", "target_pin_path",
    "target_pin_sha256",
})


class HistoricalPinRefused(ValueError):
    """Le reçu historique ne correspond plus aux autorités indépendantes."""


def canonical_receipt(value: Mapping[str, object]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(",", ":")) + "\n").encode("utf-8")


def _pin_path(value: object) -> Path:
    if not isinstance(value, str):
        raise HistoricalPinRefused("chemin du pin absent")
    path = Path(value)
    if (path.is_absolute() or ".." in path.parts or path.parent != PIN_DIRECTORY
            or path.suffix != ".json"):
        raise HistoricalPinRefused("chemin du pin hors autorité versionnée")
    return path


def _sha(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def validate_historical_pin_receipt(
    *, receipt: Mapping[str, object], pin_raw: bytes,
    expected_pin_path: str, expected_content_anchor_sha256: str,
    destination_root: Path, observation: object, now: datetime,
    pull_request: Mapping[str, object], review_decision: Mapping[str, object],
    trusted_status: Mapping[str, object], workflow_run: Mapping[str, object],
    workflow_attempt: Mapping[str, object], head_tree_sha: str,
    merge_tree_sha: str, merge_parent_sha: str,
    reviewed_head_pin_blob: bytes, main_pin_blob: bytes,
    checkout_head_sha: str, github_main_sha: str, merge_is_ancestor: bool,
) -> dict[str, object]:
    """Validation pure; chaque valeur externe est fournie par une lecture distincte."""
    r = receipt
    if (set(r) != FIELDS or r.get("kind") != KIND or r.get("status") != STATUS
            or r.get("repository") != REPOSITORY or r.get("reviewer") != REVIEWER
            or r.get("base_ref") != "main"
            or type(r.get("pull_request")) is not int or r["pull_request"] <= 0
            or type(r.get("review_id")) is not int or r["review_id"] <= 0
            or type(r.get("workflow_run_id")) is not int or r["workflow_run_id"] <= 0
            or type(r.get("workflow_run_attempt")) is not int
            or r["workflow_run_attempt"] <= 0
            or any(not _sha(r.get(key), SHA40) for key in (
                "base_sha", "head_sha", "head_tree_sha", "merge_commit_sha",
            ))
            or any(not _sha(r.get(key), SHA256) for key in (
                "content_anchor_sha256", "target_pin_sha256",
            ))
            or not isinstance(r.get("author"), str) or not r["author"]
            or r.get("content_anchor_sha256") != expected_content_anchor_sha256
            or r.get("target_pin_path") != expected_pin_path):
        raise HistoricalPinRefused("forme ou portée du reçu invalide")
    _pin_path(r["target_pin_path"])
    expected_challenge = build_challenge({
        "protocol": "NEXUS-TRUSTED-REVIEW-V1", "repository": REPOSITORY,
        "pull_request": r["pull_request"], "base_ref": "main",
        "base_sha": r["base_sha"], "head_sha": r["head_sha"],
        "author": r["author"], "reviewer": REVIEWER,
    })
    if r.get("challenge") != expected_challenge:
        raise HistoricalPinRefused("challenge exact-head divergent")
    if (hashlib.sha256(pin_raw).hexdigest() != r["target_pin_sha256"]
            or reviewed_head_pin_blob != pin_raw or main_pin_blob != pin_raw
            or head_tree_sha != merge_tree_sha
            or head_tree_sha != r["head_tree_sha"]
            or merge_parent_sha != r["base_sha"]
            or checkout_head_sha != github_main_sha
            or not _sha(checkout_head_sha, SHA40)
            or merge_is_ancestor is not True):
        raise HistoricalPinRefused("blob pin, tree fusionné ou main divergent")
    try:
        verify_target_pin(
            pin_raw, expected_sha256=str(r["target_pin_sha256"]),
            expected_content_anchor_sha256=expected_content_anchor_sha256,
            destination_root=destination_root, observation=observation, now=now,
        )
    except PinRefused as error:
        raise HistoricalPinRefused("cible du pin live non qualifiée") from error
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
        raise HistoricalPinRefused("PR fusionnée différente du reçu")
    decision = review_decision
    if (decision.get("approved") is not True or decision.get("reason") != "approved"
            or any(decision.get(key) != r[key] for key in (
                "repository", "pull_request", "base_sha", "head_sha",
                "reviewer", "review_id", "challenge",
            ))
            or decision.get("submitted_at") != r["review_submitted_at"]):
        raise HistoricalPinRefused("review exacte absente ou usurpée")
    status = trusted_status
    run = workflow_run
    attempt = workflow_attempt
    if (status.get("context") != r["trusted_status_context"] == STATUS_CONTEXT
            or status.get("state") != "success"
            or status.get("created_at") != r["trusted_status_created_at"]
            or status.get("target_url") != r["trusted_status_target_url"]
            or run.get("id") != r["workflow_run_id"]
            or run.get("run_attempt") != r["workflow_run_attempt"]
            or attempt.get("id") != r["workflow_run_id"]
            or attempt.get("run_attempt") != r["workflow_run_attempt"]
            or attempt.get("event") != "issue_comment"
            or attempt.get("head_sha") != r["base_sha"]
            or attempt.get("status") != "completed"
            or attempt.get("conclusion") != "success"):
        raise HistoricalPinRefused("statut trusted ou run divergent")
    match = RUN_URL.fullmatch(str(r["trusted_status_target_url"]))
    if match is None or int(match.group(1)) != r["workflow_run_id"]:
        raise HistoricalPinRefused("run trusted hors URL canonique")
    try:
        _validate_trusted_workflow_run(status, run, expected_base_sha=str(r["base_sha"]))
        pinned = _utc(json.loads(pin_raw)["pinned_at_utc"])
        reviewed = _utc(r["review_submitted_at"])
        started = _utc(attempt.get("run_started_at"))
        status_at = _utc(status["created_at"])
        finished = _utc(attempt.get("updated_at"))
        merged = _utc(pr.get("merged_at"))
    except (AuthorityReceiptError, KeyError, TypeError, ValueError) as error:
        raise HistoricalPinRefused("chronologie du pin/review/run invalide") from error
    if not pinned <= reviewed <= started <= status_at <= finished <= merged:
        raise HistoricalPinRefused("pin, review, run ou merge hors fenêtre")
    return {
        "HISTORICAL_STAGING_TARGET_PIN_PASS": True,
        "PUBLICATION_AUTHORIZED": False,
        "EXPECTED_TARGET_PIN_SHA256": r["target_pin_sha256"],
        "CONTENT_ANCHOR_SHA256": r["content_anchor_sha256"],
        "PR_NUMBER": r["pull_request"],
        "REVIEW_ID": r["review_id"],
        "HEAD_SHA": r["head_sha"],
        "MERGE_COMMIT_SHA": r["merge_commit_sha"],
    }


def _live_evidence(root: Path, pin_path: Path, pull_request: int,
                   destination_root: Path, database_dsn: str) -> dict[str, Any]:
    """GitHub et Git live, puis cible live; aucun reçu local ne fait autorité."""
    _pin_path(pin_path.as_posix())
    local = root / pin_path
    if local.is_symlink() or not local.is_file():
        raise HistoricalPinRefused("pin local absent ou symbolique")
    pin_raw = local.read_bytes()
    try:
        pin = json.loads(pin_raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HistoricalPinRefused("pin JSON illisible") from error
    if not isinstance(pin, dict):
        raise HistoricalPinRefused("pin JSON non objet")
    match = CONTAINER_IDENTITY.fullmatch(str(pin.get("target_identity")))
    if match is None:
        raise HistoricalPinRefused("pin sans conteneur")
    from trusted_human_review_github import (  # noqa: PLC0415
        DEFAULT_CONFIG_PATH,
        _evaluate_snapshot,
        load_config,
        run_gh_api,
    )

    pr = _read_gh(f"repos/{REPOSITORY}/pulls/{pull_request}")
    if not isinstance(pr, dict) or pr.get("state") != "closed" or pr.get("merged") is not True:
        raise HistoricalPinRefused("PR du pin non fusionnée")
    head = pr.get("head", {}).get("sha")
    if not _sha(head, SHA40):
        raise HistoricalPinRefused("HEAD de PR invalide")
    statuses_doc = _read_gh(f"repos/{REPOSITORY}/commits/{head}/status")
    statuses = statuses_doc.get("statuses") if isinstance(statuses_doc, dict) else None
    if not isinstance(statuses, list):
        raise HistoricalPinRefused("statuts trusted indisponibles")
    trusted = _select_trusted_status_at_merge(statuses, str(pr.get("merged_at")))
    run_match = RUN_URL.fullmatch(str(trusted.get("target_url", "")))
    if run_match is None:
        raise HistoricalPinRefused("run trusted absent")
    run_id = run_match.group(1)
    run = _read_gh(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    if not isinstance(run, dict) or type(run.get("run_attempt")) is not int:
        raise HistoricalPinRefused("run trusted malformé")
    attempt = _read_gh(
        f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{run['run_attempt']}"
    )
    if not isinstance(attempt, dict) or not _sha(run.get("head_sha"), SHA40):
        raise HistoricalPinRefused("tentative trusted malformée")
    base = pr.get("base")
    if not isinstance(base, dict):
        raise HistoricalPinRefused("base GitHub absente")
    historical_pr = {
        **pr, "state": "open", "draft": False,
        "base": {**base, "sha": run["head_sha"]},
    }
    decision = _evaluate_snapshot(
        pull_request=historical_pr, repository=REPOSITORY,
        pull_request_number=pull_request,
        config=load_config(DEFAULT_CONFIG_PATH), runner=run_gh_api,
    ).decision
    readback = _read_gh(f"repos/{REPOSITORY}/pulls/{pull_request}")
    if not isinstance(readback, dict) or any(readback.get(key) != pr.get(key) for key in (
        "state", "merged", "merge_commit_sha", "base", "head", "user",
    )):
        raise HistoricalPinRefused("PR modifiée pendant le rejeu")
    merge = pr.get("merge_commit_sha")
    if not _sha(merge, SHA40):
        raise HistoricalPinRefused("commit de fusion invalide")
    head_tree = _git(root, "rev-parse", f"{head}^{{tree}}")
    merge_tree = _git(root, "rev-parse", f"{merge}^{{tree}}")
    merge_parent = _git(root, "rev-parse", f"{merge}^")
    checkout_head = _git(root, "rev-parse", "HEAD")
    github_main = _read_gh(f"repos/{REPOSITORY}/branches/main")
    if not isinstance(github_main, dict) or not isinstance(github_main.get("commit"), dict):
        raise HistoricalPinRefused("main GitHub indisponible")
    main_sha = github_main["commit"].get("sha")
    merged_ancestor = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", merge, "HEAD"],
        check=False, capture_output=True, timeout=10,
    ).returncode == 0
    head_blob = _git_blob(root, head, pin_path)
    main_blob = _git_blob(root, checkout_head, pin_path)
    observation = observe_live_target(
        container_id=match.group(1), destination_root=destination_root,
        database_dsn=database_dsn,
    )
    return dict(
        pin_raw=pin_raw, destination_root=destination_root,
        observation=observation, now=datetime.now(UTC),
        pull_request=pr, review_decision=asdict(decision), trusted_status=trusted,
        workflow_run=run, workflow_attempt=attempt, head_tree_sha=head_tree,
        merge_tree_sha=merge_tree, merge_parent_sha=merge_parent,
        reviewed_head_pin_blob=head_blob,
        main_pin_blob=main_blob, checkout_head_sha=checkout_head,
        github_main_sha=main_sha, merge_is_ancestor=merged_ancestor,
    )


def build_historical_pin_receipt(
    root: Path, pin_path: Path, pull_request: int,
    expected_content_anchor_sha256: str, destination_root: Path,
    database_dsn: str,
) -> dict[str, object]:
    """Construire seulement depuis les autorités GitHub/Git/cible relues."""
    evidence = _live_evidence(root, pin_path, pull_request,
                              destination_root, database_dsn)
    pr = evidence["pull_request"]
    decision = evidence["review_decision"]
    trusted = evidence["trusted_status"]
    run = evidence["workflow_run"]
    receipt = {
        "kind": KIND, "status": STATUS, "repository": REPOSITORY,
        "pull_request": pull_request, "base_ref": "main",
        "base_sha": run["head_sha"], "head_sha": pr["head"]["sha"],
        "head_tree_sha": evidence["head_tree_sha"],
        "merge_commit_sha": pr["merge_commit_sha"],
        "author": pr["user"]["login"], "reviewer": REVIEWER,
        "review_id": decision["review_id"],
        "challenge": decision["challenge"],
        "review_submitted_at": decision["submitted_at"],
        "trusted_status_context": trusted["context"],
        "trusted_status_created_at": trusted["created_at"],
        "trusted_status_target_url": trusted["target_url"],
        "workflow_run_id": run["id"],
        "workflow_run_attempt": run["run_attempt"],
        "content_anchor_sha256": expected_content_anchor_sha256,
        "target_pin_path": pin_path.as_posix(),
        "target_pin_sha256": hashlib.sha256(evidence["pin_raw"]).hexdigest(),
    }
    validate_historical_pin_receipt(
        receipt=receipt, expected_pin_path=pin_path.as_posix(),
        expected_content_anchor_sha256=expected_content_anchor_sha256,
        **evidence,
    )
    return receipt


def check_historical_pin_receipt(
    root: Path, receipt_path: Path, pin_path: Path, pull_request: int,
    expected_content_anchor_sha256: str, destination_root: Path,
    database_dsn: str,
) -> dict[str, object]:
    """Le reçu stocké n'est jamais substitué à la relecture live."""
    if receipt_path.is_symlink() or not receipt_path.is_file():
        raise HistoricalPinRefused("reçu historique absent ou symbolique")
    raw = receipt_path.read_bytes()
    try:
        receipt = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HistoricalPinRefused("reçu historique JSON invalide") from error
    if not isinstance(receipt, dict) or canonical_receipt(receipt) != raw:
        raise HistoricalPinRefused("reçu historique non canonique")
    if receipt.get("pull_request") != pull_request:
        raise HistoricalPinRefused("numéro de PR différent du reçu")
    evidence = _live_evidence(root, pin_path, pull_request,
                              destination_root, database_dsn)
    verdict = validate_historical_pin_receipt(
        receipt=receipt, expected_pin_path=pin_path.as_posix(),
        expected_content_anchor_sha256=expected_content_anchor_sha256,
        **evidence,
    )
    pin = json.loads(evidence["pin_raw"])
    match = CONTAINER_IDENTITY.fullmatch(str(pin["target_identity"]))
    if match is None:
        raise HistoricalPinRefused("pin final sans conteneur")
    observed_final = observe_live_target(
        container_id=match.group(1), destination_root=destination_root,
        database_dsn=database_dsn,
    )
    try:
        verify_target_pin(
            evidence["pin_raw"], expected_sha256=str(receipt["target_pin_sha256"]),
            expected_content_anchor_sha256=expected_content_anchor_sha256,
            destination_root=destination_root, observation=observed_final,
            now=datetime.now(UTC),
        )
    except PinRefused as error:
        raise HistoricalPinRefused("pin expiré ou cible modifiée après rejeu") from error
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--pin-path", type=Path, required=True)
    parser.add_argument("--pull-request", type=int, required=True)
    parser.add_argument("--expected-content-anchor-sha256", required=True)
    parser.add_argument("--destination-root", type=Path, required=True)
    parser.add_argument("--database-dsn-env", required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--write-receipt", type=Path)
    operation.add_argument("--check-receipt", type=Path)
    args = parser.parse_args(argv)
    try:
        import os  # noqa: PLC0415

        dsn = os.environ.get(args.database_dsn_env, "")
        if args.write_receipt:
            receipt = build_historical_pin_receipt(
                args.repo_root, args.pin_path, args.pull_request,
                args.expected_content_anchor_sha256, args.destination_root, dsn,
            )
            if args.write_receipt.exists() or args.write_receipt.is_symlink():
                raise HistoricalPinRefused("reçu de sortie déjà présent")
            args.write_receipt.parent.mkdir(parents=True, exist_ok=True)
            args.write_receipt.write_bytes(canonical_receipt(receipt))
            verdict = check_historical_pin_receipt(
                args.repo_root, args.write_receipt, args.pin_path,
                args.pull_request, args.expected_content_anchor_sha256,
                args.destination_root, dsn,
            )
        else:
            verdict = check_historical_pin_receipt(
                args.repo_root, args.check_receipt, args.pin_path,
                args.pull_request, args.expected_content_anchor_sha256,
                args.destination_root, dsn,
            )
    except (HistoricalPinRefused, PinRefused, AuthorityReceiptError, OSError,
            KeyError, TypeError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        print("HISTORICAL_STAGING_TARGET_PIN_PASS=false", file=sys.stderr)
        return 1
    print(json.dumps(verdict, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
