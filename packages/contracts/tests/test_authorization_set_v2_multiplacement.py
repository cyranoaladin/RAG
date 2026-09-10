"""V2 AuthorizationSet contract: synthetic authorizations built from real
scope shapes (never claiming a real human review) -- proves the four
mandatory properties R1G section 26 demands.

Never written under ``governance/authorizations`` (these are in-memory
test objects only); no real review binding is claimed.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256

import pytest
from nexus_contracts.authorization_set import (
    AuthorizationSetError,
    AuthorizationSetMemberV1,
    AuthorizationSetV2,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV2,
    content_set_digest,
    scope_digest,
    verify_authorization_binding_set_v2,
)
from nexus_contracts.ingestion import ResourceScope

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
CONTENT_A = "1" * 64
MANIFEST_DIGEST = "d" * 64


def _scope(*, collection: str, niveau: str = "premiere") -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_" + niveau,
            "collection": collection,
            "niveau": niveau,
            "voie": "generale",
            "matiere": "hlp",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "public",
            "school_year": "2026-2027",
            "programme_version": "2026",
        }
    )


def _member(
    authorization_id: str,
    *,
    scope: ResourceScope,
    contents: tuple[str, ...] = (CONTENT_A,),
) -> AuthorizationSetMemberV1:
    return AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": authorization_id,
            "authorization_digest": sha256(f"auth:{authorization_id}".encode()).hexdigest(),
            "review_binding_digest": sha256(f"binding:{authorization_id}".encode()).hexdigest(),
            "scope": scope,
            "scope_digest": scope_digest(scope),
            "allowed_content_sha256": list(contents),
            "allowed_content_count": len(contents),
            "allowed_content_set_sha256": content_set_digest(contents),
            "valid_from": NOW - timedelta(days=1),
            "valid_until": NOW + timedelta(days=30),
        }
    )


def _entry(*, content: str, scope: ResourceScope) -> ReleaseScopePlacementEntryV1:
    return ReleaseScopePlacementEntryV1.model_validate(
        {
            "content_sha256": content,
            "profile_id": scope.collection,
            "profile_version": "v1",
            "profile_fingerprint": "c" * 64,
            "scope": scope,
        }
    )


def test_same_content_different_scope_is_accepted() -> None:
    premiere = _scope(collection="hlp_premiere", niveau="premiere")
    terminale = _scope(collection="hlp_terminale", niveau="terminale")
    placement = ReleaseScopePlacementV2.build(
        placements=[
            _entry(content=CONTENT_A, scope=premiere),
            _entry(content=CONTENT_A, scope=terminale),
        ],
        profile_manifest_digest=MANIFEST_DIGEST,
    )
    authorization_set = AuthorizationSetV2.build(
        members=[
            _member("hlp-premiere", scope=premiere),
            _member("hlp-terminale", scope=terminale),
        ],
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFEST_DIGEST,
        release_scope_placement_digest=placement.digest(),
    )

    assert authorization_set.unique_content_count == 1
    assert authorization_set.authorization_binding_count == 2
    verify_authorization_binding_set_v2(authorization_set, release_scope_placement=placement)


def test_same_content_same_scope_in_two_members_is_refused() -> None:
    """Two members can never legitimately share the exact same scope at
    all (that pre-existing V1 guard is unchanged) -- so this is refused
    one step earlier than the binding-overlap check, by the same
    conclusion: same content, same scope, twice, is never valid."""
    scope = _scope(collection="hlp_premiere", niveau="premiere")
    with pytest.raises(Exception, match="repeat scope"):
        AuthorizationSetV2.build(
            members=[
                _member("hlp-premiere-1", scope=scope),
                _member("hlp-premiere-2", scope=scope),
            ],
            corpus_manifest_sha256="c" * 64,
            profile_manifest_digest=MANIFEST_DIGEST,
            release_scope_placement_digest="e" * 64,
        )


def test_placement_without_matching_authorization_is_refused() -> None:
    """The release scope placement declares a binding no authorization
    covers -- the set-equality gate (R1G section 14) must refuse it."""
    premiere = _scope(collection="hlp_premiere", niveau="premiere")
    terminale = _scope(collection="hlp_terminale", niveau="terminale")
    placement = ReleaseScopePlacementV2.build(
        placements=[
            _entry(content=CONTENT_A, scope=premiere),
            _entry(content=CONTENT_A, scope=terminale),  # no authorization for this one
        ],
        profile_manifest_digest=MANIFEST_DIGEST,
    )
    authorization_set = AuthorizationSetV2.build(
        members=[_member("hlp-premiere", scope=premiere)],
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFEST_DIGEST,
        release_scope_placement_digest=placement.digest(),
    )

    with pytest.raises(AuthorizationSetError, match="required_minus_authorized"):
        verify_authorization_binding_set_v2(authorization_set, release_scope_placement=placement)


def test_authorization_binding_without_placement_is_refused() -> None:
    """An authorization covers a binding the sealed release never actually
    placed -- excess authority, refused the same way."""
    premiere = _scope(collection="hlp_premiere", niveau="premiere")
    terminale = _scope(collection="hlp_terminale", niveau="terminale")
    placement = ReleaseScopePlacementV2.build(
        placements=[_entry(content=CONTENT_A, scope=premiere)],
        profile_manifest_digest=MANIFEST_DIGEST,
    )
    authorization_set = AuthorizationSetV2.build(
        members=[
            _member("hlp-premiere", scope=premiere),
            _member("hlp-terminale", scope=terminale),  # never actually placed
        ],
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFEST_DIGEST,
        release_scope_placement_digest=placement.digest(),
    )

    with pytest.raises(AuthorizationSetError, match="authorized_minus_required"):
        verify_authorization_binding_set_v2(authorization_set, release_scope_placement=placement)


def test_no_implicit_representative_collection_rule_exists() -> None:
    """Guard (R1G section 21): nothing in the V2 mechanism ever silently
    selects a "representative" collection for a multi-placement content --
    both placements/bindings are always required explicitly, never one
    substituted for or preferred over the other."""
    premiere = _scope(collection="hlp_premiere", niveau="premiere")
    terminale = _scope(collection="hlp_terminale", niveau="terminale")
    placement = ReleaseScopePlacementV2.build(
        placements=[
            _entry(content=CONTENT_A, scope=premiere),
            _entry(content=CONTENT_A, scope=terminale),
        ],
        profile_manifest_digest=MANIFEST_DIGEST,
    )
    # Only ONE of the two legitimate placements authorized -- if any
    # implicit "pick one representative scope" rule existed, this would
    # incorrectly pass. It must not.
    authorization_set = AuthorizationSetV2.build(
        members=[_member("hlp-premiere", scope=premiere)],
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest=MANIFEST_DIGEST,
        release_scope_placement_digest=placement.digest(),
    )
    with pytest.raises(AuthorizationSetError):
        verify_authorization_binding_set_v2(authorization_set, release_scope_placement=placement)
