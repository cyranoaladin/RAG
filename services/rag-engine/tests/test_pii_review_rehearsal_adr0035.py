"""Rehearsal intégral d'ADR-0035 sur une fixture PII synthétique (pré-gel § 14).

Premier usage réel à venir du mécanisme de reçu : on le répète ici de bout en
bout, hors ligne, sans clé de production ni GitHub — décision → scellement →
review (frontière GitHub substituée) → challenge → reçu → vérification →
sabotages. Seuls les objets authentiquement concordants passent.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from nexus_contracts import (
    PiiReviewDecisionSetV1,
    canonical_pii_review_decisions_path,
    parse_pii_review_decision_set,
)
from nexus_contracts.authority_artifacts import git_blob_sha1
from nexus_contracts.review_binding import (
    ReviewBindingError,
    TrustAnchor,
    expected_challenge_digest,
    parse_signed_review_binding,
    public_key_hex,
    require_challenge_is_bound,
    require_matches_pii_review_decision_set,
    verify_review_binding,
)

import ingestor.ingestion_worker.issue_review_binding_cli as producer
from ingestor.ingestion_control.github_authority import (
    GitHubBlob,
    PullRequestActorContext,
    ReviewVerification,
)

SEED = "77" * 32
OTHER_SEED = "88" * 32
KEY_ID = "review-binding-v1-rehearsal"
REPOSITORY = "cyranoaladin/RAG"
PR = 300
BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
REVIEWER = "abenrhouma"
AUTHOR = "cyranoaladin"
SET_ID = "pii-review-rehearsal"
NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
SHA_A = "a" * 64


def _decision_set(decision: str = "APPROVED", disposition: str = "PUBLIC_INSTITUTIONAL_DATA") -> bytes:
    category = "PERSONAL_DATA_PRESENT" if decision == "REJECTED" else "INSTITUTIONAL_CONTACT"
    return PiiReviewDecisionSetV1.model_validate(
        {
            "protocol_version": "NEXUS-PII-REVIEW-DECISIONS-V1",
            "decision_set_id": SET_ID,
            "corpus_manifest_sha256": "7" * 64,
            "policy_id": "pii_gate_policy_h2b_v5",
            "policy_sha256": "1" * 64,
            "scanner_sha256": "2" * 64,
            "page_policy_id": "NEXUS-PDF-PAGE-POLICY-V1",
            "page_policy_sha256": "3" * 64,
            "review_index_sha256": "6" * 64,
            "decisions": [
                {
                    "content_sha256": SHA_A,
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
                         "disposition": disposition},
                    ],
                    "decision": decision,
                    "justification": {
                        "category": category,
                        "statement": "Standard téléphonique d'un établissement en en-tête officiel.",
                        "raw_pii_quoted": False,
                    },
                    "reviewer_login": REVIEWER,
                    "decided_at": "2026-09-05T10:00:00+00:00",
                }
            ],
        }
    ).canonical_bytes()


def _challenge(*, pr: int = PR, head: str = HEAD_SHA, reviewer: str = REVIEWER) -> str:
    return "NEXUS-TRUSTED-REVIEW-V1:" + expected_challenge_digest(
        repository=REPOSITORY, pull_request=pr, base_ref="main", base_sha=BASE_SHA,
        head_sha=head, author=AUTHOR, reviewer=reviewer,
    )


def _github(monkeypatch: pytest.MonkeyPatch, raw: bytes, **overrides: Any) -> dict[str, Any]:
    state: dict[str, Any] = {
        "verification": ReviewVerification(
            approved=True, reason="approved", repository=REPOSITORY, pull_request=PR,
            base_sha=BASE_SHA, head_sha=HEAD_SHA, reviewer=REVIEWER, review_id=9001,
            submitted_at="2026-09-06T11:00:00Z", challenge=_challenge(),
        ),
        "context": PullRequestActorContext(
            repository=REPOSITORY, pull_request=PR, author=AUTHOR, base_ref="main",
            reviewer=REVIEWER, reviewer_permission="write", reviewer_role_name="write",
        ),
        "blob": GitHubBlob(
            repository=REPOSITORY, path=canonical_pii_review_decisions_path(SET_ID),
            ref=HEAD_SHA, blob_sha=git_blob_sha1(raw), content=raw,
        ),
    }
    state.update(overrides)
    monkeypatch.setattr(producer, "verify_review", lambda **_k: state["verification"])
    monkeypatch.setattr(producer, "pull_request_actor_context", lambda **_k: state["context"])
    monkeypatch.setattr(producer, "fetch_blob_at_ref", lambda **_k: state["blob"])
    monkeypatch.setenv(producer.SIGNING_KEY_ENV, SEED)
    return state


def _args(**overrides: Any) -> argparse.Namespace:
    values: dict[str, Any] = {
        "repository": REPOSITORY, "pull_request": PR, "expected_head": HEAD_SHA,
        "authorization_id": None, "decision_set_id": SET_ID, "validity_days": 30, "key_id": KEY_ID,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _anchor(seed: str = SEED) -> TrustAnchor:
    return TrustAnchor.model_validate(
        {"protocol_version": "NEXUS-REVIEW-BINDING-V1",
         "keys": [{"key_id": KEY_ID, "algorithm": "ed25519", "public_key": public_key_hex(seed),
                   "environment": "test"}]}
    )


def _verify(receipt: bytes, raw: bytes, *, anchor: TrustAnchor | None = None, now: datetime = NOW,
            reviewers: tuple[str, ...] = (REVIEWER,)) -> None:
    binding = verify_review_binding(receipt, trust_anchor=anchor or _anchor(), environment="test", now=now)
    require_challenge_is_bound(binding)
    require_matches_pii_review_decision_set(
        binding, decision_set_id=SET_ID, decision_set_bytes=raw,
        decision_set_git_blob_sha1=git_blob_sha1(raw), expected_repository=REPOSITORY,
        accepted_reviewers=reviewers,
    )


def test_full_cycle_concordant_objects_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _decision_set()
    parse_pii_review_decision_set(raw)  # 1-2. décision scellée, canonique
    _github(monkeypatch, raw)  # 3-4. review APPROVED avec challenge lié
    receipt = producer._issue_binding(_args(), now=NOW)  # 5. reçu
    _verify(receipt, raw)  # 6. vérification hors ligne
    signed = parse_signed_review_binding(receipt)
    assert signed.key_id == KEY_ID
    assert signed.binding.authorization_decision == "APPROVE_PII_REVIEW_DECISIONS"


def test_7_a_tampered_receipt_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _decision_set()
    _github(monkeypatch, raw)
    receipt = producer._issue_binding(_args(), now=NOW)
    document = json.loads(receipt)
    document["binding"]["reviewer_login"] = "someone-else"
    tampered = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    with pytest.raises(ReviewBindingError):
        _verify(tampered, raw)
    document = json.loads(receipt)
    document["signature"] = "0" * 128
    with pytest.raises(ReviewBindingError):
        _verify((json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(), raw)


def test_8_a_decision_set_changed_after_the_receipt_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _decision_set()
    _github(monkeypatch, raw)
    receipt = producer._issue_binding(_args(), now=NOW)
    flipped = _decision_set(decision="REJECTED", disposition="PERSONAL_DATA_PRESENT")
    assert flipped != raw
    with pytest.raises(ReviewBindingError, match="different decision set bytes"):
        _verify(receipt, flipped)


def test_9_a_wrong_reviewer_never_yields_a_receipt_nor_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _decision_set()
    state = _github(monkeypatch, raw)
    state["verification"] = ReviewVerification(
        approved=True, reason="approved", repository=REPOSITORY, pull_request=PR,
        base_sha=BASE_SHA, head_sha=HEAD_SHA, reviewer=AUTHOR, review_id=9002,
        submitted_at="2026-09-06T11:00:00Z", challenge=_challenge(reviewer=AUTHOR),
    )
    with pytest.raises(producer.ReviewBindingProductionError, match="SELF_APPROVAL"):
        producer._issue_binding(_args(), now=NOW)
    # Un reçu authentique d'un reviewer hors allowlist est refusé hors ligne.
    state["verification"] = ReviewVerification(
        approved=True, reason="approved", repository=REPOSITORY, pull_request=PR,
        base_sha=BASE_SHA, head_sha=HEAD_SHA, reviewer="intruder", review_id=9003,
        submitted_at="2026-09-06T11:00:00Z", challenge=_challenge(reviewer="intruder"),
    )
    state["context"] = PullRequestActorContext(
        repository=REPOSITORY, pull_request=PR, author=AUTHOR, base_ref="main",
        reviewer="intruder", reviewer_permission="write", reviewer_role_name="write",
    )
    receipt = producer._issue_binding(_args(), now=NOW)
    with pytest.raises(ReviewBindingError, match="trusted reviewers"):
        _verify(receipt, raw)


def test_10_a_wrong_pull_request_or_commit_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _decision_set()
    state = _github(monkeypatch, raw)
    # Challenge d'une autre PR dans le corps de la review : refus à l'émission.
    state["verification"] = ReviewVerification(
        approved=True, reason="approved", repository=REPOSITORY, pull_request=PR,
        base_sha=BASE_SHA, head_sha=HEAD_SHA, reviewer=REVIEWER, review_id=9004,
        submitted_at="2026-09-06T11:00:00Z", challenge=_challenge(pr=PR + 1),
    )
    with pytest.raises(producer.ReviewBindingProductionError, match="CHALLENGE_MISMATCH"):
        producer._issue_binding(_args(), now=NOW)
    # Reçu émis pour un autre HEAD : l'ensemble relu à ce HEAD diffère → refus hors ligne.
    other_raw = _decision_set(decision="REJECTED", disposition="PERSONAL_DATA_PRESENT")
    state["verification"] = ReviewVerification(
        approved=True, reason="approved", repository=REPOSITORY, pull_request=PR,
        base_sha=BASE_SHA, head_sha="c" * 40, reviewer=REVIEWER, review_id=9005,
        submitted_at="2026-09-06T11:00:00Z", challenge=_challenge(head="c" * 40),
    )
    state["blob"] = GitHubBlob(
        repository=REPOSITORY, path=canonical_pii_review_decisions_path(SET_ID),
        ref="c" * 40, blob_sha=git_blob_sha1(other_raw), content=other_raw,
    )
    receipt = producer._issue_binding(_args(expected_head="c" * 40), now=NOW)
    with pytest.raises(ReviewBindingError, match="different decision set bytes"):
        _verify(receipt, raw)


def test_11_an_old_receipt_cannot_be_replayed(monkeypatch: pytest.MonkeyPatch) -> None:
    raw = _decision_set()
    _github(monkeypatch, raw)
    receipt = producer._issue_binding(_args(validity_days=7), now=NOW)
    _verify(receipt, raw, now=NOW + timedelta(days=6))
    with pytest.raises(ReviewBindingError, match="expired"):
        _verify(receipt, raw, now=NOW + timedelta(days=8))
    # Une clé étrangère à l'ancre ne fait pas un reçu.
    with pytest.raises(ReviewBindingError):
        _verify(receipt, raw, anchor=_anchor(OTHER_SEED))
