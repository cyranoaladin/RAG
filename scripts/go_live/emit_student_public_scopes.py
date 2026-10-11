"""Émettre les scopes V3 après rejeu live de A et review exacte de #294.

Le CLI de contrats reste fermé aux scopes étudiants. Cet orchestrateur est le
seul chemin prévu pour transmettre les verdicts externes au constructeur pur.
Il n'autorise ni ingestion, ni publication, ni accès student au runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from check_public_successor_preissuance import (
    PreissuanceVerdict,
    verify_preissuance_authority,
)

REPOSITORY = "cyranoaladin/RAG"
PR_NUMBER = 294
REVIEWER = "abenrhouma"
STATUS_CONTEXT = "trusted-human-review/head-pinned"


class StudentPublicScopeEmissionError(ValueError):
    """Les preuves de pré-émission ou de review ne permettent pas d'écrire."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class ScopePolicyReviewEvidence:
    head_sha: str
    tree_sha: str
    checkout_head_sha: str
    reviewer: str
    policy_registry_sha256: str
    successor_authority_sha256: str
    content_anchor_sha256: str
    review_pr_number: int = 294


def _sha(path: Path) -> str:
    try:
        if path.is_symlink() or not path.is_file():
            raise StudentPublicScopeEmissionError(f"missing or linked authority: {path.name}")
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise StudentPublicScopeEmissionError(f"unreadable authority: {path.name}") from error


def _git(root: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, text=True, capture_output=True,
            check=False, timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise StudentPublicScopeEmissionError("exact-head Git binding unavailable") from error
    if result.returncode != 0:
        raise StudentPublicScopeEmissionError("exact-head Git binding unavailable")
    return result.stdout.strip()


def _require_current_clean_main(root: Path) -> str:
    head = _git(root, "rev-parse", "HEAD")
    tracking = _git(root, "rev-parse", "origin/main")
    live = _git(root, "ls-remote", "--exit-code", "origin", "refs/heads/main")
    if (
        head != tracking or live != f"{head}\trefs/heads/main"
        or _git(root, "status", "--porcelain")
    ):
        raise StudentPublicScopeEmissionError("checkout is not clean current origin/main")
    return head


def _require_file_at_head(root: Path, path: Path, expected_sha256: str) -> None:
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or path.is_symlink():
        raise StudentPublicScopeEmissionError("reviewed authority escapes repository")
    relative = str(resolved.relative_to(root.resolve()))
    if _sha(path) != expected_sha256:
        raise StudentPublicScopeEmissionError("reviewed authority digest differs")
    if _git(root, "rev-parse", f"HEAD:{relative}") != _git(
        root, "hash-object", "--", relative,
    ):
        raise StudentPublicScopeEmissionError("authority bytes differ from reviewed HEAD")


def verify_live_scope_policy_review(
    repo_root: Path, policy_registry: Path, policy_registry_sha256: str,
    successor_authority: Path, successor_authority_sha256: str,
    anchor_path: Path, anchor_sha256: str, *, review_pr_number: int = 294,
) -> ScopePolicyReviewEvidence:
    """Rejouer la PR de scope explicitement choisie sur main courant."""
    root = repo_root.resolve()
    head = _require_current_clean_main(root)
    from pr294_scope_review_receipt import (
        REVIEW_BINDINGS,
        _live_evidence,
        _read_reviewed_files,
    )
    binding = REVIEW_BINDINGS.get(review_pr_number)
    if binding is None:
        raise StudentPublicScopeEmissionError("unknown exact-head scope review PR")
    pr, decision, _status, _run, tree = (
        _live_evidence(root) if review_pr_number == 294 else _live_evidence(root, binding)
    )
    reviewed_head = pr["head"]["sha"]
    if (
        decision.get("approved") is not True
        or decision.get("head_sha") != reviewed_head
        or decision.get("reviewer") != REVIEWER
    ):
        raise StudentPublicScopeEmissionError("exact-head scope policy review absent")
    reviewed_files = (_read_reviewed_files(root, reviewed_head)
                      if review_pr_number == 294 else
                      _read_reviewed_files(root, reviewed_head, binding))
    for path, digest in (
        (policy_registry, policy_registry_sha256),
        (successor_authority, successor_authority_sha256),
        (anchor_path, anchor_sha256),
    ):
        _require_file_at_head(root, path, digest)
    for label, path, digest in (
        ("policy", policy_registry, policy_registry_sha256),
        ("names", successor_authority, successor_authority_sha256),
        ("anchor", anchor_path, anchor_sha256),
    ):
        if path.resolve() != (root / binding.files[label]).resolve() or hashlib.sha256(
            reviewed_files[label]
        ).hexdigest() != digest:
            raise StudentPublicScopeEmissionError("reviewed authority path or bytes differ")
    return ScopePolicyReviewEvidence(
        reviewed_head, tree, head, REVIEWER, policy_registry_sha256,
        successor_authority_sha256, anchor_sha256, review_pr_number,
    )


def emit_student_public_scopes(
    *,
    anchor_path: Path,
    anchor_sha256: str,
    subject_release: Path,
    subject_release_sha256: str,
    preissuance_receipt: Path,
    preissuance_receipt_sha256: str,
    private_cas_root: Path,
    policy_registry: Path,
    policy_registry_sha256: str,
    successor_authority: Path,
    successor_authority_sha256: str,
    artifacts_dir: Path,
    repo_root: Path,
    now_utc: datetime | None = None,
    preissuance_verifier: Callable[..., PreissuanceVerdict] = verify_preissuance_authority,
    policy_review_verifier: Callable[..., ScopePolicyReviewEvidence] = verify_live_scope_policy_review,
    scope_emitter: Callable[..., Any] | None = None,
    scope_review_pr_number: int = 294,
) -> Any:
    """Vérifier deux autorités indépendantes avant la première écriture."""
    now = now_utc or datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() != UTC.utcoffset(now):
        raise StudentPublicScopeEmissionError("now_utc must be UTC aware")
    try:
        pre = preissuance_verifier(
            anchor_path, anchor_sha256, subject_release_sha256,
            preissuance_receipt, preissuance_receipt_sha256, repo_root,
            private_cas_root, now,
        )
    except (ValueError, OSError, RuntimeError) as error:
        raise StudentPublicScopeEmissionError("preissuance replay refused") from error
    if (
        not isinstance(pre, PreissuanceVerdict)
        or pre.preissuance_verified is not True
        or pre.publication_authorized is not False
        or pre.content_anchor_sha256 != anchor_sha256
        or pre.content_manifest_sha256 != subject_release_sha256
        or pre.expires_at_utc.tzinfo is None
        or pre.expires_at_utc.utcoffset() != UTC.utcoffset(pre.expires_at_utc)
        or now >= pre.expires_at_utc
        or len(pre.subject_sha256_by_collection) != 11
    ):
        raise StudentPublicScopeEmissionError("preissuance verdict differs or expired")
    try:
        review_args = (
            repo_root, policy_registry, policy_registry_sha256,
            successor_authority, successor_authority_sha256,
            anchor_path, anchor_sha256,
        )
        review = (policy_review_verifier(*review_args)
                  if scope_review_pr_number == 294 else
                  policy_review_verifier(*review_args, review_pr_number=scope_review_pr_number))
    except (ValueError, OSError, RuntimeError) as error:
        raise StudentPublicScopeEmissionError("exact-head policy review refused") from error
    head = _git(repo_root, "rev-parse", "HEAD")
    if (
        not isinstance(review, ScopePolicyReviewEvidence)
        or review.checkout_head_sha != head
        or review.reviewer != REVIEWER
        or review.policy_registry_sha256 != policy_registry_sha256
        or review.successor_authority_sha256 != successor_authority_sha256
        or review.content_anchor_sha256 != anchor_sha256
        or review.review_pr_number != scope_review_pr_number
        or _sha(anchor_path) != anchor_sha256
    ):
        raise StudentPublicScopeEmissionError("scope review or anchor differs")
    contracts_scripts = repo_root / "packages/contracts/scripts"
    if str(contracts_scripts) not in sys.path:
        sys.path.insert(0, str(contracts_scripts))
    from build_retrieval_scope_artifacts import (
        StudentScopeEmissionEvidence,
        emit_from_policy_registry,
    )

    emit = scope_emitter or emit_from_policy_registry
    if _require_current_clean_main(repo_root) != review.checkout_head_sha:
        raise StudentPublicScopeEmissionError("main moved after scope policy review")
    fresh_now = _utc_now()
    if (
        fresh_now.tzinfo is None
        or fresh_now.utcoffset() != UTC.utcoffset(fresh_now)
        or fresh_now >= pre.expires_at_utc
    ):
        raise StudentPublicScopeEmissionError("source currentness expired before scope write")
    return emit(
        subject_release=subject_release,
        subject_release_sha256=subject_release_sha256,
        policy_registry=policy_registry,
        policy_registry_sha256=policy_registry_sha256,
        successor_authority=successor_authority,
        successor_authority_sha256=successor_authority_sha256,
        artifacts_dir=artifacts_dir,
        repo_root=repo_root,
        student_scope_evidence=StudentScopeEmissionEvidence(
            content_anchor_sha256=anchor_sha256,
            content_manifest_sha256=subject_release_sha256,
            subject_sha256_by_collection=pre.subject_sha256_by_collection,
            expires_at_utc=pre.expires_at_utc,
            reviewed_policy_registry_sha256=review.policy_registry_sha256,
            reviewed_successor_authority_sha256=review.successor_authority_sha256,
            reviewed_head_sha=review.head_sha,
        ),
    )


def build_public_scope_registry(
    result: Any,
    anchor_path: Path,
    anchor_sha256: str,
    manifest_sha256: str,
    policy_registry_sha256: str,
    successor_authority_sha256: str,
) -> dict[str, Any]:
    """Décrire les onze V3 pour C, sans créer une autorité de publication.

    Le futur bundle place les octets *canoniques* de chaque V3 sous
    ``scopes/<scope_id>.json``. Les fichiers lisibles écrits par l'émetteur
    ne sont pas les octets adressés par ce registre.
    """
    if _sha(anchor_path) != anchor_sha256:
        raise StudentPublicScopeEmissionError("content anchor digest differs")
    try:
        anchor = json.loads(anchor_path.read_bytes())
        subjects = anchor["subjects"]
        expected = {row["collection"]: row["subject_sha256"] for row in subjects}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise StudentPublicScopeEmissionError("content anchor is invalid") from error
    if (
        anchor.get("kind") != "NEXUS_PUBLIC_SUCCESSOR_CONTENT_ANCHOR_V1"
        or anchor.get("content_manifest_sha256") != manifest_sha256
        or len(subjects) != 11 or len(expected) != 11
        or not all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in expected.values())
        or not all(re.fullmatch(r"[0-9a-f]{64}", sha) for sha in (
            anchor_sha256, manifest_sha256, policy_registry_sha256,
            successor_authority_sha256,
        ))
        or getattr(result, "reused", None) != ()
        or len(getattr(result, "emitted", ())) != 11
    ):
        raise StudentPublicScopeEmissionError("scope population or authority differs")
    scopes: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for item in result.emitted:
        artifact = item.artifact
        scope_id = item.scope_id
        collection = item.collection
        if (
            collection not in expected
            or scope_id in seen_ids
            or not re.fullmatch(r"student_public_[a-z0-9_]+_v1", scope_id)
            or artifact.artifact_version != "3"
            or artifact.scope_id != scope_id
            or artifact.status != "eligible_for_promotion"
            or artifact.evidence_subject.collection != collection
            or artifact.source_sha256 != expected[collection]
            or artifact.target_policy.roles != ["student"]
            or artifact.target_policy.audiences != ["libre"]
            or artifact.evidence_subject.visibility != "public"
            or [right.value for right in artifact.evidence_subject.rights] != ["public_allowed"]
        ):
            raise StudentPublicScopeEmissionError("V3 scope differs from content anchor")
        seen_ids.add(scope_id)
        scopes.append({
            "collection": collection,
            "scope_id": scope_id,
            "resource": f"scopes/{scope_id}.json",
            "sha256": artifact.sha256_digest(),
            "source_sha256": artifact.source_sha256,
            "artifact_version": "3",
        })
    if {row["collection"] for row in scopes} != set(expected):
        raise StudentPublicScopeEmissionError("V3 scope population incomplete")
    return {
        "kind": "NEXUS_STUDENT_PUBLIC_SCOPE_REGISTRY_V1",
        "status": "SCOPES_ISSUED_NOT_PUBLICATION_AUTHORITY",
        "activation_allowed": False,
        "content_anchor_sha256": anchor_sha256,
        "content_manifest_sha256": manifest_sha256,
        "policy_registry_sha256": policy_registry_sha256,
        "successor_authority_sha256": successor_authority_sha256,
        "scopes": sorted(scopes, key=lambda row: row["collection"]),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for field in (
        "anchor-path", "subject-release", "preissuance-receipt",
        "private-cas-root", "policy-registry", "successor-authority",
        "artifacts-dir", "repo-root",
    ):
        parser.add_argument(f"--{field}", type=Path, required=True)
    for field in (
        "anchor-sha256", "subject-release-sha256",
        "preissuance-receipt-sha256", "policy-registry-sha256",
        "successor-authority-sha256",
    ):
        parser.add_argument(f"--{field}", required=True)
    parser.add_argument("--scope-review-pr-number", type=int, choices=[294, 330], default=294)
    args = parser.parse_args()
    try:
        result = emit_student_public_scopes(**vars(args))
    except (StudentPublicScopeEmissionError, OSError) as error:
        parser.exit(2, f"student public scope emission refused: {error}\n")
    print(json.dumps({
        "emitted": [item.scope_id for item in result.emitted],
        "reused": [item.scope_id for item in result.reused],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
