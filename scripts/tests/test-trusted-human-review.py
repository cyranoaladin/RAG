#!/usr/bin/env python3
"""Tests du challenge et de la décision de revue humaine fiable."""

from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "github" / "trusted_human_review.py"
CONFIG_PATH = REPO_ROOT / "scripts" / "github" / "trusted-reviewers.json"

SPEC = importlib.util.spec_from_file_location("trusted_human_review", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Impossible de charger {MODULE_PATH}")
trusted_review = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = trusted_review
SPEC.loader.exec_module(trusted_review)


def expected_config() -> dict[str, object]:
    return {
        "protocol": "NEXUS-TRUSTED-REVIEW-V1",
        "repository": "cyranoaladin/RAG",
        "base_ref": "main",
        "reviewers": ["abenrhouma"],
    }


def valid_payload() -> dict[str, object]:
    return {
        "repository": "cyranoaladin/RAG",
        "pull_request": 89,
        "base_ref": "main",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "author": "cyranoaladin",
        "reviewer": "abenrhouma",
        "protocol": "NEXUS-TRUSTED-REVIEW-V1",
    }


class TrustedReviewerConfigTests(unittest.TestCase):
    def test_versioned_config_is_exact(self) -> None:
        config = trusted_review.load_config(CONFIG_PATH)

        self.assertEqual(config.protocol, "NEXUS-TRUSTED-REVIEW-V1")
        self.assertEqual(config.repository, "cyranoaladin/RAG")
        self.assertEqual(config.base_ref, "main")
        self.assertEqual(config.reviewers, ("abenrhouma",))

    def test_config_refuses_unknown_keys_and_invalid_values(self) -> None:
        cases: list[object] = []

        unknown = expected_config()
        unknown["unknown"] = True
        cases.append(unknown)

        duplicate = expected_config()
        duplicate["reviewers"] = ["abenrhouma", "abenrhouma"]
        cases.append(duplicate)

        empty_reviewer = expected_config()
        empty_reviewer["reviewers"] = [""]
        cases.append(empty_reviewer)

        wrong_repository = expected_config()
        wrong_repository["repository"] = "someone/else"
        cases.append(wrong_repository)

        wrong_protocol = expected_config()
        wrong_protocol["protocol"] = "NEXUS-TRUSTED-REVIEW-V2"
        cases.append(wrong_protocol)

        wrong_base = expected_config()
        wrong_base["base_ref"] = "develop"
        cases.append(wrong_base)

        cases.extend(([], {"protocol": 1}))

        for document in cases:
            with self.subTest(document=document):
                with tempfile.TemporaryDirectory() as tmp:
                    path = Path(tmp) / "reviewers.json"
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises((TypeError, ValueError)):
                        trusted_review.load_config(path)


class CanonicalChallengeTests(unittest.TestCase):
    def test_challenge_uses_canonical_json_and_sha256(self) -> None:
        payload = valid_payload()
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        expected = "NEXUS-TRUSTED-REVIEW-V1:" + sha256(encoded).hexdigest()

        self.assertEqual(trusted_review.build_challenge(payload), expected)

    def test_challenge_is_independent_of_input_key_order(self) -> None:
        payload = valid_payload()
        reversed_payload = dict(reversed(tuple(payload.items())))

        self.assertEqual(
            trusted_review.build_challenge(payload),
            trusted_review.build_challenge(reversed_payload),
        )

    def test_challenge_refuses_unknown_missing_or_malformed_fields(self) -> None:
        cases: list[dict[str, object]] = []

        unknown = valid_payload()
        unknown["unknown"] = "value"
        cases.append(unknown)

        missing = valid_payload()
        del missing["head_sha"]
        cases.append(missing)

        uppercase_sha = valid_payload()
        uppercase_sha["head_sha"] = "B" * 40
        cases.append(uppercase_sha)

        short_sha = valid_payload()
        short_sha["base_sha"] = "a" * 39
        cases.append(short_sha)

        zero_pr = valid_payload()
        zero_pr["pull_request"] = 0
        cases.append(zero_pr)

        bool_pr = valid_payload()
        bool_pr["pull_request"] = True
        cases.append(bool_pr)

        empty_author = valid_payload()
        empty_author["author"] = ""
        cases.append(empty_author)

        wrong_repository = valid_payload()
        wrong_repository["repository"] = "someone/else"
        cases.append(wrong_repository)

        wrong_base = valid_payload()
        wrong_base["base_ref"] = "develop"
        cases.append(wrong_base)

        wrong_protocol = valid_payload()
        wrong_protocol["protocol"] = "NEXUS-TRUSTED-REVIEW-V2"
        cases.append(wrong_protocol)

        for payload in cases:
            with self.subTest(payload=payload):
                with self.assertRaises((TypeError, ValueError)):
                    trusted_review.build_challenge(payload)


if __name__ == "__main__":
    raise SystemExit(unittest.main())
