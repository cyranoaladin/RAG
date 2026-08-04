#!/usr/bin/env python3
"""Décision pure et challenge canonique d'une revue GitHub indépendante."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
import re


PROTOCOL = "NEXUS-TRUSTED-REVIEW-V1"
EXPECTED_REPOSITORY = "cyranoaladin/RAG"
EXPECTED_BASE_REF = "main"

_CONFIG_KEYS = {"protocol", "repository", "base_ref", "reviewers"}
_CHALLENGE_KEYS = {
    "repository",
    "pull_request",
    "base_ref",
    "base_sha",
    "head_sha",
    "author",
    "reviewer",
    "protocol",
}
_SHA_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_LOGIN_PATTERN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?\Z")
_BOT_LOGIN_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,93}[A-Za-z0-9])?\[bot\]\Z"
)
_TIMESTAMP_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z\Z")
_REVIEW_STATES = {
    "APPROVED",
    "CHANGES_REQUESTED",
    "COMMENTED",
    "DISMISSED",
    "PENDING",
}
_WRITE_PERMISSIONS = {"write", "admin"}
_WRITE_ROLES = {"write", "maintain", "admin"}


@dataclass(frozen=True)
class TrustedReviewerConfig:
    """Configuration versionnée de la frontière de confiance GitHub."""

    protocol: str
    repository: str
    base_ref: str
    reviewers: tuple[str, ...]


@dataclass(frozen=True)
class TrustedReviewDecision:
    """Verdict normalisé lié à un head GitHub exact."""

    approved: bool
    reason: str
    repository: str
    pull_request: int
    base_sha: str
    head_sha: str
    reviewer: str | None = None
    review_id: int | None = None
    submitted_at: str | None = None
    challenge: str | None = None


def _require_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(
        isinstance(key, str) for key in value
    ):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _require_exact_keys(
    value: Mapping[str, object], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        raise ValueError(
            f"{label} keys differ: "
            f"missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _require_literal(value: object, expected: str, label: str) -> str:
    if value != expected:
        raise ValueError(f"{label} must equal {expected!r}")
    return expected


def _require_login(value: object, label: str) -> str:
    if not isinstance(value, str) or _LOGIN_PATTERN.fullmatch(value) is None:
        raise TypeError(f"{label} must be a valid non-empty GitHub login")
    return value


def _require_actor_login(value: object, label: str) -> str:
    if not isinstance(value, str) or (
        _LOGIN_PATTERN.fullmatch(value) is None
        and _BOT_LOGIN_PATTERN.fullmatch(value) is None
    ):
        raise TypeError(f"{label} must be a valid non-empty GitHub actor login")
    return value


def _require_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA_PATTERN.fullmatch(value) is None:
        raise TypeError(f"{label} must contain 40 lowercase hexadecimal characters")
    return value


def load_config(path: Path) -> TrustedReviewerConfig:
    """Charge strictement l'allowlist versionnée des reviewers."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load trusted reviewer config {path}: {exc}") from exc

    document = _require_mapping(raw, "trusted reviewer config")
    _require_exact_keys(document, _CONFIG_KEYS, "trusted reviewer config")
    protocol = _require_literal(document["protocol"], PROTOCOL, "protocol")
    repository = _require_literal(
        document["repository"], EXPECTED_REPOSITORY, "repository"
    )
    base_ref = _require_literal(document["base_ref"], EXPECTED_BASE_REF, "base_ref")

    raw_reviewers = document["reviewers"]
    if not isinstance(raw_reviewers, list) or not raw_reviewers:
        raise TypeError("reviewers must be a non-empty list")
    reviewers = tuple(
        _require_login(reviewer, f"reviewers[{index}]")
        for index, reviewer in enumerate(raw_reviewers)
    )
    if len(reviewers) != len(set(reviewers)):
        raise ValueError("reviewers contains duplicates")

    return TrustedReviewerConfig(
        protocol=protocol,
        repository=repository,
        base_ref=base_ref,
        reviewers=reviewers,
    )


def validate_challenge_payload(value: object) -> dict[str, object]:
    """Valide et normalise les seules dimensions liées au challenge."""

    document = _require_mapping(value, "challenge payload")
    _require_exact_keys(document, _CHALLENGE_KEYS, "challenge payload")
    pull_request = document["pull_request"]
    if type(pull_request) is not int or pull_request <= 0:
        raise TypeError("pull_request must be a positive integer")

    return {
        "repository": _require_literal(
            document["repository"], EXPECTED_REPOSITORY, "repository"
        ),
        "pull_request": pull_request,
        "base_ref": _require_literal(
            document["base_ref"], EXPECTED_BASE_REF, "base_ref"
        ),
        "base_sha": _require_sha(document["base_sha"], "base_sha"),
        "head_sha": _require_sha(document["head_sha"], "head_sha"),
        "author": _require_actor_login(document["author"], "author"),
        "reviewer": _require_login(document["reviewer"], "reviewer"),
        "protocol": _require_literal(document["protocol"], PROTOCOL, "protocol"),
    }


def canonical_json(value: Mapping[str, object]) -> bytes:
    """Sérialise un mapping validé de façon déterministe."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def build_challenge(payload: Mapping[str, object]) -> str:
    """Construit le challenge public lié à une PR et son head exact."""

    validated = validate_challenge_payload(payload)
    return f"{PROTOCOL}:{sha256(canonical_json(validated)).hexdigest()}"


def _require_positive_int(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise TypeError(f"{label} must be a positive integer")
    return value


def _require_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise TypeError(f"{label} must be a non-empty string")
    return value


def _pull_request_dimensions(value: object) -> dict[str, object]:
    document = _require_mapping(value, "pull request")
    number = _require_positive_int(document.get("number"), "pull request.number")
    state = _require_string(document.get("state"), "pull request.state")
    draft = document.get("draft")
    if type(draft) is not bool:
        raise TypeError("pull request.draft must be a boolean")

    base = _require_mapping(document.get("base"), "pull request.base")
    base_ref = _require_string(base.get("ref"), "pull request.base.ref")
    base_sha = _require_sha(base.get("sha"), "pull request.base.sha")

    head = _require_mapping(document.get("head"), "pull request.head")
    head_sha = _require_sha(head.get("sha"), "pull request.head.sha")
    head_repo = _require_mapping(head.get("repo"), "pull request.head.repo")
    head_repository = _require_string(
        head_repo.get("full_name"), "pull request.head.repo.full_name"
    )

    user = _require_mapping(document.get("user"), "pull request.user")
    author = _require_actor_login(
        user.get("login"), "pull request.user.login"
    )
    return {
        "number": number,
        "state": state,
        "draft": draft,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "head_repository": head_repository,
        "author": author,
    }


def _validated_reviews(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise TypeError("reviews must be a JSON list")
    normalized: list[dict[str, object]] = []
    for index, raw_review in enumerate(value):
        review = _require_mapping(raw_review, f"reviews[{index}]")
        review_id = _require_positive_int(review.get("id"), f"reviews[{index}].id")
        state = _require_string(review.get("state"), f"reviews[{index}].state")
        if state not in _REVIEW_STATES:
            raise ValueError(f"reviews[{index}].state is unsupported")
        body = review.get("body")
        if body is None:
            body = ""
        if not isinstance(body, str):
            raise TypeError(f"reviews[{index}].body must be a string or null")
        commit_id = _require_sha(
            review.get("commit_id"), f"reviews[{index}].commit_id"
        )
        submitted_at = _require_string(
            review.get("submitted_at"), f"reviews[{index}].submitted_at"
        )
        if _TIMESTAMP_PATTERN.fullmatch(submitted_at) is None:
            raise ValueError(f"reviews[{index}].submitted_at must be canonical UTC")
        user = _require_mapping(review.get("user"), f"reviews[{index}].user")
        reviewer = _require_actor_login(
            user.get("login"), f"reviews[{index}].user.login"
        )
        normalized.append(
            {
                "id": review_id,
                "state": state,
                "body": body,
                "commit_id": commit_id,
                "submitted_at": submitted_at,
                "reviewer": reviewer,
            }
        )
    return normalized


def _validated_permissions(value: object) -> dict[str, dict[str, str]]:
    document = _require_mapping(value, "permissions")
    normalized: dict[str, dict[str, str]] = {}
    for raw_login, raw_permission in document.items():
        login = _require_login(raw_login, "permissions login")
        permission = _require_mapping(raw_permission, f"permissions[{login}]")
        normalized[login] = {
            "permission": _require_string(
                permission.get("permission"), f"permissions[{login}].permission"
            ),
            "role_name": _require_string(
                permission.get("role_name"), f"permissions[{login}].role_name"
            ),
        }
    return normalized


def build_expected_challenges(
    pull_request: object, config: TrustedReviewerConfig
) -> dict[str, str]:
    """Dérive les challenges des reviewers depuis une PR validée."""

    if not isinstance(config, TrustedReviewerConfig):
        raise TypeError("config must be a TrustedReviewerConfig")
    pr = _pull_request_dimensions(pull_request)
    return {
        reviewer: build_challenge(
            {
                "repository": config.repository,
                "pull_request": pr["number"],
                "base_ref": config.base_ref,
                "base_sha": pr["base_sha"],
                "head_sha": pr["head_sha"],
                "author": pr["author"],
                "reviewer": reviewer,
                "protocol": config.protocol,
            }
        )
        for reviewer in config.reviewers
    }


def _decision(
    *,
    approved: bool,
    reason: str,
    config: TrustedReviewerConfig,
    pull_request: Mapping[str, object],
    reviewer: str | None = None,
    review: Mapping[str, object] | None = None,
    challenge: str | None = None,
) -> TrustedReviewDecision:
    return TrustedReviewDecision(
        approved=approved,
        reason=reason,
        repository=config.repository,
        pull_request=int(pull_request["number"]),
        base_sha=str(pull_request["base_sha"]),
        head_sha=str(pull_request["head_sha"]),
        reviewer=reviewer,
        review_id=int(review["id"]) if review is not None else None,
        submitted_at=(
            str(review["submitted_at"]) if review is not None else None
        ),
        challenge=challenge,
    )


def evaluate_trusted_review(
    *,
    pull_request: object,
    reviews: object,
    permissions: object,
    config: TrustedReviewerConfig,
    reviews_complete: bool,
) -> TrustedReviewDecision:
    """Évalue une review GitHub sans réseau et refuse toute ambiguïté."""

    if not isinstance(config, TrustedReviewerConfig):
        raise TypeError("config must be a TrustedReviewerConfig")
    if type(reviews_complete) is not bool:
        raise TypeError("reviews_complete must be a boolean")
    pr = _pull_request_dimensions(pull_request)
    normalized_reviews = _validated_reviews(reviews)
    normalized_permissions = _validated_permissions(permissions)

    review_ids = [int(review["id"]) for review in normalized_reviews]
    if len(review_ids) != len(set(review_ids)):
        return _decision(
            approved=False,
            reason="duplicate_review_id",
            config=config,
            pull_request=pr,
        )
    if not reviews_complete:
        return _decision(
            approved=False,
            reason="reviews_incomplete",
            config=config,
            pull_request=pr,
        )
    if pr["state"] != "open":
        return _decision(
            approved=False,
            reason="pull_request_not_open",
            config=config,
            pull_request=pr,
        )
    if pr["draft"] is True:
        return _decision(
            approved=False,
            reason="pull_request_is_draft",
            config=config,
            pull_request=pr,
        )
    if pr["base_ref"] != config.base_ref:
        return _decision(
            approved=False,
            reason="base_ref_mismatch",
            config=config,
            pull_request=pr,
        )
    if pr["head_repository"] != config.repository:
        return _decision(
            approved=False,
            reason="head_repository_mismatch",
            config=config,
            pull_request=pr,
        )

    insufficient_permission = False
    reviewer_is_author = False
    for reviewer in config.reviewers:
        if reviewer == pr["author"]:
            reviewer_is_author = True
            continue
        permission = normalized_permissions.get(reviewer)
        if permission is None or (
            permission["permission"] not in _WRITE_PERMISSIONS
            or permission["role_name"] not in _WRITE_ROLES
        ):
            insufficient_permission = True
            continue

        challenge = build_expected_challenges(pull_request, config)[reviewer]
        reviewer_reviews = sorted(
            (
                review
                for review in normalized_reviews
                if review["reviewer"] == reviewer
            ),
            key=lambda review: (str(review["submitted_at"]), int(review["id"])),
        )
        approvals = [
            review
            for review in reviewer_reviews
            if review["state"] == "APPROVED"
            and review["commit_id"] == pr["head_sha"]
            and challenge in str(review["body"]).splitlines()
        ]
        if not approvals:
            continue
        approval = approvals[-1]
        approval_key = (str(approval["submitted_at"]), int(approval["id"]))
        if any(
            (str(review["submitted_at"]), int(review["id"])) > approval_key
            and review["state"] in {"CHANGES_REQUESTED", "DISMISSED"}
            for review in reviewer_reviews
        ):
            return _decision(
                approved=False,
                reason="approval_revoked",
                config=config,
                pull_request=pr,
                reviewer=reviewer,
                challenge=challenge,
            )
        return _decision(
            approved=True,
            reason="approved",
            config=config,
            pull_request=pr,
            reviewer=reviewer,
            review=approval,
            challenge=challenge,
        )

    if reviewer_is_author:
        reason = "reviewer_is_author"
    elif insufficient_permission:
        reason = "reviewer_permission_insufficient"
    else:
        reason = "current_head_approval_missing"
    return _decision(
        approved=False,
        reason=reason,
        config=config,
        pull_request=pr,
    )
