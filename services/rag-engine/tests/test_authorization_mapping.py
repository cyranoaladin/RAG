from __future__ import annotations

import json
from hashlib import sha256

import pytest
from nexus_contracts.authorization_set import (
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    content_set_digest,
    scope_digest,
)
from nexus_contracts.ingestion import ResourceScope

from ingestor.ingestion_worker.authorization_mapping import (
    AuthorizationMapping,
    AuthorizationMappingError,
    build_authorization_mapping,
)

CONTENT_A = "a" * 64
CONTENT_B = "b" * 64


def test_public_constructor_cannot_forge_a_trusted_mapping() -> None:
    with pytest.raises(AuthorizationMappingError, match="factory"):
        AuthorizationMapping(
            authorization_set_digest="0" * 64,
            authority_required_count=1,
            authority_required_set_sha256="1" * 64,
            content_authorization_ids=((CONTENT_A, "forged"),),
            scope_authorization_ids=(("2" * 64, "forged"),),
        )


def _scope(*, collection: str) -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_terminale",
            "collection": collection,
            "niveau": "terminale",
            "voie": "generale",
            "matiere": "philosophie",
            "candidat": "libre",
            "audience": ["libre"],
            "visibility": "internal",
            "school_year": "2026-2027",
            "programme_version": "bo-2026",
        }
    )


def _member(authorization_id: str, content: str, scope: ResourceScope) -> AuthorizationSetMemberV1:
    return AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": authorization_id,
            "authorization_digest": sha256(f"authorization:{authorization_id}".encode()).hexdigest(),
            "review_binding_digest": sha256(f"binding:{authorization_id}".encode()).hexdigest(),
            "scope": scope,
            "scope_digest": scope_digest(scope),
            "allowed_content_sha256": [content],
            "allowed_content_count": 1,
            "allowed_content_set_sha256": content_set_digest([content]),
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_until": "2027-01-01T00:00:00Z",
        }
    )


def _set() -> AuthorizationSetV1:
    members = (
        _member("auth-a", CONTENT_A, _scope(collection="philo_terminale")),
        _member("auth-b", CONTENT_B, _scope(collection="francais_terminale")),
    )
    return AuthorizationSetV1.build(
        members=members,
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest="d" * 64,
        release_scope_placement_digest="e" * 64,
        authority_required_content_sha256=(CONTENT_A, CONTENT_B),
    )


def test_builds_immutable_exact_content_and_scope_lookups() -> None:
    authorization_set = _set()
    raw = bytearray(authorization_set.canonical_bytes())

    mapping = build_authorization_mapping(
        authorization_set_bytes=raw,
        expected_authorization_set_digest=authorization_set.digest(),
        authority_required_content_sha256=[CONTENT_A, CONTENT_B],
    )
    raw[:] = b"{}\n"

    assert mapping.authorization_set_digest == authorization_set.digest()
    assert mapping.authorization_id_for_content(CONTENT_A) == "auth-a"
    assert mapping.authorization_id_for_content(CONTENT_B) == "auth-b"
    assert mapping.authorization_id_for_scope(_scope(collection="philo_terminale")) == "auth-a"
    assert mapping.authorization_id_for_scope_digest(
        scope_digest(_scope(collection="francais_terminale"))
    ) == "auth-b"
    assert mapping.authorization_digest("auth-a") == next(
        member.authorization_digest
        for member in authorization_set.members
        if member.authorization_id == "auth-a"
    )
    assert isinstance(mapping.content_authorization_ids, tuple)
    assert isinstance(mapping.scope_authorization_ids, tuple)


def test_refuses_unknown_authorization_digest_lookup() -> None:
    authorization_set = _set()
    mapping = build_authorization_mapping(
        authorization_set_bytes=authorization_set.canonical_bytes(),
        expected_authorization_set_digest=authorization_set.digest(),
        authority_required_content_sha256=[CONTENT_A, CONTENT_B],
    )
    with pytest.raises(AuthorizationMappingError, match="unknown authorization"):
        mapping.authorization_digest("auth-missing")


@pytest.mark.parametrize(
    ("required", "message"),
    [
        ([CONTENT_A], "extra"),
        ([CONTENT_A, CONTENT_B, "f" * 64], "gap"),
        ([CONTENT_A, CONTENT_A], "repeats"),
    ],
)
def test_refuses_non_exact_required_union(required: list[str], message: str) -> None:
    authorization_set = _set()
    with pytest.raises(AuthorizationMappingError, match=message):
        build_authorization_mapping(
            authorization_set_bytes=authorization_set.canonical_bytes(),
            expected_authorization_set_digest=authorization_set.digest(),
            authority_required_content_sha256=required,
        )


def test_refuses_changed_set_digest() -> None:
    authorization_set = _set()
    with pytest.raises(AuthorizationMappingError, match="digest mismatch"):
        build_authorization_mapping(
            authorization_set_bytes=authorization_set.canonical_bytes(),
            expected_authorization_set_digest="0" * 64,
            authority_required_content_sha256=[CONTENT_A, CONTENT_B],
        )


def test_refuses_unknown_content_and_scope_without_guessing() -> None:
    authorization_set = _set()
    mapping = build_authorization_mapping(
        authorization_set_bytes=authorization_set.canonical_bytes(),
        expected_authorization_set_digest=authorization_set.digest(),
        authority_required_content_sha256=[CONTENT_A, CONTENT_B],
    )

    with pytest.raises(AuthorizationMappingError, match="unknown content"):
        mapping.authorization_id_for_content("f" * 64)
    with pytest.raises(AuthorizationMappingError, match="unknown scope"):
        mapping.authorization_id_for_scope(_scope(collection="unknown"))


def test_refuses_ambiguous_scope_instead_of_selecting_latest() -> None:
    authorization_set = _set()
    document = authorization_set.canonical_document()
    document["members"][1]["scope"] = document["members"][0]["scope"]
    document["members"][1]["scope_digest"] = document["members"][0]["scope_digest"]
    raw = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()

    with pytest.raises(AuthorizationMappingError, match="repeat scope"):
        build_authorization_mapping(
            authorization_set_bytes=raw,
            expected_authorization_set_digest=sha256(raw).hexdigest(),
            authority_required_content_sha256=[CONTENT_A, CONTENT_B],
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("overlap", "overlap"),
        ("duplicate_authorization", "repeat authorization_id"),
        ("duplicate_content", "contains duplicates"),
    ],
)
def test_refuses_overlapping_or_duplicate_claims(
    mutation: str, message: str
) -> None:
    document = _set().canonical_document()
    if mutation == "overlap":
        document["members"][1]["allowed_content_sha256"] = [CONTENT_A]
        document["members"][1]["allowed_content_set_sha256"] = content_set_digest(
            [CONTENT_A]
        )
    elif mutation == "duplicate_authorization":
        document["members"][1]["authorization_id"] = "auth-a"
    else:
        document["members"][0]["allowed_content_sha256"] = [CONTENT_A, CONTENT_A]
        document["members"][0]["allowed_content_count"] = 2
        document["members"][0]["allowed_content_set_sha256"] = content_set_digest(
            [CONTENT_A, CONTENT_A]
        )
    raw = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()

    with pytest.raises(AuthorizationMappingError, match=message):
        build_authorization_mapping(
            authorization_set_bytes=raw,
            expected_authorization_set_digest=sha256(raw).hexdigest(),
            authority_required_content_sha256=[CONTENT_A, CONTENT_B],
        )


def test_refuses_unknown_or_noncanonical_lookup_sha() -> None:
    authorization_set = _set()
    mapping = build_authorization_mapping(
        authorization_set_bytes=authorization_set.canonical_bytes(),
        expected_authorization_set_digest=authorization_set.digest(),
        authority_required_content_sha256=[CONTENT_A, CONTENT_B],
    )

    with pytest.raises(AuthorizationMappingError, match="lowercase SHA-256"):
        mapping.authorization_id_for_content(CONTENT_A.upper())
    with pytest.raises(AuthorizationMappingError, match="lowercase SHA-256"):
        mapping.authorization_id_for_scope_digest("not-a-digest")
