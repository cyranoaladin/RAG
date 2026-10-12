"""Le reçu C lie la revue exacte aux membres LOT41A."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus_release_chain.public_successor_activation import (
    PublicSuccessorActivationError,
    verify_public_lot41a_review_receipt,
)


def _fixture(root: Path, *, changed: str | None = None) -> tuple[str, SimpleNamespace]:
    member = SimpleNamespace(
        authorization_id="lot41a-student-public-maths-v2",
        authorization_digest="a" * 64,
        review_binding_digest="b" * 64,
    )
    authorization_set = SimpleNamespace(
        members=(member,), canonical_bytes=lambda: b"authorization set",
    )
    receipt = {
        "kind": "NEXUS_PUBLIC_SUCCESSOR_PR327_AUTHORIZATION_REVIEW_RECEIPT_V1",
        "status": "SIGNED_BINDINGS_VERIFIED_NOT_PUBLICATION_AUTHORITY",
        "publication_authorized": False,
        "repository": "cyranoaladin/RAG", "pull_request": 327,
        "base_ref": "main", "base_sha": "c" * 40, "head_sha": "d" * 40,
        "author": "cyranoaladin", "reviewer": "abenrhouma", "review_id": 123,
        "challenge": "NEXUS-TRUSTED-REVIEW-V1:" + "e" * 64,
        "review_submitted_at": "2026-10-11T00:00:00Z",
        "authorization_set_sha256": hashlib.sha256(b"authorization set").hexdigest(),
        "authorization_count": 1,
        "authorizations": [{
            "authorization_id": member.authorization_id,
            "authorization_sha256": member.authorization_digest,
            "signed_review_binding_sha256": member.review_binding_digest,
        }],
    }
    if changed == "reviewer":
        receipt["reviewer"] = "other"
    elif changed == "binding":
        receipt["authorizations"][0]["signed_review_binding_sha256"] = "f" * 64
    root.joinpath("authorities").mkdir()
    raw = (json.dumps(receipt, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()
    path = root / "authorities/exact_head_authorization_review_receipt_sha256.bin"
    path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    if changed == "bytes":
        path.write_bytes(raw + b" ")
    return digest, authorization_set


def test_receipt_binds_same_signed_review_and_members(tmp_path: Path) -> None:
    digest, authorization_set = _fixture(tmp_path)
    assert verify_public_lot41a_review_receipt(tmp_path, digest, authorization_set) == (
        "cyranoaladin/RAG", 327, "main", "c" * 40, "d" * 40,
        "cyranoaladin", "abenrhouma", 123,
        "NEXUS-TRUSTED-REVIEW-V1:" + "e" * 64, "2026-10-11T00:00:00Z",
    )


@pytest.mark.parametrize("changed", ["reviewer", "binding", "bytes"])
def test_receipt_refuses_changed_review_members_or_bytes(
    tmp_path: Path, changed: str,
) -> None:
    digest, authorization_set = _fixture(tmp_path, changed=changed)
    with pytest.raises(PublicSuccessorActivationError):
        verify_public_lot41a_review_receipt(tmp_path, digest, authorization_set)
