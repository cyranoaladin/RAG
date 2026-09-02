"""L'émetteur de reçus ADR-0035 couvre aussi un ensemble de décisions PII (ADR-0047).

Même pipeline, même clé, même vérificateur hors ligne : seule change la nature
de l'artefact relu au HEAD approuvé — un ensemble canonique de décisions sous
`governance/pii-review-decisions/`, jamais une autorisation de scope.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from typing import Any

import pytest
from nexus_contracts import PiiReviewDecisionSetV1, canonical_pii_review_decisions_path
from nexus_contracts.authority_artifacts import git_blob_sha1
from nexus_contracts.review_binding import (
    TrustAnchor,
    public_key_hex,
    require_matches_pii_review_decision_set,
    verify_review_binding,
)

import ingestor.ingestion_worker.issue_review_binding_cli as producer
from ingestor.ingestion_control.github_authority import (
    GitHubBlob,
    PullRequestActorContext,
    ReviewVerification,
)

TEST_SEED = "33" * 32
KEY_ID = "review-binding-v1-2026-08-25-test"
REPOSITORY = "cyranoaladin/RAG"
PULL_REQUEST = 210
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
REVIEWER = "abenrhouma"
AUTHOR = "cyranoaladin"
DECISION_SET_ID = "pii-review-2026-09-02-lot-1-2"
NOW = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


def _decision_set_bytes() -> bytes:
    return PiiReviewDecisionSetV1.model_validate(
        {
            "protocol_version": "NEXUS-PII-REVIEW-DECISIONS-V1",
            "decision_set_id": DECISION_SET_ID,
            "corpus_manifest_sha256": "7" * 64,
            "policy_id": "pii_gate_policy_h2b_v5",
            "policy_sha256": "1" * 64,
            "scanner_sha256": "2" * 64,
            "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
            "page_policy_sha256": "3" * 64,
            "review_index_sha256": "6" * 64,
            "decisions": [
                {
                    "content_sha256": "a" * 64,
                    "policy_id": "pii_gate_policy_h2b_v5",
                    "policy_sha256": "1" * 64,
                    "scanner_sha256": "2" * 64,
                    "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
                    "page_policy_sha256": "3" * 64,
                    "review_bundle_sha256": "4" * 64,
                    "signal_classes": ["phone_french"],
                    "signal_count": 1,
                    "pages": [2],
                    "findings": [
                        {"finding_id": "f1" * 32, "pattern_id": "phone_french", "page": 2,
                         "match_sha256": "a1" * 32, "context_sha256": "b1" * 32,
                         "disposition": "PUBLIC_INSTITUTIONAL_DATA"},
                    ],
                    "decision": "APPROVED",
                    "justification": {
                        "category": "INSTITUTIONAL_CONTACT",
                        "statement": "Standard téléphonique d'un établissement en en-tête officiel.",
                        "raw_pii_quoted": False,
                    },
                    "reviewer_login": REVIEWER,
                    "decided_at": "2026-09-03T10:00:00+00:00",
                }
            ],
        }
    ).canonical_bytes()


def _challenge() -> str:
    from nexus_contracts.review_binding import expected_challenge_digest

    digest = expected_challenge_digest(
        repository=REPOSITORY, pull_request=PULL_REQUEST, base_ref="main", base_sha=BASE_SHA,
        head_sha=HEAD_SHA, author=AUTHOR, reviewer=REVIEWER,
    )
    return f"NEXUS-TRUSTED-REVIEW-V1:{digest}"


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    raw = _decision_set_bytes()
    state: dict[str, Any] = {
        "verification": ReviewVerification(
            approved=True, reason="approved", repository=REPOSITORY, pull_request=PULL_REQUEST,
            base_sha=BASE_SHA, head_sha=HEAD_SHA, reviewer=REVIEWER, review_id=777,
            submitted_at="2026-09-05T11:00:00Z", challenge=_challenge(),
        ),
        "context": PullRequestActorContext(
            repository=REPOSITORY, pull_request=PULL_REQUEST, author=AUTHOR, base_ref="main",
            reviewer=REVIEWER, reviewer_permission="write", reviewer_role_name="write",
        ),
        "blob": GitHubBlob(
            repository=REPOSITORY, path=canonical_pii_review_decisions_path(DECISION_SET_ID),
            ref=HEAD_SHA, blob_sha=git_blob_sha1(raw), content=raw,
        ),
        "requested_paths": [],
    }

    def fetch_blob(**kwargs: Any) -> GitHubBlob:
        state["requested_paths"].append(kwargs.get("path"))
        return state["blob"]

    monkeypatch.setattr(producer, "verify_review", lambda **_k: state["verification"])
    monkeypatch.setattr(producer, "pull_request_actor_context", lambda **_k: state["context"])
    monkeypatch.setattr(producer, "fetch_blob_at_ref", fetch_blob)
    monkeypatch.setenv(producer.SIGNING_KEY_ENV, TEST_SEED)
    return state


def _args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "repository": REPOSITORY, "pull_request": PULL_REQUEST, "expected_head": HEAD_SHA,
        "authorization_id": None, "decision_set_id": DECISION_SET_ID, "validity_days": 30,
        "key_id": KEY_ID,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _anchor() -> TrustAnchor:
    return TrustAnchor.model_validate(
        {"protocol_version": "NEXUS-REVIEW-BINDING-V1",
         "keys": [{"key_id": KEY_ID, "algorithm": "ed25519", "public_key": public_key_hex(TEST_SEED),
                   "environment": "test"}]}
    )


def test_an_approved_decision_set_produces_a_verifiable_receipt(github: dict[str, Any]) -> None:
    raw = producer._issue_binding(_args(), now=NOW)
    binding = verify_review_binding(raw, trust_anchor=_anchor(), environment="test", now=NOW)
    assert binding.authorization_decision == "APPROVE_PII_REVIEW_DECISIONS"
    assert binding.authorization_id == DECISION_SET_ID
    assert binding.authorization_artifact_path == canonical_pii_review_decisions_path(DECISION_SET_ID)
    assert binding.authorization_artifact_sha256 == hashlib.sha256(_decision_set_bytes()).hexdigest()
    assert github["requested_paths"] == [canonical_pii_review_decisions_path(DECISION_SET_ID)]
    require_matches_pii_review_decision_set(
        binding, decision_set_id=DECISION_SET_ID, decision_set_bytes=_decision_set_bytes(),
        decision_set_git_blob_sha1=git_blob_sha1(_decision_set_bytes()),
        expected_repository=REPOSITORY, accepted_reviewers=(REVIEWER,),
    )


def test_a_non_canonical_decision_set_at_head_is_refused(github: dict[str, Any]) -> None:
    raw = _decision_set_bytes() + b"\n"
    github["blob"] = GitHubBlob(
        repository=REPOSITORY, path=canonical_pii_review_decisions_path(DECISION_SET_ID),
        ref=HEAD_SHA, blob_sha=git_blob_sha1(raw), content=raw,
    )
    with pytest.raises(producer.ReviewBindingProductionError, match="NOT_CANONICAL"):
        producer._issue_binding(_args(), now=NOW)


def test_a_decision_set_whose_id_differs_from_the_argument_is_refused(github: dict[str, Any]) -> None:
    with pytest.raises(producer.ReviewBindingProductionError, match="ID_MISMATCH"):
        producer._issue_binding(_args(decision_set_id="pii-review-other"), now=NOW)


def test_exactly_one_artifact_kind_must_be_named(github: dict[str, Any]) -> None:
    with pytest.raises(producer.ReviewBindingProductionError, match="exactly one"):
        producer._issue_binding(_args(authorization_id="x", decision_set_id="y"), now=NOW)
    with pytest.raises(producer.ReviewBindingProductionError, match="exactly one"):
        producer._issue_binding(_args(authorization_id=None, decision_set_id=None), now=NOW)
