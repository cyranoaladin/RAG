"""Le reçu #294 relie la review exacte à B sans autoriser la publication."""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from nexus_contracts import RetrievalScopeArtifactV3

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))
sys.path.insert(0, str(ROOT / "scripts/github"))

import pr294_scope_review_receipt as checker
from pr294_scope_review_receipt import (
    ScopeReviewReceiptError,
    build_pr294_scope_receipt,
    canonical_bytes,
    check_pr294_scope_review_receipt,
    validate_pr294_scope_receipt,
)
from trusted_human_review import build_challenge

ANCHOR = ROOT / "docs/reports/go_live/student_public_successor_content_anchor_20261010.json"
POLICY = ROOT / "governance/student_public_rights/student_public_successor_scope_policy_registry_v1.yml"
NAMES = ROOT / "packages/contracts/authorities/student-public-successor-scope-names-v1.yml"


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(document: dict) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def _fixture(tmp_path: Path) -> tuple[dict, bytes, dict, dict, dict, dict, dict[str, bytes], Path]:
    anchor = json.loads(ANCHOR.read_bytes())
    policy = yaml.safe_load(POLICY.read_bytes())
    policies = {row["collection"]: row for row in policy["collections"]}
    names = {row["collection"]: row["scope_id"]
             for row in yaml.safe_load(NAMES.read_bytes())["bindings"]}
    scope_dir = tmp_path / "scopes"
    scope_dir.mkdir()
    rows = []
    for subject in anchor["subjects"]:
        collection = subject["collection"]
        entry = policies[collection]
        artifact = RetrievalScopeArtifactV3.model_validate({
            "artifact_version": "3", "scope_id": names[collection],
            "status": "eligible_for_promotion",
            "source_sha256": subject["subject_sha256"],
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
            } | {"visibility": entry["policy_visibility"], "school_year": policy["school_year"]},
        })
        raw = artifact.canonical_bytes()
        (scope_dir / f"{names[collection]}.json").write_bytes(raw)
        rows.append({
            "collection": collection, "scope_id": names[collection],
            "resource": f"scopes/{names[collection]}.json",
            "sha256": _sha(raw), "source_sha256": subject["subject_sha256"],
            "artifact_version": "3",
        })
    registry = {
        "kind": "NEXUS_STUDENT_PUBLIC_SCOPE_REGISTRY_V1",
        "status": "SCOPES_ISSUED_NOT_PUBLICATION_AUTHORITY",
        "activation_allowed": False,
        "content_anchor_sha256": _sha(ANCHOR.read_bytes()),
        "content_manifest_sha256": anchor["content_manifest_sha256"],
        "policy_registry_sha256": _sha(POLICY.read_bytes()),
        "successor_authority_sha256": _sha(NAMES.read_bytes()),
        "scopes": rows,
    }
    registry_raw = _canonical(registry)
    head, base, tree, merge = "a" * 40, "b" * 40, "c" * 40, "d" * 40
    challenge = build_challenge({
        "protocol": "NEXUS-TRUSTED-REVIEW-V1", "repository": "cyranoaladin/RAG",
        "pull_request": 294, "base_ref": "main", "base_sha": base,
        "head_sha": head, "author": "scope-author", "reviewer": "abenrhouma",
    })
    status_url = "https://github.com/cyranoaladin/RAG/actions/runs/12345"
    receipt = {
        "kind": "PR294_STUDENT_PUBLIC_SCOPE_REVIEW_RECEIPT_V1",
        "status": "REVIEWED_SCOPES_NOT_PUBLICATION_AUTHORITY",
        "activation_allowed": False,
        "repository": "cyranoaladin/RAG", "pull_request": 294,
        "base_ref": "main", "base_sha": base, "head_sha": head,
        "head_tree_sha": tree, "merge_commit_sha": merge,
        "author": "scope-author", "reviewer": "abenrhouma",
        "review_id": 777, "challenge": challenge,
        "review_submitted_at": "2026-10-10T07:06:54Z",
        "trusted_status_context": "trusted-human-review/head-pinned",
        "trusted_status_created_at": "2026-10-10T07:08:51Z",
        "trusted_status_target_url": status_url,
        "workflow_run_id": 12345, "workflow_run_attempt": 1,
        "content_anchor_sha256": registry["content_anchor_sha256"],
        "content_manifest_sha256": registry["content_manifest_sha256"],
        "policy_registry_sha256": registry["policy_registry_sha256"],
        "successor_authority_sha256": registry["successor_authority_sha256"],
        "public_scope_authority_sha256": _sha(registry_raw),
        "scope_sha256_by_id": {row["scope_id"]: row["sha256"] for row in rows},
    }
    pr = {
        "number": 294, "state": "closed", "merged": True,
        "merged_at": "2026-10-10T07:09:11Z",
        "base": {"ref": "main", "sha": base}, "head": {"sha": head},
        "user": {"login": "scope-author"}, "merge_commit_sha": merge,
    }
    decision = {
        "approved": True, "reason": "approved", "base_sha": base,
        "head_sha": head, "reviewer": "abenrhouma", "review_id": 777,
        "challenge": challenge, "submitted_at": "2026-10-10T07:06:54Z",
    }
    trusted = {
        "context": "trusted-human-review/head-pinned", "state": "success",
        "created_at": "2026-10-10T07:08:51Z", "target_url": status_url,
    }
    run = {
        "id": 12345, "run_attempt": 1, "name": "Trusted human review",
        "path": ".github/workflows/trusted-human-review.yml",
        "event": "issue_comment", "status": "completed", "conclusion": "success",
        "head_sha": base, "created_at": "2026-10-10T07:08:35Z",
    }
    return receipt, registry_raw, pr, decision, trusted, run, {
        "anchor": ANCHOR.read_bytes(), "policy": POLICY.read_bytes(),
        "names": NAMES.read_bytes(),
    }, tmp_path


def _validate(fixture: tuple) -> dict:
    receipt, registry_raw, pr, decision, trusted, run, files, bundle_root = fixture
    return validate_pr294_scope_receipt(
        receipt, registry_raw, files, bundle_root,
        pull_request=pr, review_decision=decision,
        trusted_status=trusted, workflow_run=run,
        head_tree_sha=receipt["head_tree_sha"],
    )


def test_exact_review_of_eleven_v3_is_bound_but_not_publication_authority(tmp_path: Path) -> None:
    result = _validate(_fixture(tmp_path))
    assert result["PR294_SCOPE_REVIEW_PASS"] is True
    assert result["PUBLICATION_AUTHORIZED"] is False
    assert result["SCOPE_COUNT"] == 11


@pytest.mark.parametrize("sabotage", ["head", "challenge", "policy", "scope"])
def test_receipt_sabotage_fails_closed(tmp_path: Path, sabotage: str) -> None:
    parts = list(deepcopy(_fixture(tmp_path)))
    receipt = parts[0]
    if sabotage == "head":
        receipt["head_sha"] = "f" * 40
    elif sabotage == "challenge":
        receipt["challenge"] = "NEXUS-TRUSTED-REVIEW-V1:" + "f" * 64
    elif sabotage == "policy":
        receipt["policy_registry_sha256"] = "f" * 64
    else:
        scope_id = next(iter(receipt["scope_sha256_by_id"]))
        receipt["scope_sha256_by_id"][scope_id] = "f" * 64
    with pytest.raises(ScopeReviewReceiptError):
        _validate(tuple(parts))


@pytest.mark.parametrize("sabotage", ["not_merged", "status", "run", "tree", "index"])
def test_post_merge_or_external_proof_sabotage_fails_closed(
    tmp_path: Path, sabotage: str,
) -> None:
    parts = list(deepcopy(_fixture(tmp_path)))
    if sabotage == "not_merged":
        parts[2]["merged"] = False
    elif sabotage == "status":
        parts[4]["state"] = "failure"
    elif sabotage == "run":
        parts[5]["head_sha"] = "f" * 40
    elif sabotage == "tree":
        parts[0]["head_tree_sha"] = "f" * 40
    else:
        registry = json.loads(parts[1])
        registry["scopes"][0]["source_sha256"] = "f" * 64
        parts[1] = _canonical(registry)
    with pytest.raises(ScopeReviewReceiptError):
        validate_pr294_scope_receipt(
            parts[0], parts[1], parts[6], parts[7], pull_request=parts[2],
            review_decision=parts[3], trusted_status=parts[4],
            workflow_run=parts[5], head_tree_sha="c" * 40,
        )


def test_post_merge_builder_and_checker_replay_live_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    receipt, registry_raw, pr, decision, trusted, run, files, _bundle_root = _fixture(tmp_path)
    registry_path = tmp_path / "index.json"
    registry_path.write_bytes(registry_raw)
    receipt_path = tmp_path / "receipt.json"
    calls: list[str] = []

    def live(_root: Path) -> tuple:
        calls.append("github_git")
        return pr, decision, trusted, run, receipt["head_tree_sha"]

    def reviewed(_root: Path, _head: str) -> dict:
        calls.append("approved_tree")
        return files

    monkeypatch.setattr(checker, "_live_evidence", live)
    monkeypatch.setattr(checker, "_read_reviewed_files", reviewed)
    built = build_pr294_scope_receipt(tmp_path, registry_path, tmp_path)
    assert built == receipt
    receipt_path.write_bytes(canonical_bytes(built))
    assert check_pr294_scope_review_receipt(
        tmp_path, receipt_path, registry_path, tmp_path,
    )["PR294_SCOPE_REVIEW_PASS"] is True
    assert calls == ["github_git", "approved_tree", "github_git", "approved_tree"]
    trusted["state"] = "failure"
    with pytest.raises(ScopeReviewReceiptError):
        check_pr294_scope_review_receipt(tmp_path, receipt_path, registry_path, tmp_path)


@pytest.mark.parametrize("sabotage", ["missing", "altered", "aefe", "teacher", "tenant"])
def test_actual_v3_scope_file_or_student_policy_sabotage_fails_closed(
    tmp_path: Path, sabotage: str,
) -> None:
    parts = list(_fixture(tmp_path))
    registry = json.loads(parts[1])
    row = registry["scopes"][0]
    scope_path = tmp_path / row["resource"]
    if sabotage == "missing":
        scope_path.unlink()
    elif sabotage == "altered":
        scope_path.write_bytes(scope_path.read_bytes() + b"\n")
    else:
        artifact = RetrievalScopeArtifactV3.model_validate_json(scope_path.read_bytes())
        changed = artifact.model_dump(mode="json")
        if sabotage == "aefe":
            changed["target_policy"]["audiences"] = ["aefe"]
        elif sabotage == "teacher":
            changed["target_policy"]["roles"] = ["teacher"]
        else:
            changed["target_policy"]["tenant"] = "aefe_terminale"
        raw = RetrievalScopeArtifactV3.model_validate(changed).canonical_bytes()
        scope_path.write_bytes(raw)
        row["sha256"] = _sha(raw)
        parts[1] = _canonical(registry)
        parts[0]["public_scope_authority_sha256"] = _sha(parts[1])
        parts[0]["scope_sha256_by_id"][row["scope_id"]] = row["sha256"]
    with pytest.raises(ScopeReviewReceiptError):
        _validate(tuple(parts))
