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


@dataclass(frozen=True)
class TrustedReviewerConfig:
    """Configuration versionnée de la frontière de confiance GitHub."""

    protocol: str
    repository: str
    base_ref: str
    reviewers: tuple[str, ...]


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
        "author": _require_login(document["author"], "author"),
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
