"""Reçu post-fusion #294 : revue exacte de B, sans autorité de publication.

Le reçu seul n'autorise rien. Sa création et sa vérification relisent GitHub,
le tree fusionné, les trois entrées revues et l'index collectif B. Le signer C
doit rejouer ``check_pr294_scope_review_receipt`` avant son propre scellement.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml
from nexus_contracts import RetrievalScopeArtifactV3
from pr300_authority_receipt import (
    AuthorityReceiptError,
    _git,
    _mapping,
    _read_gh,
    _select_trusted_status_at_merge,
    _utc,
    _validate_trusted_workflow_run,
)

GITHUB_DIR = Path(__file__).resolve().parents[1] / "github"
if str(GITHUB_DIR) not in sys.path:
    sys.path.insert(0, str(GITHUB_DIR))
from trusted_human_review import build_challenge

REPOSITORY = "cyranoaladin/RAG"
PR_NUMBER = 294
REVIEWER = "abenrhouma"
STATUS_CONTEXT = "trusted-human-review/head-pinned"
KIND = "PR294_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1"
STATUS = "REVIEWED_SCOPES_NOT_PUBLICATION_AUTHORITY"
FILES = {
    "anchor": "docs/reports/go_live/student_public_successor_content_anchor_20261010.json",
    "policy": "governance/student_public_rights/student_public_successor_scope_policy_registry_v1.yml",
    "names": "packages/contracts/authorities/student-public-successor-scope-names-v1.yml",
}
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
SCOPE_ID = re.compile(r"student_public_[a-z0-9_]+_v1\Z")
RUN_URL = re.compile(r"https://github\.com/cyranoaladin/RAG/actions/runs/([1-9][0-9]*)\Z")
KEYS = frozenset({
    "kind", "status", "activation_allowed", "repository", "pull_request",
    "base_ref", "base_sha", "head_sha", "head_tree_sha", "merge_commit_sha",
    "author", "reviewer", "review_id", "challenge", "review_submitted_at",
    "trusted_status_context", "trusted_status_created_at",
    "trusted_status_target_url", "workflow_run_id", "workflow_run_attempt",
    "content_anchor_sha256", "content_manifest_sha256",
    "policy_registry_sha256", "successor_authority_sha256",
    "public_scope_authority_sha256", "scope_sha256_by_id",
})


class ScopeReviewReceiptError(ValueError):
    """Le reçu ou une de ses preuves externes ne tient pas."""


def canonical_bytes(document: Mapping[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _is_sha(value: object, pattern: re.Pattern[str]) -> bool:
    return isinstance(value, str) and pattern.fullmatch(value) is not None


def _object(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ScopeReviewReceiptError(f"{label}: invalid JSON") from error
    if not isinstance(value, dict):
        raise ScopeReviewReceiptError(f"{label}: object required")
    return value


def _registry_population(
    raw: bytes, *, anchor: dict[str, Any], names: Mapping[str, str],
    receipt: Mapping[str, Any], policy: Mapping[str, Any], bundle_root: Path,
) -> dict[str, str]:
    registry = _object(raw, "scope registry")
    if raw != canonical_bytes(registry):
        raise ScopeReviewReceiptError("scope registry is not canonical JSON")
    subjects = anchor.get("subjects")
    if not isinstance(subjects, list) or len(subjects) != 11:
        raise ScopeReviewReceiptError("A subject population invalid")
    expected = {row.get("collection"): row.get("subject_sha256")
                for row in subjects if isinstance(row, dict)}
    policy_rows = policy.get("collections")
    if not isinstance(policy_rows, list):
        raise ScopeReviewReceiptError("reviewed scope policy population missing")
    policies = {row.get("collection"): row for row in policy_rows
                if isinstance(row, dict)}
    if (
        len(expected) != 11 or set(expected) != set(names)
        or len(policy_rows) != 11 or len(policies) != 11
        or set(policies) != set(expected)
        or policy.get("registry_kind") != "NEXUS_RETRIEVAL_SCOPE_POLICY_REGISTRY_V1"
        or policy.get("release_manifest_sha256") != receipt["content_manifest_sha256"]
        or policy.get("school_year") != "2026-2027"
    ):
        raise ScopeReviewReceiptError("A subject/naming population differs")
    if (
        set(registry) != {
            "kind", "status", "activation_allowed", "content_anchor_sha256",
            "content_manifest_sha256", "policy_registry_sha256",
            "successor_authority_sha256", "scopes",
        }
        or registry["kind"] != "NEXUS_STUDENT_PUBLIC_SCOPE_REGISTRY_V1"
        or registry["status"] != "SCOPES_ISSUED_NOT_PUBLICATION_AUTHORITY"
        or registry["activation_allowed"] is not False
        or any(registry.get(key) != receipt.get(key) for key in (
            "content_anchor_sha256", "content_manifest_sha256",
            "policy_registry_sha256", "successor_authority_sha256",
        ))
        or not isinstance(registry.get("scopes"), list)
        or len(registry["scopes"]) != 11
    ):
        raise ScopeReviewReceiptError("scope registry authority or population differs")
    rows = registry["scopes"]
    if rows != sorted(rows, key=lambda row: row.get("collection", "")
                      if isinstance(row, dict) else ""):
        raise ScopeReviewReceiptError("scope registry order differs")
    observed: dict[str, str] = {}
    collections: set[str] = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
            "collection", "scope_id", "resource", "sha256", "source_sha256",
            "artifact_version",
        }:
            raise ScopeReviewReceiptError("scope registry row invalid")
        collection, scope_id = row["collection"], row["scope_id"]
        if (
            not isinstance(collection, str) or collection not in expected
            or not isinstance(scope_id, str) or SCOPE_ID.fullmatch(scope_id) is None
            or scope_id != names[collection] or collection in collections
            or scope_id in observed
            or row["resource"] != f"scopes/{scope_id}.json"
            or row["artifact_version"] != "3"
            or not _is_sha(row["sha256"], SHA64)
            or row["source_sha256"] != expected[collection]
        ):
            raise ScopeReviewReceiptError("scope registry row differs from A/naming")
        collections.add(collection)
        observed[scope_id] = row["sha256"]
        entry = policies[collection]
        if (
            entry.get("decision_status") != "GOVERNED_BY_HUMAN_DECISION"
            or entry.get("authority_source") != "NEXUS_HUMAN_DECISION_ADR_0064"
            or entry.get("policy_source_scope_id") is not None
            or entry.get("subject_manifest_sha256") != expected[collection]
            or entry.get("rights") != ["public_allowed"]
            or entry.get("audiences") != ["libre", "aefe"]
            or entry.get("policy_visibility") != "public"
            or entry.get("evidence_visibility") != "public"
            or entry.get("target_audience") != "libre"
            or entry.get("target_candidates") != ["libre"]
        ):
            raise ScopeReviewReceiptError("reviewed ADR-0064 policy is not student public")
        scope_dir = bundle_root / "scopes"
        path = bundle_root / row["resource"]
        if (
            scope_dir.is_symlink() or path.is_symlink()
            or not path.resolve().is_relative_to(bundle_root.resolve())
            or not path.is_file()
        ):
            raise ScopeReviewReceiptError("V3 scope file missing or linked")
        try:
            scope_bytes = path.read_bytes()
            artifact = RetrievalScopeArtifactV3.model_validate_json(scope_bytes)
            expected_artifact = RetrievalScopeArtifactV3.model_validate({
                "artifact_version": "3", "scope_id": scope_id,
                "status": "eligible_for_promotion",
                "source_sha256": expected[collection],
                "target_policy": {
                    key: entry[key] for key in (
                        "tenant", "niveau", "voie", "matiere", "statut_enseignement",
                    )
                } | {
                    "audiences": [entry["target_audience"]],
                    "candidates": entry["target_candidates"], "roles": ["student"],
                },
                "evidence_subject": {
                    key: entry[key] for key in (
                        "collection", "tenant", "niveau", "voie", "matiere",
                        "statut_enseignement", "candidat", "audiences", "rights",
                        "programme_version",
                    )
                } | {
                    "visibility": entry["policy_visibility"],
                    "school_year": policy["school_year"],
                },
            })
        except (OSError, ValueError, KeyError, TypeError) as error:
            raise ScopeReviewReceiptError("V3 scope or policy invalid") from error
        if (
            _digest(scope_bytes) != row["sha256"]
            or artifact.canonical_bytes() != scope_bytes
            or artifact.canonical_bytes() != expected_artifact.canonical_bytes()
        ):
            raise ScopeReviewReceiptError("V3 scope bytes or student policy differ")
    if collections != set(expected) or observed != receipt.get("scope_sha256_by_id"):
        raise ScopeReviewReceiptError("reviewed scope digest population differs")
    return observed


def validate_pr294_scope_receipt(
    receipt: Mapping[str, Any], scope_registry_bytes: bytes,
    reviewed_files: Mapping[str, bytes], scope_bundle_root: Path, *,
    pull_request: Mapping[str, Any], review_decision: Mapping[str, Any],
    trusted_status: Mapping[str, Any], workflow_run: Mapping[str, Any],
    head_tree_sha: str,
) -> dict[str, Any]:
    """Validation déterministe ; le caller fournit des observations indépendantes."""
    r = receipt
    if (
        set(r) != KEYS or r.get("kind") != KIND or r.get("status") != STATUS
        or r.get("activation_allowed") is not False
        or r.get("repository") != REPOSITORY or r.get("pull_request") != PR_NUMBER
        or r.get("base_ref") != "main" or r.get("reviewer") != REVIEWER
        or type(r.get("review_id")) is not int or r["review_id"] <= 0
        or type(r.get("workflow_run_id")) is not int or r["workflow_run_id"] <= 0
        or type(r.get("workflow_run_attempt")) is not int
        or r["workflow_run_attempt"] <= 0
        or any(not _is_sha(r.get(key), SHA40) for key in (
            "base_sha", "head_sha", "head_tree_sha", "merge_commit_sha",
        ))
        or any(not _is_sha(r.get(key), SHA64) for key in (
            "content_anchor_sha256", "content_manifest_sha256",
            "policy_registry_sha256", "successor_authority_sha256",
            "public_scope_authority_sha256",
        ))
        or not isinstance(r.get("author"), str)
        or not isinstance(r.get("challenge"), str)
        or not isinstance(r.get("scope_sha256_by_id"), dict)
    ):
        raise ScopeReviewReceiptError("receipt shape or authority invalid")
    challenge = build_challenge({
        "protocol": "NEXUS-TRUSTED-REVIEW-V1", "repository": REPOSITORY,
        "pull_request": PR_NUMBER, "base_ref": r["base_ref"],
        "base_sha": r["base_sha"], "head_sha": r["head_sha"],
        "author": r["author"], "reviewer": REVIEWER,
    })
    if r["challenge"] != challenge:
        raise ScopeReviewReceiptError("challenge does not derive from exact PR revision")
    if set(reviewed_files) != set(FILES):
        raise ScopeReviewReceiptError("reviewed file population invalid")
    for label, key in (
        ("anchor", "content_anchor_sha256"),
        ("policy", "policy_registry_sha256"),
        ("names", "successor_authority_sha256"),
    ):
        if _digest(reviewed_files[label]) != r[key]:
            raise ScopeReviewReceiptError(f"reviewed {label} bytes differ")
    anchor = _object(reviewed_files["anchor"], "content anchor")
    names_doc = yaml.safe_load(reviewed_files["names"])
    policy_doc = yaml.safe_load(reviewed_files["policy"])
    if not isinstance(names_doc, dict) or not isinstance(names_doc.get("bindings"), list):
        raise ScopeReviewReceiptError("scope naming authority invalid")
    if not isinstance(policy_doc, dict):
        raise ScopeReviewReceiptError("scope policy invalid")
    names = {row.get("collection"): row.get("scope_id")
             for row in names_doc["bindings"] if isinstance(row, dict)}
    if (
        len(names_doc["bindings"]) != 11 or len(names) != 11
        or anchor.get("content_manifest_sha256") != r["content_manifest_sha256"]
        or _digest(scope_registry_bytes) != r["public_scope_authority_sha256"]
    ):
        raise ScopeReviewReceiptError("A/index digest or naming population differs")
    observed = _registry_population(
        scope_registry_bytes, anchor=anchor, names=names, receipt=r,
        policy=policy_doc, bundle_root=scope_bundle_root,
    )
    pr = pull_request
    if (
        pr.get("number") != PR_NUMBER or pr.get("state") != "closed"
        or pr.get("merged") is not True
        or pr.get("merge_commit_sha") != r["merge_commit_sha"]
        or not isinstance(pr.get("base"), dict)
        or pr["base"].get("ref") != r["base_ref"]
        or pr["base"].get("sha") != r["base_sha"]
        or not isinstance(pr.get("head"), dict)
        or pr["head"].get("sha") != r["head_sha"]
        or not isinstance(pr.get("user"), dict)
        or pr["user"].get("login") != r["author"]
        or head_tree_sha != r["head_tree_sha"]
    ):
        raise ScopeReviewReceiptError("merged PR/head/tree differs")
    decision = review_decision
    if (
        decision.get("approved") is not True or decision.get("reason") != "approved"
        or any(decision.get(key) != r[key] for key in (
            "base_sha", "head_sha", "reviewer", "review_id", "challenge",
        ))
        or decision.get("submitted_at") != r["review_submitted_at"]
    ):
        raise ScopeReviewReceiptError("exact-head review differs")
    status = trusted_status
    run = workflow_run
    if (
        status.get("context") != r["trusted_status_context"] == STATUS_CONTEXT
        or status.get("state") != "success"
        or status.get("created_at") != r["trusted_status_created_at"]
        or status.get("target_url") != r["trusted_status_target_url"]
        or run.get("id") != r["workflow_run_id"]
        or run.get("run_attempt") != r["workflow_run_attempt"]
    ):
        raise ScopeReviewReceiptError("trusted status or workflow run differs")
    match = RUN_URL.fullmatch(r["trusted_status_target_url"])
    if match is None or int(match.group(1)) != r["workflow_run_id"]:
        raise ScopeReviewReceiptError("trusted workflow target invalid")
    try:
        _validate_trusted_workflow_run(status, run, expected_base_sha=r["base_sha"])
        reviewed_at = _utc(r["review_submitted_at"])
        status_at = _utc(r["trusted_status_created_at"])
        merged_at = _utc(pr.get("merged_at"))
    except AuthorityReceiptError as error:
        raise ScopeReviewReceiptError("trusted workflow or timestamp invalid") from error
    if not reviewed_at <= status_at <= merged_at:
        raise ScopeReviewReceiptError("review/status outside merge window")
    return {
        "PR294_SCOPE_REVIEW_PASS": True,
        "PUBLICATION_AUTHORIZED": False,
        "SCOPE_COUNT": len(observed),
        "PUBLIC_SCOPE_AUTHORITY_SHA256": r["public_scope_authority_sha256"],
        "HEAD_SHA": r["head_sha"],
        "MERGE_COMMIT_SHA": r["merge_commit_sha"],
    }


def _read_reviewed_files(root: Path, head: str) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for label, relative in FILES.items():
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise ScopeReviewReceiptError(f"reviewed {label} file missing or symlink")
        if _git(root, "rev-parse", f"{head}:{relative}") != _git(
            root, "hash-object", "--", relative,
        ):
            raise ScopeReviewReceiptError(f"reviewed {label} differs from approved HEAD")
        files[label] = path.read_bytes()
    return files


def _live_evidence(root: Path) -> tuple[dict, dict, dict, dict, str]:
    from trusted_human_review_github import (
        DEFAULT_CONFIG_PATH,
        _evaluate_snapshot,
        load_config,
        run_gh_api,
    )

    pr = _read_gh(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    if not isinstance(pr, dict) or pr.get("state") != "closed" or pr.get("merged") is not True:
        raise ScopeReviewReceiptError("PR #294 is not merged")
    result = _evaluate_snapshot(
        pull_request={**pr, "state": "open", "draft": False},
        repository=REPOSITORY, pull_request_number=PR_NUMBER,
        config=load_config(DEFAULT_CONFIG_PATH), runner=run_gh_api,
    )
    readback = _read_gh(f"repos/{REPOSITORY}/pulls/{PR_NUMBER}")
    if not isinstance(readback, dict) or any(readback.get(key) != pr.get(key) for key in (
        "state", "merged", "merge_commit_sha", "base", "head",
    )):
        raise ScopeReviewReceiptError("PR changed during review replay")
    head = pr.get("head", {}).get("sha")
    if not _is_sha(head, SHA40):
        raise ScopeReviewReceiptError("PR head invalid")
    statuses = _mapping(_read_gh(f"repos/{REPOSITORY}/commits/{head}/status")).get(
        "statuses"
    )
    if not isinstance(statuses, list):
        raise ScopeReviewReceiptError("trusted status unavailable")
    trusted = _select_trusted_status_at_merge(statuses, str(pr.get("merged_at")))
    match = RUN_URL.fullmatch(str(trusted.get("target_url", "")))
    if match is None:
        raise ScopeReviewReceiptError("trusted workflow URL invalid")
    run = _read_gh(f"repos/{REPOSITORY}/actions/runs/{match.group(1)}")
    if not isinstance(run, dict):
        raise ScopeReviewReceiptError("trusted workflow unavailable")
    merge = pr.get("merge_commit_sha")
    if not _is_sha(merge, SHA40):
        raise ScopeReviewReceiptError("merge commit SHA invalid")
    merge_tree = _git(root, "rev-parse", f"{merge}^{{tree}}")
    approved_tree = _git(root, "rev-parse", f"{head}^{{tree}}")
    if merge_tree != approved_tree:
        raise ScopeReviewReceiptError("merge tree differs from approved HEAD")
    _git(root, "merge-base", "--is-ancestor", merge, "HEAD")
    return pr, asdict(result.decision), dict(trusted), run, merge_tree


def _read_registry(path: Path) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise ScopeReviewReceiptError("scope registry missing or symlink")
    return path.read_bytes()


def build_pr294_scope_receipt(
    root: Path, scope_registry_path: Path, scope_bundle_root: Path,
) -> dict[str, Any]:
    """Construire seulement après fusion et rejeu live de GitHub/git."""
    pr, decision, trusted, run, tree = _live_evidence(root)
    head = pr["head"]["sha"]
    files = _read_reviewed_files(root, head)
    registry_raw = _read_registry(scope_registry_path)
    registry = _object(registry_raw, "scope registry")
    rows = registry.get("scopes")
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ScopeReviewReceiptError("scope registry rows invalid")
    receipt = {
        "kind": KIND, "status": STATUS, "activation_allowed": False,
        "repository": REPOSITORY, "pull_request": PR_NUMBER,
        "base_ref": pr["base"]["ref"], "base_sha": pr["base"]["sha"],
        "head_sha": head, "head_tree_sha": tree,
        "merge_commit_sha": pr["merge_commit_sha"],
        "author": pr["user"]["login"], "reviewer": REVIEWER,
        "review_id": decision["review_id"], "challenge": decision["challenge"],
        "review_submitted_at": decision["submitted_at"],
        "trusted_status_context": trusted["context"],
        "trusted_status_created_at": trusted["created_at"],
        "trusted_status_target_url": trusted["target_url"],
        "workflow_run_id": run["id"], "workflow_run_attempt": run["run_attempt"],
        "content_anchor_sha256": _digest(files["anchor"]),
        "content_manifest_sha256": _object(files["anchor"], "A")["content_manifest_sha256"],
        "policy_registry_sha256": _digest(files["policy"]),
        "successor_authority_sha256": _digest(files["names"]),
        "public_scope_authority_sha256": _digest(registry_raw),
        "scope_sha256_by_id": {row.get("scope_id"): row.get("sha256") for row in rows},
    }
    validate_pr294_scope_receipt(
        receipt, registry_raw, files, scope_bundle_root, pull_request=pr,
        review_decision=decision, trusted_status=trusted,
        workflow_run=run, head_tree_sha=tree,
    )
    return receipt


def check_pr294_scope_review_receipt(
    root: Path, receipt_path: Path, scope_registry_path: Path,
    scope_bundle_root: Path,
) -> dict[str, Any]:
    """Rejouer GitHub live avant qu'un signer C accepte le reçu scellé."""
    receipt_raw = _read_registry(receipt_path)
    receipt = _object(receipt_raw, "scope review receipt")
    if receipt_raw != canonical_bytes(receipt):
        raise ScopeReviewReceiptError("scope review receipt is not canonical JSON")
    pr, decision, trusted, run, tree = _live_evidence(root)
    files = _read_reviewed_files(root, pr["head"]["sha"])
    return validate_pr294_scope_receipt(
        receipt, _read_registry(scope_registry_path), files, scope_bundle_root,
        pull_request=pr, review_decision=decision,
        trusted_status=trusted, workflow_run=run, head_tree_sha=tree,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--scope-registry", type=Path, required=True)
    parser.add_argument("--scope-bundle-root", type=Path, required=True)
    operation = parser.add_mutually_exclusive_group(required=True)
    operation.add_argument("--write-receipt", type=Path)
    operation.add_argument("--check-receipt", type=Path)
    args = parser.parse_args()
    try:
        if args.write_receipt:
            receipt = build_pr294_scope_receipt(
                args.repo_root, args.scope_registry, args.scope_bundle_root,
            )
            if args.write_receipt.exists() or args.write_receipt.is_symlink():
                raise ScopeReviewReceiptError("receipt target already exists")
            args.write_receipt.parent.mkdir(parents=True, exist_ok=True)
            args.write_receipt.write_bytes(canonical_bytes(receipt))
            verdict = check_pr294_scope_review_receipt(
                args.repo_root, args.write_receipt, args.scope_registry,
                args.scope_bundle_root,
            )
        else:
            verdict = check_pr294_scope_review_receipt(
                args.repo_root, args.check_receipt, args.scope_registry,
                args.scope_bundle_root,
            )
    except (ScopeReviewReceiptError, AuthorityReceiptError, OSError, KeyError,
            TypeError, ValueError) as error:
        parser.exit(2, f"PR294 scope review receipt refused: {error}\n")
    print(json.dumps(verdict, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
