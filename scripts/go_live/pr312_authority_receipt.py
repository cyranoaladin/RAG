"""Vérification exacte de l'approbation #312 du candidat public étudiant."""

from __future__ import annotations

import hashlib
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

from pr300_authority_receipt import (
    AuthorityReceiptError,
    _git,
    _mapping,
    _read_gh,
    _select_trusted_status_at_merge,
    _sha,
    _utc,
)

REPOSITORY = "cyranoaladin/RAG"
PR_NUMBER = 312
REVIEWER = "abenrhouma"
STATUS_CONTEXT = "trusted-human-review/head-pinned"
TRUSTED_WORKFLOW_PATH = ".github/workflows/trusted-human-review.yml"
RECEIPT_RELATIVE_PATH = Path(
    "docs/reports/go_live/student_rights_evidence/pr312_candidate_approval.json"
)
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
CHALLENGE = re.compile(r"NEXUS-TRUSTED-REVIEW-V1:[0-9a-f]{64}\Z")
RELEASE_ID = "student-public-20261010-v1-eb39f6cd0423e184"
RELEASE_PARENT = Path(
    "services/rag-pedago/data/releases/prerentree_2026_2027/"
    "profile_gate_student_public_v1/release-eb39f6cd0423e184"
)
RELEASE_ROOT = RELEASE_PARENT / "profile_gate"
COLLECTIONS = (
    "dgemc_terminale_option",
    "hggsp_premiere_specialite",
    "hggsp_terminale_specialite",
    "hlp_premiere_specialite",
    "hlp_terminale_specialite",
    "nsi_premiere_specialite",
    "nsi_terminale_specialite",
    "ses_premiere_specialite",
    "ses_terminale_specialite",
    "svt_premiere_specialite",
    "svt_terminale_specialite",
)
PACK_FILES = {
    "release_registry": str(RELEASE_PARENT / "release-registry.json"),
    "aggregate": str(RELEASE_ROOT / "production-profile-gate.release.json"),
    "artifacts": str(RELEASE_ROOT / "artifacts.release.json"),
    "public_profiles": str(RELEASE_ROOT / "public_profiles.json"),
    "public_rights": str(RELEASE_ROOT / "public_rights_registry.json"),
    "public_pii": str(RELEASE_ROOT / "public_pii_registry.json"),
    **{
        f"subject_{collection}": str(
            RELEASE_ROOT / "subjects" / f"rag_nexus_{collection}.release.json"
        )
        for collection in COLLECTIONS
    },
}
EXPECTED_COUNTS = {
    "unique_artifacts": 253, "placements": 377,
    "unique_chunks": 3975, "subjects": 11,
}


def _read_bound_json(root: Path, relative: str, digest: str) -> dict[str, Any]:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise AuthorityReceiptError("CANDIDATE_FILE_MISSING")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != digest:
        raise AuthorityReceiptError("CANDIDATE_FILE_DIGEST_MISMATCH")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise AuthorityReceiptError("CANDIDATE_FILE_INVALID_JSON") from error
    if not isinstance(value, dict):
        raise AuthorityReceiptError("CANDIDATE_FILE_NOT_OBJECT")
    return value


def require_pack_matches_approved_tree(
    root: Path, approved_head: str, files: Mapping[str, str],
) -> None:
    """Comparer les octets locaux aux blobs du HEAD approuvé, pas au seul reçu."""
    if not _sha(approved_head, SHA40):
        raise AuthorityReceiptError("APPROVED_HEAD_INVALID")
    for relative in files.values():
        candidate = root / relative
        if candidate.is_symlink() or not candidate.is_file():
            raise AuthorityReceiptError("APPROVED_HEAD_PACK_FILE_MISSING")
        historical_blob = _git(root, "rev-parse", f"{approved_head}:{relative}")
        current_blob = _git(root, "hash-object", "--", relative)
        if historical_blob != current_blob:
            raise AuthorityReceiptError("APPROVED_HEAD_PACK_FILE_CHANGED")


def _validate_candidate_pack(pack: Mapping[str, dict[str, Any]], digests: Mapping[str, str]) -> None:
    aggregate = pack["aggregate"]
    registry = pack["artifacts"]
    release_registry = pack["release_registry"]
    if (
        aggregate.get("release_id") != RELEASE_ID
        or aggregate.get("release_kind") != "MULTILEVEL_AGGREGATE_RELEASE_V2"
        or aggregate.get("release_mode") != "candidate"
        or aggregate.get("promotion_status") != "NOT_PROMOTABLE"
        or aggregate.get("activation_status") != "NO_PRODUCTION_ACTIVATION"
        or aggregate.get("review_status") != "PRE_REVIEW"
        or aggregate.get("expected_counts") != EXPECTED_COUNTS
        or aggregate.get("artifact_registry") != {
            "path": "artifacts.release.json", "sha256": digests["artifacts"],
        }
        or registry.get("release_id") != RELEASE_ID
        or registry.get("expected_counts") != {
            "unique_artifacts": 253, "unique_chunks": 3975,
        }
    ):
        raise AuthorityReceiptError("CANDIDATE_AGGREGATE_INVALID")
    artifacts = registry.get("artifacts")
    if (
        not isinstance(artifacts, list) or len(artifacts) != 253
        or len({a.get("content_sha256") for a in artifacts if isinstance(a, dict)}) != 253
        or any(
            not isinstance(a, dict)
            or a.get("media_type") != "text/plain; charset=utf-8"
            or a.get("artifact_id") != a.get("content_sha256")
            or a.get("source_pdf_sha256") == a.get("content_sha256")
            for a in artifacts
        )
    ):
        raise AuthorityReceiptError("CANDIDATE_ARTIFACTS_INVALID")
    authorities = _mapping(aggregate.get("authorities"))
    sidecars = {
        "public_profiles": "public_profile_registry_sha256",
        "public_rights": "public_rights_registry_sha256",
        "public_pii": "public_pii_registry_sha256",
    }
    for label, authority_key in sidecars.items():
        sidecar = pack[label]
        if (
            authorities.get(authority_key) != digests[label]
            or sidecar.get("release_id") != RELEASE_ID
            or sidecar.get("status") != "CANDIDATE_NOT_AUTHORIZED"
        ):
            raise AuthorityReceiptError("CANDIDATE_SIDECAR_INVALID")
    if (
        len(pack["public_profiles"].get("entries", [])) != 11
        or len(pack["public_rights"].get("entries", [])) != 253
        or len(pack["public_pii"].get("entries", [])) != 253
    ):
        raise AuthorityReceiptError("CANDIDATE_SIDECAR_POPULATION_INVALID")
    refs = aggregate.get("subjects")
    expected = {f"rag_nexus_{collection}" for collection in COLLECTIONS}
    if not isinstance(refs, list) or len(refs) != 11:
        raise AuthorityReceiptError("CANDIDATE_SUBJECTS_INVALID")
    observed = set()
    for ref in refs:
        if not isinstance(ref, dict):
            raise AuthorityReceiptError("CANDIDATE_SUBJECTS_INVALID")
        collection = ref.get("collection")
        if collection not in expected or collection in observed:
            raise AuthorityReceiptError("CANDIDATE_SUBJECTS_INVALID")
        observed.add(collection)
        label = f"subject_{collection.removeprefix('rag_nexus_')}"
        if (
            ref.get("path") != f"subjects/{collection}.release.json"
            or ref.get("sha256") != digests[label]
            or pack[label].get("collection") != collection
            or pack[label].get("release_id") != f"{RELEASE_ID}-{collection}"
            or pack[label].get("authorities") != authorities
        ):
            raise AuthorityReceiptError("CANDIDATE_SUBJECT_BINDING_INVALID")
    if observed != expected or release_registry.get("releases") != [{
        "release_id": RELEASE_ID,
        "collections": sorted(expected),
        "manifest_path": f"{RELEASE_ROOT.name}/production-profile-gate.release.json",
        "expected_manifest_sha256": digests["aggregate"],
        "release_kind": "MULTILEVEL_AGGREGATE_RELEASE_V2",
    }]:
        raise AuthorityReceiptError("CANDIDATE_RELEASE_REGISTRY_INVALID")


def _validate_trusted_workflow_attempt(
    status: Mapping[str, Any], run: Mapping[str, Any], attempt: Mapping[str, Any],
    *, expected_head_sha: str, review_submitted_at: str, merged_at: str,
) -> None:
    target = status.get("target_url")
    match = re.fullmatch(
        rf"https://github\.com/{re.escape(REPOSITORY)}/actions/runs/([1-9][0-9]*)",
        target if isinstance(target, str) else "",
    )
    if match is None:
        raise AuthorityReceiptError("AUTHORITY_WORKFLOW_PROVENANCE_MISSING")
    run_id = int(match.group(1))
    if (
        run.get("id") != run_id
        or run.get("name") != "Trusted human review"
        or run.get("path") != TRUSTED_WORKFLOW_PATH
        or run.get("event") != "pull_request_target"
        or run.get("head_sha") != expected_head_sha
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or type(run.get("run_attempt")) is not int
        or run["run_attempt"] < 1
        or attempt.get("id") != run_id
        or attempt.get("run_attempt") != run["run_attempt"]
        or attempt.get("event") != run["event"]
        or attempt.get("head_sha") != expected_head_sha
        or attempt.get("status") != "completed"
        or attempt.get("conclusion") != "success"
    ):
        raise AuthorityReceiptError("AUTHORITY_WORKFLOW_PROVENANCE_INVALID")
    review_at = _utc(review_submitted_at)
    started_at = _utc(attempt.get("run_started_at"))
    status_at = _utc(status.get("created_at"))
    ended_at = _utc(attempt.get("updated_at"))
    merged = _utc(merged_at)
    if not review_at <= started_at <= status_at <= ended_at <= merged:
        raise AuthorityReceiptError("AUTHORITY_WORKFLOW_ATTEMPT_WINDOW_INVALID")


def validate_pr312_authority_receipt(
    root: Path, receipt: Mapping[str, Any], *,
    pull_request: Mapping[str, Any], review_decision: Mapping[str, Any],
    trusted_status: Mapping[str, Any], head_tree_sha: str,
) -> dict[str, Any]:
    r = _mapping(receipt)
    if (
        set(r) != {
            "kind", "repository", "pull_request", "base_sha", "head_sha",
            "head_tree_sha", "merge_commit_sha", "reviewer", "review_id",
            "challenge", "release_id", "expected_counts", "files", "sha256",
        }
        or r.get("kind") != "PR312_STUDENT_PUBLIC_CANDIDATE_APPROVAL_V1"
        or r.get("repository") != REPOSITORY
        or r.get("pull_request") != PR_NUMBER
        or r.get("reviewer") != REVIEWER
        or type(r.get("review_id")) is not int
        or r["review_id"] <= 0
        or any(not _sha(r.get(name), SHA40) for name in (
            "base_sha", "head_sha", "head_tree_sha", "merge_commit_sha",
        ))
        or not isinstance(r.get("challenge"), str)
        or CHALLENGE.fullmatch(r["challenge"]) is None
        or r.get("release_id") != RELEASE_ID
        or r.get("expected_counts") != EXPECTED_COUNTS
        or r.get("files") != PACK_FILES
    ):
        raise AuthorityReceiptError("AUTHORITY_RECEIPT_INVALID")
    digests = _mapping(r.get("sha256"))
    if set(digests) != set(PACK_FILES):
        raise AuthorityReceiptError("AUTHORITY_PACK_FILES_INVALID")
    pack = {}
    for label, relative in PACK_FILES.items():
        digest = digests[label]
        if not _sha(digest, SHA64):
            raise AuthorityReceiptError("AUTHORITY_PACK_DIGEST_INVALID")
        pack[label] = _read_bound_json(root, relative, digest)
    _validate_candidate_pack(pack, digests)
    pr = _mapping(pull_request)
    if (
        pr.get("number") != PR_NUMBER
        or pr.get("state") != "closed"
        or pr.get("merged") is not True
        or _mapping(pr.get("base")).get("sha") != r["base_sha"]
        or _mapping(pr.get("head")).get("sha") != r["head_sha"]
        or pr.get("merge_commit_sha") != r["merge_commit_sha"]
    ):
        raise AuthorityReceiptError("AUTHORITY_PR_REVISION_MISMATCH")
    decision = _mapping(review_decision)
    if (
        decision.get("approved") is not True
        or decision.get("reason") != "approved"
        or any(decision.get(name) != r[name] for name in (
            "base_sha", "head_sha", "reviewer", "review_id", "challenge",
        ))
    ):
        raise AuthorityReceiptError("AUTHORITY_EXACT_REVIEW_MISSING")
    merged_at = _utc(pr.get("merged_at"))
    if (
        _utc(decision.get("submitted_at")) > merged_at
        or _utc(trusted_status.get("created_at")) > merged_at
        or trusted_status.get("context") != STATUS_CONTEXT
        or trusted_status.get("state") != "success"
        or head_tree_sha != r["head_tree_sha"]
    ):
        raise AuthorityReceiptError("AUTHORITY_MERGE_BOUNDARY_INVALID")
    return {
        "PR312_AUTHORITY_APPROVAL_PASS": True,
        "PR_NUMBER": PR_NUMBER,
        "HEAD_SHA": r["head_sha"],
        "MERGE_COMMIT_SHA": r["merge_commit_sha"],
        "REVIEW_ID": r["review_id"],
        "RELEASE_ID": RELEASE_ID,
        "EXPECTED_COUNTS": EXPECTED_COUNTS,
        "AGGREGATE_SHA256": digests["aggregate"],
        "ARTIFACTS_SHA256": digests["artifacts"],
        "CANDIDATE_ACTIVATION_ALLOWED": False,
    }


def check_pr312_authority(root: Path) -> dict[str, Any]:
    """Relire GitHub et Git ; le fichier versionné n'est jamais autonome."""
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
    from trusted_human_review_github import (
        DEFAULT_CONFIG_PATH,
        _evaluate_snapshot,
        load_config,
        run_gh_api,
    )

    pr = _read_gh(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    if not isinstance(pr, dict) or pr.get("state") != "closed" or pr.get("merged") is not True:
        raise AuthorityReceiptError("AUTHORITY_PR_NOT_MERGED")
    result = _evaluate_snapshot(
        pull_request={**pr, "state": "open", "draft": False},
        repository=REPOSITORY, pull_request_number=PR_NUMBER,
        config=load_config(DEFAULT_CONFIG_PATH), runner=run_gh_api,
    )
    readback = _read_gh(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    if not isinstance(readback, dict) or any(readback.get(key) != pr.get(key) for key in (
        "state", "merged", "merge_commit_sha", "base", "head",
    )):
        raise AuthorityReceiptError("AUTHORITY_PR_CHANGED_DURING_EVALUATION")
    statuses = _mapping(_read_gh(f"repos/{REPOSITORY}/commits/{head}/status")).get("statuses")
    if not isinstance(statuses, list):
        raise AuthorityReceiptError("AUTHORITY_STATUS_UNAVAILABLE")
    trusted = _select_trusted_status_at_merge(statuses, str(pr.get("merged_at")))
    target = trusted.get("target_url")
    match = re.fullmatch(
        rf"https://github\.com/{re.escape(REPOSITORY)}/actions/runs/([1-9][0-9]*)",
        target if isinstance(target, str) else "",
    )
    if match is None:
        raise AuthorityReceiptError("AUTHORITY_WORKFLOW_PROVENANCE_MISSING")
    run_id = match.group(1)
    run = _mapping(_read_gh(f"repos/{REPOSITORY}/actions/runs/{run_id}"))
    attempt = _mapping(_read_gh(
        f"repos/{REPOSITORY}/actions/runs/{run_id}/attempts/{run.get('run_attempt')}"
    ))
    _validate_trusted_workflow_attempt(
        trusted, run, attempt, expected_head_sha=str(head),
        review_submitted_at=result.decision.submitted_at,
        merged_at=str(pr.get("merged_at")),
    )
    merge_tree = _git(root, "rev-parse", f"{r.get('merge_commit_sha')}^{{tree}}")
    approved_tree = _git(root, "rev-parse", f"{head}^{{tree}}")
    if merge_tree != approved_tree or merge_tree != r.get("head_tree_sha"):
        raise AuthorityReceiptError("AUTHORITY_MERGE_TREE_MISMATCH")
    _git(root, "merge-base", "--is-ancestor", str(r.get("merge_commit_sha")), "HEAD")
    require_pack_matches_approved_tree(root, str(head), PACK_FILES)
    return validate_pr312_authority_receipt(
        root, r, pull_request=_mapping(pr), review_decision=asdict(result.decision),
        trusted_status=_mapping(trusted), head_tree_sha=merge_tree,
    )
