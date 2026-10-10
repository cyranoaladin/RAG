"""Vérifie l'approbation exacte de #300 et les octets du pack délégué.

Le reçu versionné est un pointeur, jamais une approbation autonome : l'API
GitHub et le vérificateur canonique sont relus à chaque qualification.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

REPOSITORY = "cyranoaladin/RAG"
PR_NUMBER = 300
REVIEWER = "abenrhouma"
STATUS_CONTEXT = "trusted-human-review/head-pinned"
RECEIPT_RELATIVE_PATH = Path(
    "docs/reports/go_live/student_rights_evidence/pr300_final_authority_approval.json"
)
PACK_FILES = {
    "authority": "governance/student_public_rights/authorities/eduscol_etalab_2_0_sitewide_20261010.yml",
    "delegated_policy": "governance/student_public_rights/delegated_review_policy_v1.yml",
    "delegation_mandate": "governance/student_public_rights/delegation_abenrhouma_20261009.yml",
    "review_schema": "governance/student_public_rights/schemas/automated_artifact_review_v1.schema.json",
    "inventory_packet": "docs/reports/go_live/student_public_rights_individual_review_packet_20261009.json",
    "extraction_policy": "governance/student_public_rights/text_derivative_extraction_policy_v1.yml",
    "decision_sheet": "docs/reports/go_live/student_public_rights_individual_review_sheet_20261009.tsv",
    "evidence_index": "docs/reports/go_live/student_rights_evidence/index.json",
    "candidate_manifest": "docs/reports/go_live/student_rights_evidence/public_derivative_candidate_manifest_20261010.json",
}
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")


class AuthorityReceiptError(ValueError):
    """L'autorité finale de #300 ne peut pas être opposée à ce candidat."""


def _mapping(value: object) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise AuthorityReceiptError("AUTHORITY_RECEIPT_INVALID")
    return value


def _sha(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AuthorityReceiptError("AUTHORITY_TIMESTAMP_INVALID")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise AuthorityReceiptError("AUTHORITY_TIMESTAMP_INVALID") from error
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise AuthorityReceiptError("AUTHORITY_TIMESTAMP_INVALID")
    return parsed


def validate_pr300_authority_receipt(
    root: Path,
    receipt: Mapping[str, Any],
    *,
    pull_request: Mapping[str, Any],
    review_decision: Mapping[str, Any],
    trusted_status: Mapping[str, Any],
    head_tree_sha: str,
) -> dict[str, Any]:
    """Vérifie sans réseau les données relues indépendamment de GitHub/git."""
    r = _mapping(receipt)
    if (set(r) != {"kind", "repository", "pull_request", "base_sha", "head_sha",
                   "head_tree_sha", "merge_commit_sha", "reviewer", "review_id",
                   "challenge", "files", "sha256"}
            or r.get("kind") != "PR300_DELEGATED_STUDENT_RIGHTS_APPROVAL_V1"
            or r.get("repository") != REPOSITORY or r.get("pull_request") != PR_NUMBER
            or r.get("reviewer") != REVIEWER
            or type(r.get("review_id")) is not int or r["review_id"] <= 0
            or any(not _sha(r.get(k), SHA40) for k in (
                "base_sha", "head_sha", "head_tree_sha", "merge_commit_sha"))
            or not isinstance(r.get("challenge"), str)
            or not re.fullmatch(r"NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}", r["challenge"])):
        raise AuthorityReceiptError("AUTHORITY_RECEIPT_INVALID")
    if r.get("files") != PACK_FILES or set(_mapping(r.get("sha256"))) != set(PACK_FILES):
        raise AuthorityReceiptError("AUTHORITY_PACK_FILES_INVALID")
    for label, relative in PACK_FILES.items():
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()) or not path.is_file():
            raise AuthorityReceiptError(f"AUTHORITY_PACK_FILE_MISSING:{label}")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not _sha(r["sha256"].get(label), SHA64) or digest != r["sha256"][label]:
            raise AuthorityReceiptError(f"AUTHORITY_PACK_DIGEST_MISMATCH:{label}")
    pr = _mapping(pull_request)
    if (pr.get("number") != PR_NUMBER or pr.get("merged") is not True
            or _mapping(pr.get("base")).get("sha") != r["base_sha"]
            or _mapping(pr.get("head")).get("sha") != r["head_sha"]
            or pr.get("merge_commit_sha") != r["merge_commit_sha"]):
        raise AuthorityReceiptError("AUTHORITY_PR_REVISION_MISMATCH")
    decision = _mapping(review_decision)
    if (decision.get("approved") is not True or decision.get("reason") != "approved"
            or any(decision.get(k) != r[k] for k in (
                "base_sha", "head_sha", "reviewer", "review_id", "challenge"))):
        raise AuthorityReceiptError("AUTHORITY_EXACT_REVIEW_MISSING")
    if (trusted_status.get("context") != STATUS_CONTEXT
            or trusted_status.get("state") != "success"):
        raise AuthorityReceiptError("AUTHORITY_TRUSTED_STATUS_NOT_GREEN")
    merged_at = _utc(pr.get("merged_at"))
    if (_utc(decision.get("submitted_at")) > merged_at
            or _utc(trusted_status.get("created_at")) > merged_at):
        raise AuthorityReceiptError("AUTHORITY_APPROVAL_AFTER_MERGE")
    if head_tree_sha != r["head_tree_sha"]:
        raise AuthorityReceiptError("AUTHORITY_HEAD_TREE_MISMATCH")
    return {
        "PR300_AUTHORITY_APPROVAL_PASS": True,
        "PR_NUMBER": PR_NUMBER,
        "HEAD_SHA": r["head_sha"],
        "REVIEW_ID": r["review_id"],
        "EVIDENCE_PACK_SHA256": r["sha256"]["evidence_index"],
        "CANDIDATE_MANIFEST_SHA256": r["sha256"]["candidate_manifest"],
    }


def _read_gh(endpoint: str) -> Any:
    result = subprocess.run(
        ["gh", "api", endpoint], capture_output=True, text=True, check=False,
        timeout=30,
    )
    if result.returncode != 0:
        raise AuthorityReceiptError("AUTHORITY_GITHUB_UNAVAILABLE")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise AuthorityReceiptError("AUTHORITY_GITHUB_INVALID_JSON") from error


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True,
        check=False, timeout=20,
    )
    if result.returncode != 0:
        raise AuthorityReceiptError("AUTHORITY_GIT_BINDING_INVALID")
    return result.stdout.strip()


def check_pr300_authority(root: Path) -> dict[str, Any]:
    """Relit la review canonique et son statut au moment du build."""
    try:
        receipt = json.loads((root / RECEIPT_RELATIVE_PATH).read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise AuthorityReceiptError("AUTHORITY_RECEIPT_MISSING") from error
    r = _mapping(receipt)
    head = r.get("head_sha")
    if not _sha(head, SHA40):
        raise AuthorityReceiptError("AUTHORITY_HEAD_INVALID")
    github_path = root / "scripts/github"
    sys.path.insert(0, str(github_path))
    # Le vérificateur de merge exige une PR OPEN. Après fusion, on reconstruit
    # uniquement cette dimension historique depuis la PR effectivement
    # MERGED ; ses base/head/author/reviews et le statut publié restent relus
    # sur GitHub. C'est l'évaluation du gate *au moment de la fusion*, pas une
    # affirmation que la PR est encore ouverte.
    from trusted_human_review_github import (  # noqa: PLC0415
        DEFAULT_CONFIG_PATH,
        _evaluate_snapshot,
        load_config,
        run_gh_api,
    )

    pr = _read_gh(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    if not isinstance(pr, dict) or pr.get("merged") is not True or pr.get("state") != "closed":
        raise AuthorityReceiptError("AUTHORITY_PR_NOT_MERGED")
    historical_pr = {**pr, "state": "open", "draft": False}
    result = _evaluate_snapshot(
        pull_request=historical_pr, repository=REPOSITORY,
        pull_request_number=PR_NUMBER, config=load_config(DEFAULT_CONFIG_PATH),
        runner=run_gh_api,
    )
    readback = _read_gh(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    if not isinstance(readback, dict) or any(readback.get(k) != pr.get(k) for k in (
        "state", "merged", "merge_commit_sha", "base", "head",
    )):
        raise AuthorityReceiptError("AUTHORITY_PR_CHANGED_DURING_EVALUATION")
    statuses = _mapping(_read_gh(f"repos/{REPOSITORY}/commits/{head}/status")).get("statuses")
    if not isinstance(statuses, list):
        raise AuthorityReceiptError("AUTHORITY_STATUS_UNAVAILABLE")
    trusted = next((s for s in statuses if isinstance(s, dict)
                    and s.get("context") == STATUS_CONTEXT), None)
    if trusted is None:
        raise AuthorityReceiptError("AUTHORITY_STATUS_UNAVAILABLE")
    head_tree = _git(root, "rev-parse", f"{head}^{{tree}}")
    merge_tree = _git(root, "rev-parse", f"{r.get('merge_commit_sha')}^{{tree}}")
    if head_tree != merge_tree:
        raise AuthorityReceiptError("AUTHORITY_MERGE_TREE_MISMATCH")
    _git(root, "merge-base", "--is-ancestor", str(r.get("merge_commit_sha")), "HEAD")
    return validate_pr300_authority_receipt(
        root, r, pull_request=_mapping(pr), review_decision=asdict(result.decision),
        trusted_status=_mapping(trusted), head_tree_sha=head_tree,
    )


__all__ = ["AuthorityReceiptError", "check_pr300_authority",
           "validate_pr300_authority_receipt"]
