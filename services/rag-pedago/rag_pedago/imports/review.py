from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from rag_pedago.imports.gate import GateStatus, build_gate_report
from rag_pedago.imports.quality import QualityPolicy


class ReviewStatus(str, Enum):
    ready_for_review = "ready_for_review"
    blocked_before_review = "blocked_before_review"
    approved = "approved"
    rejected = "rejected"


class ReviewPackage(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    batch_id: str
    status: ReviewStatus
    gate_status: str
    readiness_status: str
    coverage_status: str
    manifests_sha256: dict[str, str]
    gate_json_sha256: str
    readiness_json_sha256: str
    coverage_json_sha256: str
    official_reference_sha256: str
    taxonomy_sha256: dict[str, str]
    git_commit: str | None
    generated_at: datetime
    markdown_path: Path
    json_path: Path
    recommended_actions: list[str] = Field(default_factory=list)


class ReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    review_id: str
    batch_id: str
    decision: Literal["approved", "rejected"]
    reviewer: str
    reviewed_at: datetime
    review_package_sha256: str
    gate_json_sha256: str
    notes: str | None = None


class ReviewerPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    allowed_reviewers: list[str] = Field(default_factory=list)
    require_known_reviewer: bool = False


def _canonical_payload(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _canonical_payload(value.model_dump(mode="json"))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _canonical_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_canonical_payload(item) for item in value]
    return value


def canonical_json_bytes(model_or_dict: Any) -> bytes:
    return json.dumps(
        _canonical_payload(model_or_dict),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_canonical_json(model_or_dict: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(model_or_dict)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_directory_yaml(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.rglob("*.yml")):
        digest.update(str(path.relative_to(directory)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _manifest_paths(directory_path: Path) -> list[Path]:
    paths = sorted(path for path in directory_path.iterdir() if path.suffix == ".jsonl")
    if not paths:
        raise ValueError(f"no JSONL manifests found: {directory_path}")
    return paths


def _git_commit() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    return result.stdout.strip() or None


def _write_review_package_markdown(package: ReviewPackage) -> None:
    package.markdown_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_lines = "\n".join(
        f"- {path}: {digest}" for path, digest in package.manifests_sha256.items()
    ) or "- none"
    taxonomy_lines = "\n".join(
        f"- {path}: {digest}" for path, digest in package.taxonomy_sha256.items()
    ) or "- none"
    actions = "\n".join(f"- {action}" for action in package.recommended_actions) or "- none"
    content = f"""# Review Package — {package.batch_id}

## Review status

- status: {package.status.value}
- gate_status: {package.gate_status}
- readiness_status: {package.readiness_status}
- coverage_status: {package.coverage_status}

## Gate summary

- gate_json_sha256: {package.gate_json_sha256}
- readiness_json_sha256: {package.readiness_json_sha256}
- coverage_json_sha256: {package.coverage_json_sha256}

## Hashes

### Manifests

{manifest_lines}

### Reports

- readiness JSON: {package.readiness_json_sha256}
- coverage JSON: {package.coverage_json_sha256}
- gate JSON: {package.gate_json_sha256}

### Official reference

- data/reference: {package.official_reference_sha256}

### Taxonomies

{taxonomy_lines}

## Recommended actions

{actions}

## Guarantees

- No source_uri was opened.
- No document ingestion was performed.
- No network call was made.
"""
    package.markdown_path.write_text(content, encoding="utf-8")


def _write_review_package_json(package: ReviewPackage) -> None:
    package.json_path.parent.mkdir(parents=True, exist_ok=True)
    package.json_path.write_text(
        json.dumps(package.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_review_package(
    directory_path: Path,
    batch_id: str,
    taxonomy_paths: list[Path],
    policy: QualityPolicy,
    priority_notions: list[str] | None = None,
    output_dir: Path = Path("data/reports"),
    ledger_db_path: Path | None = None,
) -> ReviewPackage:
    gate_report = build_gate_report(
        directory_path=directory_path,
        batch_id=batch_id,
        taxonomy_paths=taxonomy_paths,
        policy=policy,
        priority_notions=priority_notions,
        output_dir=output_dir,
    )
    readiness_json = output_dir / f"readiness_{batch_id}.json"
    coverage_json = output_dir / f"coverage_{batch_id}.json"
    status = (
        ReviewStatus.ready_for_review
        if gate_report.status is GateStatus.ready_for_controlled_import
        else ReviewStatus.blocked_before_review
    )
    package = ReviewPackage(
        batch_id=batch_id,
        status=status,
        gate_status=gate_report.status.value,
        readiness_status=gate_report.readiness_status,
        coverage_status=gate_report.coverage_status,
        manifests_sha256={
            str(path): sha256_file(path) for path in _manifest_paths(directory_path)
        },
        gate_json_sha256=sha256_file(gate_report.json_path),
        readiness_json_sha256=sha256_file(readiness_json),
        coverage_json_sha256=sha256_file(coverage_json),
        official_reference_sha256=sha256_directory_yaml(Path("data/reference")),
        taxonomy_sha256={str(path): sha256_file(path) for path in taxonomy_paths},
        git_commit=_git_commit(),
        generated_at=datetime.now(UTC),
        markdown_path=output_dir / f"review_package_{batch_id}.md",
        json_path=output_dir / f"review_package_{batch_id}.json",
        recommended_actions=gate_report.recommended_actions,
    )
    _write_review_package_markdown(package)
    _write_review_package_json(package)
    if ledger_db_path is not None:
        from rag_pedago.ledger.migrations import initialize_database
        from rag_pedago.ledger.repository import LedgerRepository

        initialize_database(ledger_db_path)
        LedgerRepository(ledger_db_path).record_review_package(package)
    return package


def _load_review_package(path: Path) -> ReviewPackage:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"invalid review package JSON: {path}") from exc
    return ReviewPackage.model_validate(payload)


def approve_review_package(
    review_package_json: Path,
    reviewer: str,
    decision: str,
    notes: str | None = None,
    output_dir: Path = Path("data/reviews"),
    reviewer_policy: ReviewerPolicy | None = None,
    ledger_db_path: Path | None = None,
) -> ReviewDecision:
    if decision not in {"approved", "rejected"}:
        raise ValueError("decision must be approved or rejected")
    if not reviewer.strip():
        raise ValueError("reviewer is required")
    reviewer = reviewer.strip()
    policy = reviewer_policy or ReviewerPolicy()
    if policy.require_known_reviewer and reviewer not in policy.allowed_reviewers:
        raise ValueError("reviewer is not allowed by reviewer policy")

    package = _load_review_package(review_package_json)
    if decision == "approved" and package.status is ReviewStatus.blocked_before_review:
        raise ValueError("cannot approve review package with status blocked_before_review")

    review_id = f"{package.batch_id}-{uuid4().hex[:12]}"
    review = ReviewDecision(
        review_id=review_id,
        batch_id=package.batch_id,
        decision=decision,  # type: ignore[arg-type]
        reviewer=reviewer,
        reviewed_at=datetime.now(UTC),
        review_package_sha256=sha256_canonical_json(package),
        gate_json_sha256=package.gate_json_sha256,
        notes=notes,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    decision_path = output_dir / f"review_{review.review_id}.json"
    decision_path.write_text(
        json.dumps(review.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    registry_path = output_dir / "review_registry.jsonl"
    registry_entry = {
        "review_id": review.review_id,
        "batch_id": review.batch_id,
        "decision": review.decision,
        "reviewer": review.reviewer,
        "reviewed_at": review.reviewed_at.isoformat(),
        "review_decision_path": str(decision_path),
        "review_package_sha256": review.review_package_sha256,
        "gate_json_sha256": review.gate_json_sha256,
    }
    with registry_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(registry_entry, ensure_ascii=False, sort_keys=True) + "\n")
    if ledger_db_path is not None:
        from rag_pedago.ledger.migrations import initialize_database
        from rag_pedago.ledger.repository import LedgerRepository

        initialize_database(ledger_db_path)
        repo = LedgerRepository(ledger_db_path)
        if repo.get_review_package(package.batch_id) is None:
            repo.record_review_package(package)
        repo.record_review_decision(
            review,
            package_id=package.batch_id,
            decision_json_path=str(decision_path),
        )
    return review
