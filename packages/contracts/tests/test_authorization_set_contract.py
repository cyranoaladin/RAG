"""ADR-0044 — contrat de l'ensemble gouverné multi-scope `AuthorizationSetV1`."""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2, git_blob_sha1
from nexus_contracts.authorization_set import (
    AUTHORIZATION_SET_PROTOCOL_VERSION,
    AuthorizationSetError,
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    build_authorization_set,
    canonical_authorization_set_path,
    parse_authorization_set,
)
from nexus_contracts.document import Rights
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    ScopeAuthorizationReviewBindingV1,
    SignedScopeAuthorizationReviewBinding,
    expected_challenge_digest,
    sign_review_binding,
)

REPOSITORY = "cyranoaladin/RAG"
MANIFEST_DIGEST = "a" * 64
BASE_SHA = "c" * 40
HEAD_SHA = "d" * 40
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
TEST_SEED = "33" * 32

_SCOPE_A = ResourceScope(
    tenant="libre_terminale",
    collection="rag_nexus_philosophie_terminale_tc",
    niveau="terminale",
    voie="generale",
    matiere="philosophie",
    candidat="libre",
    audience=["libre", "tous"],
    visibility="internal",
    school_year="2026-2027",
    programme_version="BOEN_special_8_2019-07-25",
)

_SCOPE_B = ResourceScope(
    tenant="libre_seconde",
    collection="rag_nexus_maths_seconde_tc",
    niveau="seconde",
    voie="generale",
    matiere="mathematiques",
    candidat="libre",
    audience=["libre", "tous"],
    visibility="internal",
    school_year="2026-2027",
    programme_version="BOEN_special_1_2019-01-22",
)


def _authorization(
    *, authorization_id: str, scope: ResourceScope, content_sha256: str, **overrides: Any
) -> ScopeAuthorizationArtifactV2:
    fields: dict[str, Any] = {
        "protocol_version": "LOT41A-V2",
        "authorization_id": authorization_id,
        "decision": "AUTHORIZE_INGESTION_SCOPE",
        "scope": scope,
        "manifest_digest": MANIFEST_DIGEST,
        "profile_id": str(scope.collection),
        "profile_version": "v1",
        "profile_fingerprint": "b" * 64,
        "allowed_domains": ("eduscol.education.gouv.fr",),
        "rights_categories": (Rights.officiel_public,),
        "exclusions": (),
        "allowed_content_sha256": (content_sha256,),
        "pii_absence_attested": True,
        "pii_absence_evidence": f"H2 PII evidence; content_sha256={content_sha256}; status=CLEARED",
        "valid_from": NOW - timedelta(hours=1),
        "valid_until": NOW + timedelta(days=7),
    }
    fields.update(overrides)
    return ScopeAuthorizationArtifactV2(**fields)


def _signed_binding_for(
    authorization: ScopeAuthorizationArtifactV2, *, reviewer: str = "abenrhouma"
) -> SignedScopeAuthorizationReviewBinding:
    authorization_bytes = authorization.canonical_bytes()
    binding = ScopeAuthorizationReviewBindingV1.model_validate(
        {
            "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
            "repository": REPOSITORY,
            "pull_request": 130,
            "base_ref": "main",
            "base_sha": BASE_SHA,
            "head_sha": HEAD_SHA,
            "authorization_artifact_path": (
                f"governance/authorizations/{authorization.authorization_id}.json"
            ),
            "authorization_artifact_sha256": hashlib.sha256(authorization_bytes).hexdigest(),
            "authorization_artifact_git_blob_sha1": git_blob_sha1(authorization_bytes),
            "authorization_id": authorization.authorization_id,
            "authorization_decision": "AUTHORIZE_INGESTION_SCOPE",
            "review_id": 900,
            "reviewer_login": reviewer,
            "reviewer_permission": "admin",
            "author_login": "cyranoaladin",
            "submitted_at": "2026-08-22T09:00:00Z",
            "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
            "challenge_digest": expected_challenge_digest(
                repository=REPOSITORY,
                pull_request=130,
                base_ref="main",
                base_sha=BASE_SHA,
                head_sha=HEAD_SHA,
                author="cyranoaladin",
                reviewer=reviewer,
            ),
            "verified_at": "2026-08-22T09:05:00Z",
            "verifier_version": "nexus-review-binding/1",
            "expires_at": "2026-09-22T09:05:00Z",
        }
    )
    return sign_review_binding(binding, private_key_hex=TEST_SEED, key_id="nexus-governance-test-1")


CONTENT_A = "1" * 64
CONTENT_B = "2" * 64


def _valid_set(*, extra_member: bool = True) -> AuthorizationSetV1:
    auth_a = _authorization(authorization_id="auth-a", scope=_SCOPE_A, content_sha256=CONTENT_A)
    authorizations = [auth_a]
    bindings = {"auth-a": _signed_binding_for(auth_a)}
    if extra_member:
        auth_b = _authorization(authorization_id="auth-b", scope=_SCOPE_B, content_sha256=CONTENT_B)
        authorizations.append(auth_b)
        bindings["auth-b"] = _signed_binding_for(auth_b)
    return build_authorization_set(
        authorizations,
        bindings,
        manifest_digest=MANIFEST_DIGEST,
        expected_repository=REPOSITORY,
    )


class TestBuildAuthorizationSet:
    def test_builds_a_valid_two_member_set(self) -> None:
        authorization_set = _valid_set()
        assert authorization_set.authorization_count == 2
        assert authorization_set.union_content_count == 2
        assert {m.authorization_id for m in authorization_set.members} == {"auth-a", "auth-b"}

    def test_single_member_set_is_valid(self) -> None:
        authorization_set = _valid_set(extra_member=False)
        assert authorization_set.authorization_count == 1

    def test_refuses_zero_authorizations(self) -> None:
        with pytest.raises(AuthorizationSetError, match="at least one"):
            build_authorization_set(
                [], {}, manifest_digest=MANIFEST_DIGEST, expected_repository=REPOSITORY
            )

    def test_refuses_duplicate_authorization_id(self) -> None:
        auth_a = _authorization(authorization_id="auth-a", scope=_SCOPE_A, content_sha256=CONTENT_A)
        auth_a_dup = _authorization(
            authorization_id="auth-a", scope=_SCOPE_B, content_sha256=CONTENT_B
        )
        with pytest.raises(AuthorizationSetError, match="duplicate authorization_id"):
            build_authorization_set(
                [auth_a, auth_a_dup],
                {"auth-a": _signed_binding_for(auth_a)},
                manifest_digest=MANIFEST_DIGEST,
                expected_repository=REPOSITORY,
            )

    def test_refuses_missing_review_binding(self) -> None:
        auth_a = _authorization(authorization_id="auth-a", scope=_SCOPE_A, content_sha256=CONTENT_A)
        with pytest.raises(AuthorizationSetError, match="no review binding"):
            build_authorization_set(
                [auth_a], {}, manifest_digest=MANIFEST_DIGEST, expected_repository=REPOSITORY
            )

    def test_refuses_a_member_built_against_a_stale_manifest(self) -> None:
        auth_a = _authorization(authorization_id="auth-a", scope=_SCOPE_A, content_sha256=CONTENT_A)
        with pytest.raises(AuthorizationSetError, match="stale manifest"):
            build_authorization_set(
                [auth_a],
                {"auth-a": _signed_binding_for(auth_a)},
                manifest_digest="f" * 64,
                expected_repository=REPOSITORY,
            )

    def test_refuses_a_mismatched_review_binding(self) -> None:
        auth_a = _authorization(authorization_id="auth-a", scope=_SCOPE_A, content_sha256=CONTENT_A)
        auth_b = _authorization(authorization_id="auth-b", scope=_SCOPE_B, content_sha256=CONTENT_B)
        with pytest.raises(AuthorizationSetError, match="does not match it"):
            build_authorization_set(
                [auth_a],
                {"auth-a": _signed_binding_for(auth_b)},
                manifest_digest=MANIFEST_DIGEST,
                expected_repository=REPOSITORY,
            )

    def test_member_order_of_the_input_never_changes_the_digest(self) -> None:
        auth_a = _authorization(authorization_id="auth-a", scope=_SCOPE_A, content_sha256=CONTENT_A)
        auth_b = _authorization(authorization_id="auth-b", scope=_SCOPE_B, content_sha256=CONTENT_B)
        bindings = {"auth-a": _signed_binding_for(auth_a), "auth-b": _signed_binding_for(auth_b)}
        forward = build_authorization_set(
            [auth_a, auth_b], bindings, manifest_digest=MANIFEST_DIGEST,
            expected_repository=REPOSITORY,
        )
        backward = build_authorization_set(
            [auth_b, auth_a], bindings, manifest_digest=MANIFEST_DIGEST,
            expected_repository=REPOSITORY,
        )
        assert forward.authorization_set_digest == backward.authorization_set_digest
        assert forward.canonical_bytes() == backward.canonical_bytes()

    def test_changing_one_member_changes_the_set_digest(self) -> None:
        baseline = _valid_set()
        auth_a = _authorization(authorization_id="auth-a", scope=_SCOPE_A, content_sha256=CONTENT_A)
        auth_b_changed = _authorization(
            authorization_id="auth-b", scope=_SCOPE_B, content_sha256="3" * 64
        )
        changed = build_authorization_set(
            [auth_a, auth_b_changed],
            {"auth-a": _signed_binding_for(auth_a), "auth-b": _signed_binding_for(auth_b_changed)},
            manifest_digest=MANIFEST_DIGEST,
            expected_repository=REPOSITORY,
        )
        assert baseline.authorization_set_digest != changed.authorization_set_digest


class TestAuthorizationSetModelValidators:
    def test_refuses_members_not_sorted_by_id(self) -> None:
        valid = _valid_set()
        members = list(valid.members)[::-1]  # reverse into "auth-b", "auth-a"
        with pytest.raises(Exception, match="committed sorted"):
            AuthorizationSetV1(
                protocol_version=AUTHORIZATION_SET_PROTOCOL_VERSION,
                manifest_digest=valid.manifest_digest,
                members=tuple(members),
                authorization_count=valid.authorization_count,
                authorization_set_digest=valid.authorization_set_digest,
                union_content_sha256_digest=valid.union_content_sha256_digest,
                union_content_count=valid.union_content_count,
            )

    def test_refuses_overlapping_content_across_members(self) -> None:
        member_a = AuthorizationSetMemberV1(
            authorization_id="auth-a",
            authorization_digest="1" * 64,
            review_binding_digest="2" * 64,
            scope_digest="3" * 64,
            manifest_digest=MANIFEST_DIGEST,
            allowed_content_sha256=(CONTENT_A,),
        )
        member_b = AuthorizationSetMemberV1(
            authorization_id="auth-b",
            authorization_digest="4" * 64,
            review_binding_digest="5" * 64,
            scope_digest="6" * 64,
            manifest_digest=MANIFEST_DIGEST,
            allowed_content_sha256=(CONTENT_A,),  # same content as member_a
        )
        with pytest.raises(Exception, match="overlap on content_sha256"):
            AuthorizationSetV1(
                protocol_version=AUTHORIZATION_SET_PROTOCOL_VERSION,
                manifest_digest=MANIFEST_DIGEST,
                members=(member_a, member_b),
                authorization_count=2,
                authorization_set_digest="7" * 64,
                union_content_sha256_digest="8" * 64,
                union_content_count=1,
            )

    def test_refuses_a_member_manifest_disagreeing_with_the_set(self) -> None:
        valid = _valid_set(extra_member=False)
        bad_member = valid.members[0].model_copy(update={"manifest_digest": "f" * 64})
        with pytest.raises(Exception, match="different manifest_digest|stale manifest"):
            AuthorizationSetV1(
                protocol_version=AUTHORIZATION_SET_PROTOCOL_VERSION,
                manifest_digest=valid.manifest_digest,
                members=(bad_member,),
                authorization_count=1,
                authorization_set_digest=valid.authorization_set_digest,
                union_content_sha256_digest=valid.union_content_sha256_digest,
                union_content_count=valid.union_content_count,
            )

    def test_refuses_a_claimed_union_count_that_does_not_match_members(self) -> None:
        valid = _valid_set()
        with pytest.raises(Exception, match="union_content_count"):
            AuthorizationSetV1(
                protocol_version=AUTHORIZATION_SET_PROTOCOL_VERSION,
                manifest_digest=valid.manifest_digest,
                members=valid.members,
                authorization_count=valid.authorization_count,
                authorization_set_digest=valid.authorization_set_digest,
                union_content_sha256_digest=valid.union_content_sha256_digest,
                union_content_count=999,
            )

    def test_refuses_a_claimed_union_digest_that_does_not_match_members(self) -> None:
        valid = _valid_set()
        with pytest.raises(Exception, match="union_content_sha256_digest"):
            AuthorizationSetV1(
                protocol_version=AUTHORIZATION_SET_PROTOCOL_VERSION,
                manifest_digest=valid.manifest_digest,
                members=valid.members,
                authorization_count=valid.authorization_count,
                authorization_set_digest=valid.authorization_set_digest,
                union_content_sha256_digest="9" * 64,
                union_content_count=valid.union_content_count,
            )

    def test_refuses_a_claimed_set_digest_that_does_not_match_members(self) -> None:
        valid = _valid_set()
        with pytest.raises(Exception, match="authorization_set_digest"):
            AuthorizationSetV1(
                protocol_version=AUTHORIZATION_SET_PROTOCOL_VERSION,
                manifest_digest=valid.manifest_digest,
                members=valid.members,
                authorization_count=valid.authorization_count,
                authorization_set_digest="0" * 64,
                union_content_sha256_digest=valid.union_content_sha256_digest,
                union_content_count=valid.union_content_count,
            )


class TestParseAuthorizationSet:
    def test_round_trip_parses_canonical_bytes(self) -> None:
        valid = _valid_set()
        parsed = parse_authorization_set(valid.canonical_bytes())
        assert parsed.authorization_set_digest == valid.authorization_set_digest

    def test_refuses_non_canonical_bytes(self) -> None:
        valid = _valid_set()
        # Reorder members in the raw JSON without updating the recorded
        # digests -- this must fail model validation (unsorted members),
        # never silently reserialize into canonical form.
        import json

        document = json.loads(valid.canonical_bytes())
        document["members"] = list(reversed(document["members"]))
        tampered = (json.dumps(document, sort_keys=False) + "\n").encode("utf-8")
        with pytest.raises(AuthorizationSetError, match="must be committed sorted"):
            parse_authorization_set(tampered)

    def test_refuses_wrong_protocol_version(self) -> None:
        valid = _valid_set()
        import json

        document = json.loads(valid.canonical_bytes())
        document["protocol_version"] = "NEXUS-AUTHORIZATION-SET-V2"
        raw = (json.dumps(document, sort_keys=True, indent=2) + "\n").encode("utf-8")
        with pytest.raises(Exception, match="protocol_version"):
            parse_authorization_set(raw)


class TestCanonicalPath:
    def test_path_is_addressed_by_digest(self) -> None:
        valid = _valid_set()
        assert valid.canonical_path() == canonical_authorization_set_path(
            valid.authorization_set_digest
        )
        assert valid.canonical_path().startswith("governance/authorization-sets/")

    def test_rejects_a_non_hex_digest(self) -> None:
        with pytest.raises(ValueError, match="64 lowercase"):
            canonical_authorization_set_path("not-a-digest")
