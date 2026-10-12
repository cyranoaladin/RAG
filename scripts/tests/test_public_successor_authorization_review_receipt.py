"""Le reçu C agrégé reste lié aux onze bindings signés de #327."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from nexus_contracts.authority_artifacts import (
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.authorization_set import canonical_review_binding_path
from nexus_contracts.review_binding import (
    ScopeAuthorizationReviewBindingV1,
    expected_challenge_digest,
    sign_review_binding,
)

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/go_live"))
sys.path.insert(0, str(ROOT / "services/rag-engine/scripts"))

import produce_public_lot41a_v2 as producer
import public_successor_authorization_review_receipt as receipt
import public_successor_signing_replay as replay

SEED = "11" * 32  # clé synthétique de test, jamais une identité réelle
REVIEW = {
    "repository": "cyranoaladin/RAG",
    "pull_request": 327,
    "base_ref": "main",
    "base_sha": "a" * 40,
    "head_sha": "b" * 40,
    "author_login": "cyranoaladin",
    "reviewer_login": "abenrhouma",
    "review_id": 9001,
}


def _material(*, changed_index: int | None = None, change: dict | None = None):
    files: dict[str, bytes] = {}
    members = []
    for index in range(11):
        authorization_id = f"lot41a-student-public-test-{index}-v2"
        auth_raw = f"authorization-{index}".encode()
        facts = dict(REVIEW)
        if index == changed_index:
            facts.update({key: value for key, value in (change or {}).items()
                          if key != "challenge_digest"})
        challenge = expected_challenge_digest(
            repository=facts["repository"], pull_request=facts["pull_request"],
            base_ref=facts["base_ref"], base_sha=facts["base_sha"],
            head_sha=facts["head_sha"], author=facts["author_login"],
            reviewer=facts["reviewer_login"],
        )
        binding = ScopeAuthorizationReviewBindingV1.model_validate({
            "protocol_version": "NEXUS-REVIEW-BINDING-V1", **facts,
            "authorization_artifact_path": canonical_authorization_path(authorization_id),
            "authorization_artifact_sha256": hashlib.sha256(auth_raw).hexdigest(),
            "authorization_artifact_git_blob_sha1": git_blob_sha1(auth_raw),
            "authorization_id": authorization_id,
            "authorization_decision": "AUTHORIZE_INGESTION_SCOPE",
            "reviewer_permission": "admin",
            "submitted_at": datetime(2026, 10, 11, 20, tzinfo=UTC),
            "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
            "challenge_digest": (change or {}).get("challenge_digest", challenge)
            if index == changed_index else challenge,
            "verified_at": datetime(2026, 10, 11, 21, tzinfo=UTC),
            "verifier_version": "test-only",
            "expires_at": datetime(2026, 10, 18, 21, tzinfo=UTC),
        })
        binding_raw = sign_review_binding(
            binding, private_key_hex=SEED, key_id="nexus-test-key",
        ).canonical_bytes()
        files[canonical_authorization_path(authorization_id)] = auth_raw
        files[canonical_review_binding_path(authorization_id)] = binding_raw
        members.append(SimpleNamespace(
            authorization_id=authorization_id,
            authorization_digest=hashlib.sha256(auth_raw).hexdigest(),
            review_binding_digest=hashlib.sha256(binding_raw).hexdigest(),
        ))
    return SimpleNamespace(
        members=tuple(members), authorization_count=11,
        canonical_bytes=lambda: b"verified-authorization-set\n",
    ), files


def test_receipt_is_deterministic_and_exact_head_bound(tmp_path: Path) -> None:
    authorization_set, files = _material()
    raw = receipt.build_exact_head_authorization_review_receipt(authorization_set, files)
    assert raw == receipt.build_exact_head_authorization_review_receipt(authorization_set, files)
    document = json.loads(raw)
    assert document["kind"] == "NEXUS_PUBLIC_SUCCESSOR_PR327_AUTHORIZATION_REVIEW_RECEIPT_V1"
    assert document["authorization_set_sha256"] == hashlib.sha256(
        authorization_set.canonical_bytes()
    ).hexdigest()
    assert document["head_sha"] == REVIEW["head_sha"]
    assert document["base_sha"] == REVIEW["base_sha"]
    assert document["review_id"] == REVIEW["review_id"]
    assert document["challenge"] == "NEXUS-TRUSTED-REVIEW-V1:" + expected_challenge_digest(
        repository=REVIEW["repository"], pull_request=327,
        base_ref="main", base_sha=REVIEW["base_sha"], head_sha=REVIEW["head_sha"],
        author=REVIEW["author_login"], reviewer=REVIEW["reviewer_login"],
    )
    assert len(document["authorizations"]) == 11
    bundle = tmp_path / "bundle" / "authorities"
    bundle.mkdir(parents=True)
    path = bundle / "exact_head_authorization_review_receipt_sha256.bin"
    path.write_bytes(raw)
    replay._verify_exact_head_authorization_review_receipt(
        bundle.parent, hashlib.sha256(raw).hexdigest(), authorization_set, files,
    )
    path.write_bytes(raw.replace(b'"head_sha": "', b'"head_sha": "f'))
    with pytest.raises(replay.PublicationSigningReplayRefused, match="authorization review"):
        replay._verify_exact_head_authorization_review_receipt(
            bundle.parent, hashlib.sha256(path.read_bytes()).hexdigest(),
            authorization_set, files,
        )


@pytest.mark.parametrize("change", [
    {"base_sha": "c" * 40}, {"head_sha": "c" * 40},
    {"review_id": 9002}, {"reviewer_login": "another-reviewer"},
    {"pull_request": 326}, {"challenge_digest": "f" * 64},
])
def test_mixed_exact_review_refused(change: dict) -> None:
    authorization_set, files = _material(changed_index=7, change=change)
    with pytest.raises(receipt.AuthorizationReviewReceiptError):
        receipt.build_exact_head_authorization_review_receipt(authorization_set, files)


def test_missing_or_substituted_member_refused() -> None:
    authorization_set, files = _material()
    member = authorization_set.members[0]
    files.pop(canonical_review_binding_path(member.authorization_id))
    with pytest.raises(receipt.AuthorizationReviewReceiptError):
        receipt.build_exact_head_authorization_review_receipt(authorization_set, files)
    authorization_set, files = _material()
    files[canonical_authorization_path(member.authorization_id)] = b"substituted"
    with pytest.raises(receipt.AuthorizationReviewReceiptError):
        receipt.build_exact_head_authorization_review_receipt(authorization_set, files)


def test_private_producer_writes_once_after_verified_set(tmp_path: Path) -> None:
    authorization_set, files = _material()
    output = tmp_path / "review-receipt.json"
    producer._write_private_review_receipt(output, authorization_set, files)
    assert output.read_bytes() == receipt.build_exact_head_authorization_review_receipt(
        authorization_set, files,
    )
    with pytest.raises(FileExistsError):
        producer._write_private_review_receipt(output, authorization_set, files)


def test_private_producer_refuses_repository_destination() -> None:
    authorization_set, files = _material()
    with pytest.raises(ValueError, match="private"):
        producer._write_private_review_receipt(
            ROOT / "docs/reports/go_live/forbidden-review-receipt.json",
            authorization_set, files,
        )
