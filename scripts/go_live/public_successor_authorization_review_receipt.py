"""Reçu déterministe des onze revues LOT41A V2 de la PR #327.

Le producteur et C appellent cette fonction seulement après le vérificateur
complet du set, qui authentifie les signatures et les révocations. Ce reçu ne
remplace ni ces vérifications ni la relecture des autorisations en DB.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from nexus_contracts.authority_artifacts import (
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.authorization_set import (
    AuthorizationSetV2,
    canonical_review_binding_path,
)
from nexus_contracts.review_binding import (
    ReviewBindingError,
    parse_signed_review_binding,
    require_challenge_is_bound,
    require_matches_authorization,
)

KIND = "NEXUS_PUBLIC_SUCCESSOR_PR327_AUTHORIZATION_REVIEW_RECEIPT_V1"
REPOSITORY = "cyranoaladin/RAG"
REVIEWER = "abenrhouma"
PR_NUMBER = 327


class AuthorizationReviewReceiptError(ValueError):
    """Les onze autorisations ne portent pas une seule revue exacte."""


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical(document: dict[str, Any]) -> bytes:
    return (json.dumps(document, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def build_exact_head_authorization_review_receipt(
    authorization_set: AuthorizationSetV2,
    release_files: Mapping[str, bytes],
) -> bytes:
    """Agréger des preuves déjà vérifiées, sans forger une nouvelle review."""
    members = authorization_set.members
    if authorization_set.authorization_count != 11 or len(members) != 11:
        raise AuthorizationReviewReceiptError("eleven reviewed authorizations required")
    expected_paths = {
        path
        for member in members
        for path in (
            canonical_authorization_path(member.authorization_id),
            canonical_review_binding_path(member.authorization_id),
        )
    }
    if len(expected_paths) != 22 or set(release_files) != expected_paths:
        raise AuthorizationReviewReceiptError("exact authorization material population required")
    reviews: set[tuple[object, ...]] = set()
    entries: list[dict[str, str]] = []
    for member in members:
        authorization_id = member.authorization_id
        authorization_raw = release_files[canonical_authorization_path(authorization_id)]
        binding_raw = release_files[canonical_review_binding_path(authorization_id)]
        if (_sha(authorization_raw) != member.authorization_digest
                or _sha(binding_raw) != member.review_binding_digest):
            raise AuthorizationReviewReceiptError("authorization or signed binding differs from set")
        try:
            signed = parse_signed_review_binding(binding_raw)
            binding = signed.binding
            if signed.binding_digest != _sha(binding.canonical_bytes()):
                raise ReviewBindingError("signed binding payload digest differs")
            require_matches_authorization(
                binding, authorization_id=authorization_id,
                authorization_bytes=authorization_raw,
                authorization_git_blob_sha1=git_blob_sha1(authorization_raw),
                expected_repository=REPOSITORY, accepted_reviewers=(REVIEWER,),
            )
            require_challenge_is_bound(binding)
        except ReviewBindingError as error:
            raise AuthorizationReviewReceiptError("signed review binding differs") from error
        if (binding.pull_request != PR_NUMBER or binding.base_ref != "main"
                or binding.authorization_decision != "AUTHORIZE_INGESTION_SCOPE"):
            raise AuthorizationReviewReceiptError("PR327 exact authorization review required")
        reviews.add((
            binding.repository, binding.pull_request, binding.base_ref,
            binding.base_sha, binding.head_sha, binding.author_login,
            binding.reviewer_login, binding.review_id, binding.challenge,
            binding.canonical_document()["submitted_at"],
        ))
        entries.append({
            "authorization_id": authorization_id,
            "authorization_sha256": member.authorization_digest,
            "signed_review_binding_sha256": member.review_binding_digest,
        })
    if len(reviews) != 1:
        raise AuthorizationReviewReceiptError("eleven bindings do not share exact PR327 review")
    (repository, pull_request, base_ref, base_sha, head_sha, author,
     reviewer, review_id, challenge, submitted_at) = next(iter(reviews))
    return _canonical({
        "kind": KIND,
        "status": "SIGNED_BINDINGS_VERIFIED_NOT_PUBLICATION_AUTHORITY",
        "publication_authorized": False,
        "repository": repository,
        "pull_request": pull_request,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "author": author,
        "reviewer": reviewer,
        "review_id": review_id,
        "challenge": challenge,
        "review_submitted_at": submitted_at,
        "authorization_set_sha256": _sha(authorization_set.canonical_bytes()),
        "authorization_count": len(entries),
        "authorizations": sorted(entries, key=lambda row: row["authorization_id"]),
    })
