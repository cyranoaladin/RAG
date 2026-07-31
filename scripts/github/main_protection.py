#!/usr/bin/env python3
"""Vérifie ou applique la politique versionnée de protection de ``main``."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
import difflib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any


GITHUB_API_VERSION = "2026-03-10"
GH_API_TIMEOUT_SECONDS = 30
DEFAULT_POLICY_PATH = Path(__file__).with_name("main-protection-policy.json")
Runner = Callable[..., dict[str, object] | str]

_TOP_LEVEL_KEYS = {
    "required_status_checks",
    "enforce_admins",
    "required_pull_request_reviews",
    "restrictions",
    "required_linear_history",
    "allow_force_pushes",
    "allow_deletions",
    "block_creations",
    "required_conversation_resolution",
    "lock_branch",
    "allow_fork_syncing",
}
_STATUS_KEYS = {"strict", "contexts"}
_REVIEW_KEYS = {
    "dismiss_stale_reviews",
    "require_code_owner_reviews",
    "required_approving_review_count",
    "require_last_push_approval",
}
_BYPASS_KEYS = {"users", "teams", "apps"}
_BOOLEAN_KEYS = {
    "enforce_admins",
    "required_linear_history",
    "allow_force_pushes",
    "allow_deletions",
    "block_creations",
    "required_conversation_resolution",
    "lock_branch",
    "allow_fork_syncing",
}
_REPOSITORY_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_SHA_PATTERN = re.compile(r"[0-9a-fA-F]{40}\Z")


class PolicyDrift(RuntimeError):
    """Signale un écart entre la politique attendue et l'état GitHub observé."""


class GitHubAPIError(RuntimeError):
    """Signale un échec explicite de l'appel ``gh api``."""

    def __init__(self, message: str, *, returncode: int | None = None) -> None:
        super().__init__(message)
        self.returncode = returncode


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) for key in value
    ):
        raise TypeError(f"{label} must be a JSON object")
    return value


def _require_exact_keys(
    value: dict[str, object], expected: set[str], label: str
) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise ValueError(
            f"{label} keys differ: missing={missing}, unknown={unknown}"
        )


def _require_bool(value: object, label: str) -> bool:
    if type(value) is not bool:
        raise TypeError(f"{label} must be a boolean")
    return value


def _require_contexts(value: object, label: str) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(context, str) and bool(context) for context in value
    ):
        raise TypeError(f"{label} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{label} contains duplicate contexts")
    return list(value)


def _validate_policy(policy: object) -> dict[str, object]:
    document = _require_mapping(policy, "policy")
    _require_exact_keys(document, _TOP_LEVEL_KEYS, "policy")

    status = _require_mapping(
        document["required_status_checks"], "required_status_checks"
    )
    _require_exact_keys(status, _STATUS_KEYS, "required_status_checks")
    _require_bool(status["strict"], "required_status_checks.strict")
    _require_contexts(
        status["contexts"], "required_status_checks.contexts"
    )

    reviews = _require_mapping(
        document["required_pull_request_reviews"],
        "required_pull_request_reviews",
    )
    _require_exact_keys(reviews, _REVIEW_KEYS, "required_pull_request_reviews")
    for key in _REVIEW_KEYS - {"required_approving_review_count"}:
        _require_bool(reviews[key], f"required_pull_request_reviews.{key}")
    count = reviews["required_approving_review_count"]
    if type(count) is not int or not 0 <= count <= 6:
        raise TypeError(
            "required_pull_request_reviews.required_approving_review_count "
            "must be an integer between 0 and 6"
        )

    if document["restrictions"] is not None:
        raise TypeError("restrictions must be null")
    for key in _BOOLEAN_KEYS:
        _require_bool(document[key], key)
    return document


def load_policy(path: Path) -> dict[str, object]:
    """Charge et valide strictement une politique depuis un fichier JSON."""

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load policy {path}: {exc}") from exc
    return _validate_policy(raw)


def normalize_policy(policy: dict[str, object]) -> dict[str, object]:
    """Retourne uniquement les champs gouvernés dans un ordre déterministe."""

    validated = _validate_policy(policy)
    status = _require_mapping(
        validated["required_status_checks"], "required_status_checks"
    )
    reviews = _require_mapping(
        validated["required_pull_request_reviews"],
        "required_pull_request_reviews",
    )
    return {
        "required_status_checks": {
            "strict": status["strict"],
            "contexts": sorted(
                _require_contexts(
                    status["contexts"], "required_status_checks.contexts"
                )
            ),
        },
        "enforce_admins": validated["enforce_admins"],
        "required_pull_request_reviews": {
            **{key: reviews[key] for key in sorted(_REVIEW_KEYS)},
            "bypass_pull_request_allowances": {
                key: [] for key in sorted(_BYPASS_KEYS)
            },
        },
        "restrictions": None,
        **{key: validated[key] for key in sorted(_BOOLEAN_KEYS - {"enforce_admins"})},
    }


def _unwrap_enabled(remote: dict[str, object], key: str) -> bool:
    wrapper = _require_mapping(remote[key], key)
    if "enabled" not in wrapper:
        raise ValueError(f"{key}.enabled is missing")
    return _require_bool(wrapper["enabled"], f"{key}.enabled")


def _normalize_bypass_actors(
    value: object, *, actor: str, identity_key: str
) -> list[str]:
    if not isinstance(value, list):
        raise TypeError(
            f"bypass_pull_request_allowances.{actor} must be a list"
        )
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str) and item:
            identity = item
        elif isinstance(item, dict):
            identity_value: object = item.get(identity_key)
            if not isinstance(identity_value, str) or not identity_value:
                raise TypeError(
                    f"bypass_pull_request_allowances.{actor} entries "
                    f"must contain a non-empty {identity_key}"
                )
            identity = identity_value
        else:
            raise TypeError(
                f"bypass_pull_request_allowances.{actor} entries "
                "must be strings or JSON objects"
            )
        normalized.append(identity)
    return sorted(normalized)


def _normalize_bypass_allowances(value: object) -> dict[str, object]:
    if value is None:
        return {key: [] for key in sorted(_BYPASS_KEYS)}
    bypass = _require_mapping(value, "bypass_pull_request_allowances")
    unknown = set(bypass) - _BYPASS_KEYS
    if unknown:
        raise ValueError(
            "bypass_pull_request_allowances contains unknown keys: "
            f"{sorted(unknown)}"
        )
    return {
        "apps": _normalize_bypass_actors(
            bypass.get("apps", []), actor="apps", identity_key="slug"
        ),
        "teams": _normalize_bypass_actors(
            bypass.get("teams", []), actor="teams", identity_key="slug"
        ),
        "users": _normalize_bypass_actors(
            bypass.get("users", []), actor="users", identity_key="login"
        ),
    }


def normalize_remote(remote: dict[str, object]) -> dict[str, object]:
    """Convertit la réponse GitHub en politique gouvernée comparable."""

    document = _require_mapping(remote, "remote protection")
    missing = _TOP_LEVEL_KEYS - set(document)
    if missing:
        raise ValueError(f"remote protection is missing keys: {sorted(missing)}")

    status = _require_mapping(
        document["required_status_checks"], "required_status_checks"
    )
    if not _STATUS_KEYS.issubset(status):
        raise ValueError("required_status_checks is missing governed keys")
    strict = _require_bool(status["strict"], "required_status_checks.strict")
    contexts = sorted(
        _require_contexts(
            status["contexts"], "required_status_checks.contexts"
        )
    )

    reviews = _require_mapping(
        document["required_pull_request_reviews"],
        "required_pull_request_reviews",
    )
    if not _REVIEW_KEYS.issubset(reviews):
        raise ValueError("required_pull_request_reviews is missing governed keys")
    normalized_reviews: dict[str, object] = {}
    for key in sorted(_REVIEW_KEYS):
        if key == "required_approving_review_count":
            value = reviews[key]
            if type(value) is not int or not 0 <= value <= 6:
                raise TypeError(
                    "required_pull_request_reviews."
                    "required_approving_review_count must be an integer "
                    "between 0 and 6"
                )
            normalized_reviews[key] = value
        else:
            normalized_reviews[key] = _require_bool(
                reviews[key], f"required_pull_request_reviews.{key}"
            )
    normalized_reviews["bypass_pull_request_allowances"] = (
        _normalize_bypass_allowances(
            reviews.get("bypass_pull_request_allowances")
        )
    )

    restrictions = document["restrictions"]
    if restrictions is not None and not isinstance(restrictions, dict):
        raise TypeError("restrictions must be null or a JSON object")

    normalized: dict[str, object] = {
        "required_status_checks": {
            "strict": strict,
            "contexts": contexts,
        },
        "enforce_admins": _unwrap_enabled(document, "enforce_admins"),
        "required_pull_request_reviews": normalized_reviews,
        "restrictions": restrictions,
    }
    for key in sorted(_BOOLEAN_KEYS - {"enforce_admins"}):
        normalized[key] = _unwrap_enabled(document, key)
    return normalized


def verify_policy(
    policy: dict[str, object], remote: dict[str, object]
) -> None:
    """Lève :class:`PolicyDrift` si GitHub diffère de la politique."""

    expected = normalize_policy(policy)
    observed = normalize_remote(remote)
    if expected == observed:
        return
    expected_json = json.dumps(
        expected, ensure_ascii=False, indent=2, sort_keys=True
    ).splitlines()
    observed_json = json.dumps(
        observed, ensure_ascii=False, indent=2, sort_keys=True
    ).splitlines()
    diff = "\n".join(
        difflib.unified_diff(
            expected_json,
            observed_json,
            fromfile="expected",
            tofile="remote",
            lineterm="",
        )
    )
    raise PolicyDrift(f"main protection policy drift:\n{diff}")


def _api_args(endpoint: str, *, method: str | None = None) -> list[str]:
    args = ["gh", "api"]
    if method is not None:
        args.extend(["--method", method])
    args.append(endpoint)
    args.extend(["-H", f"X-GitHub-Api-Version: {GITHUB_API_VERSION}"])
    if method is not None:
        args.extend(["--input", "-"])
    return args


def _runner_mapping(
    runner: Runner, argv: list[str], *, input_data: str | None = None
) -> dict[str, object]:
    result = runner(argv, input_data=input_data)
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError as exc:
            raise ValueError("gh api returned malformed JSON") from exc
    return _require_mapping(result, "gh api response")


def run_gh_api(
    argv: list[str], *, input_data: str | None = None
) -> dict[str, object] | str:
    """Exécute ``gh api`` sans shell et retourne son objet JSON."""

    if argv[:2] != ["gh", "api"]:
        raise ValueError("runner only accepts gh api argv")
    try:
        completed = subprocess.run(
            argv,
            input=input_data,
            text=True,
            capture_output=True,
            check=False,
            timeout=GH_API_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitHubAPIError(
            f"gh api timed out after {GH_API_TIMEOUT_SECONDS} seconds; "
            "run --check before any new attempt"
        ) from exc
    except OSError as exc:
        raise GitHubAPIError(f"unable to execute gh api: {exc}") from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise GitHubAPIError(
            f"gh api failed ({completed.returncode}): {detail}",
            returncode=completed.returncode,
        )
    try:
        parsed: Any = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubAPIError("gh api returned malformed JSON") from exc
    return _require_mapping(parsed, "gh api response")


def _validate_repository(repository: str) -> None:
    if _REPOSITORY_PATTERN.fullmatch(repository) is None:
        raise ValueError("repository must use OWNER/REPO format")


def _validate_sha(sha: str) -> None:
    if _SHA_PATTERN.fullmatch(sha) is None:
        raise ValueError("expected main SHA must contain exactly 40 hexadecimal chars")


def apply_policy(
    repository: str,
    expected_main_sha: str,
    confirmation: str | None,
    policy_path: Path,
    runner: Runner,
) -> None:
    """Applique la politique si le SHA et la confirmation sont exacts.

    ``runner`` reçoit un argv ``gh api`` et le mot-clé optionnel
    ``input_data``. Cette injection garde le chemin d'écriture unitaire et
    testable, sans exécuter de shell.
    """

    _validate_repository(repository)
    _validate_sha(expected_main_sha)
    ref_endpoint = f"repos/{repository}/git/ref/heads/main"
    ref = _runner_mapping(runner, _api_args(ref_endpoint))
    ref_object = _require_mapping(ref.get("object"), "main ref object")
    remote_sha = ref_object.get("sha")
    if not isinstance(remote_sha, str) or _SHA_PATTERN.fullmatch(remote_sha) is None:
        raise ValueError("main ref response contains a malformed SHA")
    if remote_sha != expected_main_sha:
        raise PolicyDrift(
            f"main SHA drift: expected {expected_main_sha}, remote {remote_sha}"
        )

    expected_confirmation = f"{repository}@{expected_main_sha}"
    if confirmation != expected_confirmation:
        raise PermissionError(
            "NEXUS_CONFIRM_MAIN_PROTECTION does not match repository@SHA"
        )

    policy = load_policy(policy_path)
    protection_endpoint = f"repos/{repository}/branches/main/protection"
    _runner_mapping(
        runner,
        _api_args(protection_endpoint, method="PUT"),
        input_data=json.dumps(policy, ensure_ascii=False),
    )
    remote = _runner_mapping(runner, _api_args(protection_endpoint))
    verify_policy(policy, remote)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Vérifie ou applique la protection versionnée de main."
    )
    parser.add_argument("--repository", required=True, metavar="OWNER/REPO")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--apply", action="store_true")
    parser.add_argument("--expected-main-sha")
    return parser


def main(
    argv: Sequence[str] | None = None, *, runner: Runner = run_gh_api
) -> int:
    """Point d'entrée CLI ; retourne zéro uniquement après vérification."""

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        _validate_repository(args.repository)
    except ValueError as exc:
        parser.error(str(exc))

    if args.check and args.expected_main_sha is not None:
        parser.error("--expected-main-sha is only valid with --apply")
    if args.apply and args.expected_main_sha is None:
        parser.error("--apply requires --expected-main-sha")
    if args.expected_main_sha is not None:
        try:
            _validate_sha(args.expected_main_sha)
        except ValueError as exc:
            parser.error(str(exc))

    try:
        if args.check:
            policy = load_policy(DEFAULT_POLICY_PATH)
            endpoint = f"repos/{args.repository}/branches/main/protection"
            remote = _runner_mapping(runner, _api_args(endpoint))
            verify_policy(policy, remote)
        else:
            apply_policy(
                args.repository,
                args.expected_main_sha,
                os.environ.get("NEXUS_CONFIRM_MAIN_PROTECTION"),
                DEFAULT_POLICY_PATH,
                runner,
            )
    except (GitHubAPIError, OSError, PolicyDrift, TypeError, ValueError, PermissionError) as exc:
        detail = str(exc)
        if (
            args.check
            and isinstance(exc, GitHubAPIError)
            and "Branch not protected" in detail
        ):
            detail = f"main is not protected: {detail}"
        print(f"ERROR: {detail}", file=sys.stderr)
        return 1

    print(f"OK: main protection matches policy for {args.repository}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
