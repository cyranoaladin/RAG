"""Contrat canonique de composition multi-autorisation (ADR-0044)."""
from __future__ import annotations

import json
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any

import pytest
from nexus_contracts.authorization_set import (
    AUTHORIZATION_SET_PROTOCOL_VERSION,
    AuthorizationSetError,
    AuthorizationSetMemberV1,
    AuthorizationSetV1,
    ReleaseScopePlacementEntryV1,
    ReleaseScopePlacementV1,
    VerifiedProfileFactV1,
    VerifiedAuthorizationSetV1,
    canonical_review_binding_path,
    parse_authorization_set,
    parse_release_scope_placement,
    resolve_authorization_set_material,
    _verify_authorization_set_invariants,
    verify_authorization_set,
    _verify_authorization_set_scope_facts,
    _verify_authorization_set_material,
)
from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
)
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.review_binding import (
    REVIEW_BINDING_PROTOCOL_VERSION,
    ScopeAuthorizationReviewBindingV1,
    TrustAnchor,
    expected_challenge_digest,
    public_key_hex,
    sign_review_binding,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
SHA_A = "1" * 64
SHA_B = "2" * 64
SHA_C = "3" * 64
TEST_SEED = "11" * 32


def _scope(*, collection: str = "francais_seconde", matiere: str = "francais") -> ResourceScope:
    return ResourceScope.model_validate(
        {
            "tenant": "libre_seconde",
            "collection": collection,
            "niveau": "seconde",
            "voie": "generale",
            "matiere": matiere,
            "candidat": "libre",
            "audience": ["libre", "aefe"],
            "visibility": "public",
            "school_year": "2026-2027",
            "programme_version": "2026",
        }
    )


def _content_digest(values: tuple[str, ...]) -> str:
    return sha256(("".join(f"{value}\n" for value in sorted(values))).encode()).hexdigest()


def _canonical_json(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode()


def _scope_digest(scope: ResourceScope) -> str:
    document = scope.model_dump(mode="json")
    document["audience"] = sorted(document["audience"])
    raw = (json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    return sha256(raw).hexdigest()


def _member(
    authorization_id: str = "auth-francais-v1",
    *,
    scope: ResourceScope | None = None,
    contents: tuple[str, ...] = (SHA_A,),
    authorization_digest: str = "a" * 64,
    review_binding_digest: str = "b" * 64,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> AuthorizationSetMemberV1:
    selected_scope = scope or _scope()
    return AuthorizationSetMemberV1.model_validate(
        {
            "authorization_id": authorization_id,
            "authorization_digest": authorization_digest,
            "review_binding_digest": review_binding_digest,
            "scope": selected_scope,
            "scope_digest": _scope_digest(selected_scope),
            "allowed_content_sha256": list(contents),
            "allowed_content_count": len(contents),
            "allowed_content_set_sha256": _content_digest(contents),
            "valid_from": valid_from or NOW - timedelta(days=1),
            "valid_until": valid_until or NOW + timedelta(days=30),
        }
    )


def _set(*members: AuthorizationSetMemberV1) -> AuthorizationSetV1:
    selected = members or (_member(),)
    required = tuple(sorted(content for member in selected for content in member.allowed_content_sha256))
    return AuthorizationSetV1.build(
        members=selected,
        corpus_manifest_sha256="c" * 64,
        profile_manifest_digest="d" * 64,
        release_scope_placement_digest="e" * 64,
        authority_required_content_sha256=required,
    )


def _authorization(
    *,
    authorization_id: str = "auth-francais-v1",
    scope: ResourceScope | None = None,
    contents: tuple[str, ...] = (SHA_A,),
    profile_id: str = "profile-francais-seconde",
    profile_version: str = "1",
    profile_fingerprint: str = "4" * 64,
) -> ScopeAuthorizationArtifactV2:
    return ScopeAuthorizationArtifactV2.model_validate(
        {
            "protocol_version": "LOT41A-V2",
            "authorization_id": authorization_id,
            "decision": "AUTHORIZE_INGESTION_SCOPE",
            "scope": scope or _scope(),
            "manifest_digest": "d" * 64,
            "profile_id": profile_id,
            "profile_version": profile_version,
            "profile_fingerprint": profile_fingerprint,
            "allowed_domains": ["education.gouv.fr"],
            "rights_categories": ["officiel_public"],
            "exclusions": [],
            "pii_absence_attested": True,
            "pii_absence_evidence": "pii-campaign-v1",
            "valid_from": NOW - timedelta(days=1),
            "valid_until": NOW + timedelta(days=30),
            "allowed_content_sha256": list(contents),
        }
    )


def _binding_bytes(
    authorization: ScopeAuthorizationArtifactV2, **overrides: Any
) -> bytes:
    raw = authorization.canonical_bytes()
    document: dict[str, Any] = {
        "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
        "repository": "cyranoaladin/RAG",
        "pull_request": 127,
        "base_ref": "main",
        "base_sha": "a" * 40,
        "head_sha": "b" * 40,
        "authorization_artifact_path": authorization.canonical_path(),
        "authorization_artifact_sha256": sha256(raw).hexdigest(),
        "authorization_artifact_git_blob_sha1": git_blob_sha1(raw),
        "authorization_id": authorization.authorization_id,
        "authorization_decision": "AUTHORIZE_INGESTION_SCOPE",
        "review_id": 900,
        "reviewer_login": "abenrhouma",
        "reviewer_permission": "admin",
        "author_login": "cyranoaladin",
        "submitted_at": NOW - timedelta(hours=4),
        "challenge_protocol": "NEXUS-TRUSTED-REVIEW-V1",
        "verified_at": NOW - timedelta(hours=3),
        "verifier_version": "nexus-review-binding/1",
        "expires_at": NOW + timedelta(days=7),
    }
    document.update(overrides)
    challenge = expected_challenge_digest(
        repository=document["repository"],
        pull_request=document["pull_request"],
        base_ref=document["base_ref"],
        base_sha=document["base_sha"],
        head_sha=document["head_sha"],
        author=document["author_login"],
        reviewer=document["reviewer_login"],
    )
    document.setdefault("challenge_digest", challenge)
    binding = ScopeAuthorizationReviewBindingV1.model_validate(document)
    return sign_review_binding(
        binding, private_key_hex=TEST_SEED, key_id="nexus-test-key"
    ).canonical_bytes()


def _set_and_material(
    *, binding_overrides: dict[str, Any] | None = None
) -> tuple[AuthorizationSetV1, dict[str, bytes]]:
    authorization = _authorization()
    authorization_raw = authorization.canonical_bytes()
    binding_raw = _binding_bytes(authorization, **(binding_overrides or {}))
    member = _member(
        authorization_id=authorization.authorization_id,
        scope=authorization.scope,
        contents=authorization.allowed_content_sha256,
        authorization_digest=sha256(authorization_raw).hexdigest(),
        review_binding_digest=sha256(binding_raw).hexdigest(),
    )
    authorization_set = _set(member)
    return authorization_set, {
        canonical_authorization_path(authorization.authorization_id): authorization_raw,
        canonical_review_binding_path(authorization.authorization_id): binding_raw,
    }


def _trust_anchor() -> TrustAnchor:
    return TrustAnchor.model_validate(
        {
            "protocol_version": REVIEW_BINDING_PROTOCOL_VERSION,
            "keys": [
                {
                    "key_id": "nexus-test-key",
                    "algorithm": "ed25519",
                    "public_key": public_key_hex(TEST_SEED),
                    "environment": "test",
                }
            ],
        }
    )


def _verify_material(
    authorization_set: AuthorizationSetV1,
    material: dict[str, bytes],
    *,
    now: datetime = NOW,
) -> dict[str, Any]:
    return _verify_authorization_set_material(
        authorization_set,
        release_files=material,
        trust_anchor=_trust_anchor(),
        environment="test",
        now=now,
        expected_repository="cyranoaladin/RAG",
        accepted_reviewers=("abenrhouma",),
    )


def _placement_entry(**overrides: Any) -> ReleaseScopePlacementEntryV1:
    document: dict[str, Any] = {
        "content_sha256": SHA_A,
        "profile_id": "profile-francais-seconde",
        "profile_version": "1",
        "profile_fingerprint": "4" * 64,
        "scope": _scope(),
    }
    document.update(overrides)
    return ReleaseScopePlacementEntryV1.model_validate(document)


def _placement(*entries: ReleaseScopePlacementEntryV1) -> ReleaseScopePlacementV1:
    return ReleaseScopePlacementV1.build(
        placements=entries or (_placement_entry(),),
        profile_manifest_digest="d" * 64,
    )


def _profile_fact(**overrides: Any) -> VerifiedProfileFactV1:
    document: dict[str, Any] = {
        "profile_id": "profile-francais-seconde",
        "profile_version": "1",
        "profile_fingerprint": "4" * 64,
        "scope": _scope(),
    }
    document.update(overrides)
    return VerifiedProfileFactV1.model_validate(document)


def _verified_scope_inputs() -> tuple[
    AuthorizationSetV1,
    dict[str, Any],
    ReleaseScopePlacementV1,
    tuple[VerifiedProfileFactV1, ...],
]:
    authorization_set, material = _set_and_material()
    verified = _verify_material(authorization_set, material)
    placement = _placement()
    return (
        authorization_set.model_copy(
            update={"release_scope_placement_digest": placement.digest()}
        ),
        verified,
        placement,
        (_profile_fact(),),
    )


class TestStructureAndCanonicalization:
    def test_zero_members_is_refused(self) -> None:
        with pytest.raises(AuthorizationSetError, match="at least one member"):
            AuthorizationSetV1.build(
                members=(),
                corpus_manifest_sha256="c" * 64,
                profile_manifest_digest="d" * 64,
                release_scope_placement_digest="e" * 64,
                authority_required_content_sha256=(),
            )

    def test_noncanonical_authorization_id_is_refused(self) -> None:
        with pytest.raises(Exception, match="authorization_id"):
            _member(authorization_id="../escape")

    @pytest.mark.parametrize(
        ("contents", "message"),
        [
            (("A" * 64,), "lowercase"),
            ((SHA_B, SHA_A), "sorted"),
            ((SHA_A, SHA_A), "duplicates"),
        ],
    )
    def test_member_content_list_is_intrinsically_canonical(
        self, contents: tuple[str, ...], message: str
    ) -> None:
        with pytest.raises(Exception, match=message):
            _member(contents=contents)

    @pytest.mark.parametrize(
        ("member_update", "message"),
        [
            ({"allowed_content_count": 2}, "allowed_content_count"),
            ({"allowed_content_set_sha256": "0" * 64}, "allowed_content_set_sha256"),
            ({"scope_digest": "0" * 64}, "scope_digest"),
            ({"valid_until": NOW - timedelta(days=2)}, "valid_until"),
        ],
    )
    def test_member_derived_facts_are_intrinsically_valid(
        self, member_update: dict[str, Any], message: str
    ) -> None:
        document = _member().model_dump(mode="json")
        document.update(member_update)
        with pytest.raises(Exception, match=message):
            AuthorizationSetMemberV1.model_validate(document)

    @pytest.mark.parametrize(
        ("document_update", "message"),
        [
            ({"authorization_count": 2}, "authorization_count"),
            (
                {"authorizations_effective_valid_from": "2026-08-20T12:00:00Z"},
                "effective_valid_from",
            ),
            (
                {"authorizations_effective_valid_until": "2026-09-30T12:00:00Z"},
                "effective_valid_until",
            ),
            ({"union_content_count": 2}, "union_content_count"),
            ({"union_content_sha256_digest": "0" * 64}, "union_content_sha256"),
            ({"authority_required_count": 2}, "authority_required_count"),
            ({"authority_required_set_sha256": "0" * 64}, "authority_required_set"),
        ],
    )
    def test_canonical_parse_refuses_intrinsically_inconsistent_set(
        self, document_update: dict[str, Any], message: str
    ) -> None:
        document = _set(_member()).canonical_document()
        document.update(document_update)
        with pytest.raises(AuthorizationSetError, match=message):
            parse_authorization_set(_canonical_json(document))

    def test_set_intrinsically_refuses_overlap(self) -> None:
        second = _member(
            "auth-maths-v1",
            scope=_scope(collection="maths_seconde", matiere="maths"),
            contents=(SHA_A,),
            authorization_digest="f" * 64,
            review_binding_digest="9" * 64,
        )
        with pytest.raises(AuthorizationSetError, match="overlap"):
            _set(_member(), second)

    @pytest.mark.parametrize(
        ("changed", "message"),
        [
            ({"authorization_id": "auth-francais-v1"}, "authorization_id"),
            ({"authorization_digest": "a" * 64}, "authorization_digest"),
            ({"review_binding_digest": "b" * 64}, "review_binding_digest"),
            ({"scope": _scope()}, "scope"),
        ],
    )
    def test_duplicate_member_identity_is_refused(
        self, changed: dict[str, Any], message: str
    ) -> None:
        first = _member()
        kwargs: dict[str, Any] = {
            "authorization_id": "auth-maths-v1",
            "scope": _scope(collection="maths_seconde", matiere="maths"),
            "authorization_digest": "f" * 64,
            "review_binding_digest": "9" * 64,
            "contents": (SHA_B,),
        }
        kwargs.update(changed)
        with pytest.raises(AuthorizationSetError, match=message):
            _set(first, _member(**kwargs))

    def test_input_permutation_has_one_canonical_digest(self) -> None:
        first = _member()
        second = _member(
            "auth-maths-v1",
            scope=_scope(collection="maths_seconde", matiere="maths"),
            contents=(SHA_B,),
            authorization_digest="f" * 64,
            review_binding_digest="9" * 64,
        )
        assert _set(first, second).digest() == _set(second, first).digest()

    def test_changed_member_changes_the_set_digest(self) -> None:
        assert _set(_member()).digest() != _set(
            _member(review_binding_digest="8" * 64)
        ).digest()

    def test_changed_authorization_digest_changes_the_set_digest(self) -> None:
        assert _set(_member()).digest() != _set(
            _member(authorization_digest="8" * 64)
        ).digest()

    def test_canonical_document_declares_exact_protocol(self) -> None:
        assert _set(_member()).canonical_document()["protocol_version"] == (
            AUTHORIZATION_SET_PROTOCOL_VERSION
        )

    def test_noncanonical_persisted_bytes_are_refused(self) -> None:
        document = _set(_member()).canonical_document()
        raw = json.dumps(document, ensure_ascii=False, indent=4, sort_keys=True).encode()
        with pytest.raises(AuthorizationSetError, match="not in canonical form"):
            parse_authorization_set(raw)

    def test_release_scope_placement_is_a_strict_protocol(self) -> None:
        with pytest.raises(Exception, match="Extra inputs are not permitted"):
            ReleaseScopePlacementV1.model_validate(
                {"protocol_version": "NEXUS-RELEASE-SCOPE-PLACEMENT-V1", "extra": True}
            )

    def test_release_scope_placement_round_trips_canonical_jsonl(self) -> None:
        placement = _placement()
        parsed = parse_release_scope_placement(placement.canonical_bytes())
        assert parsed.canonical_bytes() == placement.canonical_bytes()

    def test_noncanonical_release_scope_placement_bytes_are_refused(self) -> None:
        raw = _placement().canonical_bytes() + b"\n"
        with pytest.raises(AuthorizationSetError, match="not in canonical form"):
            parse_release_scope_placement(raw)

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("profile_id", "profil\u2028officiel"),
            ("profile_version", "version\u0085canonique"),
        ],
    )
    def test_release_scope_placement_round_trips_unicode_line_separators(
        self, field: str, value: str
    ) -> None:
        placement = _placement(_placement_entry(**{field: value}))
        raw = placement.canonical_bytes()
        assert parse_release_scope_placement(raw).canonical_bytes() == raw


class TestExactMemberMaterial:
    def test_member_paths_are_derived_from_authorization_id(self) -> None:
        assert canonical_authorization_path("auth-francais-v1") == (
            "governance/authorizations/auth-francais-v1.json"
        )
        assert canonical_review_binding_path("auth-francais-v1") == (
            "governance/review-bindings/auth-francais-v1.json"
        )

    def test_missing_declared_material_is_refused(self) -> None:
        authorization_set, material = _set_and_material()
        material.pop(canonical_review_binding_path("auth-francais-v1"))
        with pytest.raises(AuthorizationSetError, match="missing release material"):
            _verify_material(authorization_set, material)

    def test_supplied_extra_release_material_is_refused(self) -> None:
        authorization_set, material = _set_and_material()
        material["governance/authorizations/extra.json"] = b"{}\n"
        with pytest.raises(AuthorizationSetError, match="extra release material"):
            _verify_material(authorization_set, material)

    def test_wrong_authorization_digest_is_refused(self) -> None:
        authorization_set, material = _set_and_material()
        changed = authorization_set.model_copy(
            update={
                "members": (
                    authorization_set.members[0].model_copy(
                        update={"authorization_digest": "0" * 64}
                    ),
                )
            }
        )
        with pytest.raises(AuthorizationSetError, match="authorization_digest"):
            _verify_material(changed, material)

    def test_wrong_review_binding_digest_is_refused(self) -> None:
        authorization_set, material = _set_and_material()
        changed = authorization_set.model_copy(
            update={
                "members": (
                    authorization_set.members[0].model_copy(
                        update={"review_binding_digest": "0" * 64}
                    ),
                )
            }
        )
        with pytest.raises(AuthorizationSetError, match="review_binding_digest"):
            _verify_material(changed, material)

    def test_unrelated_historical_root_files_are_not_release_extras(self) -> None:
        authorization_set, material = _set_and_material()
        governed_root = {
            **material,
            "governance/authorizations/historical-v1.json": b"historical",
            "governance/review-bindings/historical-v1.json": b"historical",
        }
        release_material = resolve_authorization_set_material(
            authorization_set, governed_files=governed_root
        )
        assert set(release_material) == set(material)
        verified = _verify_material(authorization_set, release_material)
        assert set(verified) == {"auth-francais-v1"}

    def test_production_refuses_omitted_accepted_reviewers(self) -> None:
        authorization_set, material = _set_and_material()
        with pytest.raises(AuthorizationSetError, match="production.*reviewers"):
            _verify_authorization_set_material(
                authorization_set,
                release_files=material,
                trust_anchor=_trust_anchor(),
                environment="production",
                now=NOW,
                expected_repository="cyranoaladin/RAG",
            )

    def test_production_refuses_empty_accepted_reviewers(self) -> None:
        authorization_set, material = _set_and_material()
        with pytest.raises(AuthorizationSetError, match="production.*reviewers"):
            _verify_authorization_set_material(
                authorization_set,
                release_files=material,
                trust_anchor=_trust_anchor(),
                environment="production",
                now=NOW,
                expected_repository="cyranoaladin/RAG",
                accepted_reviewers=(),
            )

    def test_test_environment_may_explicitly_omit_reviewer_allowlist(self) -> None:
        authorization_set, material = _set_and_material()
        verified = _verify_authorization_set_material(
            authorization_set,
            release_files=material,
            trust_anchor=_trust_anchor(),
            environment="test",
            now=NOW,
            expected_repository="cyranoaladin/RAG",
            accepted_reviewers=None,
        )
        assert set(verified) == {"auth-francais-v1"}

    def test_invalid_review_binding_signature_is_refused(self) -> None:
        authorization_set, material = _set_and_material()
        path = canonical_review_binding_path("auth-francais-v1")
        document = json.loads(material[path])
        document["signature"] = "0" * 128
        raw = (
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
        material[path] = raw
        member = authorization_set.members[0].model_copy(
            update={"review_binding_digest": sha256(raw).hexdigest()}
        )
        authorization_set = authorization_set.model_copy(update={"members": (member,)})
        with pytest.raises(AuthorizationSetError, match="signature does not verify"):
            _verify_material(authorization_set, material)

    def test_internal_review_binding_digest_mismatch_is_refused(self) -> None:
        authorization_set, material = _set_and_material()
        path = canonical_review_binding_path("auth-francais-v1")
        document = json.loads(material[path])
        document["binding_digest"] = "0" * 64
        raw = (
            json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode()
        material[path] = raw
        member = authorization_set.members[0].model_copy(
            update={"review_binding_digest": sha256(raw).hexdigest()}
        )
        authorization_set = authorization_set.model_copy(update={"members": (member,)})
        with pytest.raises(AuthorizationSetError, match="binding_digest does not describe"):
            _verify_material(authorization_set, material)

    @pytest.mark.parametrize(
        ("binding_overrides", "message"),
        [
            ({"expires_at": NOW}, "expired"),
            ({"verified_at": NOW + timedelta(seconds=1)}, "in the future"),
            ({"repository": "other/repository"}, "another repository"),
            ({"authorization_id": "other-authorization"}, "covers authorization"),
            (
                {
                    "authorization_artifact_path": (
                        "governance/authorizations/other-authorization.json"
                    )
                },
                "canonical path",
            ),
            ({"authorization_artifact_sha256": "0" * 64}, "different authorization bytes"),
            ({"reviewer_login": "rogue-reviewer"}, "trusted reviewers"),
        ],
    )
    def test_cryptographically_valid_but_unbound_receipt_is_refused(
        self, binding_overrides: dict[str, Any], message: str
    ) -> None:
        authorization_set, material = _set_and_material(
            binding_overrides=binding_overrides
        )
        with pytest.raises(AuthorizationSetError, match=message):
            _verify_material(authorization_set, material)

    def test_unbound_trusted_review_challenge_is_refused(self) -> None:
        authorization_set, material = _set_and_material(
            binding_overrides={"challenge_digest": "0" * 64}
        )
        with pytest.raises(AuthorizationSetError, match="challenge"):
            _verify_material(authorization_set, material)


class TestIndependentPlacementAndProfileFacts:
    def test_exact_independent_facts_are_accepted(self) -> None:
        authorization_set, verified, placement, profiles = _verified_scope_inputs()
        _verify_authorization_set_scope_facts(
            authorization_set,
            verified_members=verified,
            release_scope_placement=placement,
            verified_profiles=profiles,
        )

    def test_wrong_content_mapping_is_refused(self) -> None:
        authorization_set, verified, _, profiles = _verified_scope_inputs()
        placement = _placement(_placement_entry(content_sha256=SHA_B))
        authorization_set = authorization_set.model_copy(
            update={"release_scope_placement_digest": placement.digest()}
        )
        with pytest.raises(AuthorizationSetError, match="placement content"):
            _verify_authorization_set_scope_facts(
                authorization_set,
                verified_members=verified,
                release_scope_placement=placement,
                verified_profiles=profiles,
            )


def _revocations(*authorization_ids: str) -> bytes:
    return json.dumps(
        {
            "protocol_version": "NEXUS-AUTHORIZATION-REVOCATIONS-V1",
            "revoked_authorization_ids": list(authorization_ids),
        }
    ).encode()


class TestRevocationTimeOverlapAndExactUnion:
    def test_valid_exact_union_is_accepted_and_returns_the_aggregate_window(
        self,
    ) -> None:
        authorization_set = _set(_member())
        window = _verify_authorization_set_invariants(
            authorization_set,
            revocation_registry_raw=_revocations(),
            now=NOW,
            authority_required_content_sha256=(SHA_A,),
        )
        assert window == (
            authorization_set.authorizations_effective_valid_from,
            authorization_set.authorizations_effective_valid_until,
        )

    def test_one_revoked_authorization_is_refused(self) -> None:
        with pytest.raises(AuthorizationSetError, match="revoked"):
            _verify_authorization_set_invariants(
                _set(_member()),
                revocation_registry_raw=_revocations("auth-francais-v1"),
                now=NOW,
                authority_required_content_sha256=(SHA_A,),
            )

    def test_one_expired_authorization_is_refused(self) -> None:
        authorization_set = _set(
            _member(
                valid_from=NOW - timedelta(days=2),
                valid_until=NOW - timedelta(seconds=1),
            )
        )
        with pytest.raises(AuthorizationSetError, match="expired"):
            _verify_authorization_set_invariants(
                authorization_set,
                revocation_registry_raw=_revocations(),
                now=NOW,
                authority_required_content_sha256=(SHA_A,),
            )

    def test_one_future_authorization_is_refused(self) -> None:
        authorization_set = _set(
            _member(
                valid_from=NOW + timedelta(seconds=1),
                valid_until=NOW + timedelta(days=1),
            )
        )
        with pytest.raises(AuthorizationSetError, match="not valid yet"):
            _verify_authorization_set_invariants(
                authorization_set,
                revocation_registry_raw=_revocations(),
                now=NOW,
                authority_required_content_sha256=(SHA_A,),
            )

    def test_now_equal_to_valid_until_is_refused(self) -> None:
        authorization_set = _set(
            _member(valid_from=NOW - timedelta(days=1), valid_until=NOW)
        )
        with pytest.raises(AuthorizationSetError, match="expired"):
            _verify_authorization_set_invariants(
                authorization_set,
                revocation_registry_raw=_revocations(),
                now=NOW,
                authority_required_content_sha256=(SHA_A,),
            )

    def test_overlapping_content_claims_are_refused(self) -> None:
        second = _member(
            "auth-maths-v1",
            scope=_scope(collection="maths_seconde", matiere="maths"),
            contents=(SHA_A,),
            authorization_digest="f" * 64,
            review_binding_digest="9" * 64,
        )
        with pytest.raises(AuthorizationSetError, match="overlap"):
            _verify_authorization_set_invariants(
                _set(_member(), second),
                revocation_registry_raw=_revocations(),
                now=NOW,
                authority_required_content_sha256=(SHA_A,),
            )

    def test_duplicate_content_inside_one_member_is_refused(self) -> None:
        with pytest.raises(Exception, match="duplicates"):
            _member(contents=(SHA_A, SHA_A))

    def test_required_set_gap_is_refused(self) -> None:
        with pytest.raises(AuthorizationSetError, match="gap"):
            _verify_authorization_set_invariants(
                _set(_member()),
                revocation_registry_raw=_revocations(),
                now=NOW,
                authority_required_content_sha256=(SHA_A, SHA_B),
            )

    def test_extra_content_is_refused(self) -> None:
        with pytest.raises(AuthorizationSetError, match="extra"):
            _verify_authorization_set_invariants(
                _set(_member(contents=(SHA_A, SHA_B))),
                revocation_registry_raw=_revocations(),
                now=NOW,
                authority_required_content_sha256=(SHA_A,),
            )

    def test_runtime_legacy_revocation_schema_is_not_accepted_as_shared(self) -> None:
        crossed = json.dumps(
            {
                "registry_version": "1",
                "revoked": [{"kind": "scope_authorization", "id": "auth-francais-v1"}],
            }
        ).encode()
        with pytest.raises(AuthorizationSetError, match="REVOCATION_REGISTRY_INVALID"):
            _verify_authorization_set_invariants(
                _set(_member()),
                revocation_registry_raw=crossed,
                now=NOW,
                authority_required_content_sha256=(SHA_A,),
            )


class TestIndependentPlacementAndProfileFactsContinued:
    @pytest.mark.parametrize(
        ("changed", "message"),
        [
            ({"profile_id": "profile-francais-autre"}, "profile_id"),
            ({"profile_version": "2"}, "profile_version"),
            ({"profile_fingerprint": "5" * 64}, "profile_fingerprint"),
            (
                {
                    "scope": _scope(
                        collection="francais_interne", matiere="francais"
                    )
                },
                "scope",
            ),
        ],
    )
    def test_wrong_placement_profile_fact_is_refused(
        self, changed: dict[str, Any], message: str
    ) -> None:
        authorization_set, verified, _, _ = _verified_scope_inputs()
        entry = _placement_entry(**changed)
        placement = _placement(entry)
        profile = _profile_fact(**changed)
        authorization_set = authorization_set.model_copy(
            update={"release_scope_placement_digest": placement.digest()}
        )
        with pytest.raises(AuthorizationSetError, match=message):
            _verify_authorization_set_scope_facts(
                authorization_set,
                verified_members=verified,
                release_scope_placement=placement,
                verified_profiles=(profile,),
            )

    def test_wrong_verified_profile_scope_is_refused(self) -> None:
        authorization_set, verified, placement, _ = _verified_scope_inputs()
        with pytest.raises(AuthorizationSetError, match="verified profile scope"):
            _verify_authorization_set_scope_facts(
                authorization_set,
                verified_members=verified,
                release_scope_placement=placement,
                verified_profiles=(
                    _profile_fact(
                        scope=_scope(
                            collection="francais_interne", matiere="francais"
                        )
                    ),
                ),
            )

    def test_wrong_projection_digest_is_refused(self) -> None:
        authorization_set, verified, placement, profiles = _verified_scope_inputs()
        authorization_set = authorization_set.model_copy(
            update={"release_scope_placement_digest": "0" * 64}
        )
        with pytest.raises(AuthorizationSetError, match="placement digest"):
            _verify_authorization_set_scope_facts(
                authorization_set,
                verified_members=verified,
                release_scope_placement=placement,
                verified_profiles=profiles,
            )


class TestGlobalVerificationBoundary:
    def _inputs(self) -> tuple[
        AuthorizationSetV1,
        dict[str, bytes],
        ReleaseScopePlacementV1,
        tuple[VerifiedProfileFactV1, ...],
    ]:
        authorization_set, material = _set_and_material()
        placement = _placement()
        return (
            authorization_set.model_copy(
                update={"release_scope_placement_digest": placement.digest()}
            ),
            material,
            placement,
            (_profile_fact(),),
        )

    def _verify(self, *, revoked: tuple[str, ...] = ()) -> VerifiedAuthorizationSetV1:
        authorization_set, material, placement, profiles = self._inputs()
        return verify_authorization_set(
            authorization_set,
            release_files=material,
            trust_anchor=_trust_anchor(),
            environment="test",
            now=NOW,
            expected_repository="cyranoaladin/RAG",
            accepted_reviewers=("abenrhouma",),
            release_scope_placement=placement,
            verified_profiles=profiles,
            revocation_registry_raw=_revocations(*revoked),
            authority_required_content_sha256=(SHA_A,),
        )

    def test_only_global_boundary_returns_verified_aggregate(self) -> None:
        result = self._verify()
        assert isinstance(result, VerifiedAuthorizationSetV1)
        assert not hasattr(result, "authorization_set")
        parsed = parse_authorization_set(result.authorization_set_bytes)
        assert parsed.digest() == result.authorization_set_digest
        assert result.content_authorization_ids == ((SHA_A, "auth-francais-v1"),)
        assert result.scope_authorization_ids == (
            (_scope_digest(_scope()), "auth-francais-v1"),
        )

    def test_verified_snapshot_cannot_be_mutated(self) -> None:
        result = self._verify()
        with pytest.raises(FrozenInstanceError):
            result.authorization_set_digest = "0" * 64  # type: ignore[misc]
        with pytest.raises(TypeError):
            result.authorization_set_bytes[0] = 0  # type: ignore[index]

    def test_partial_material_result_is_not_a_verified_aggregate(self) -> None:
        authorization_set, material, _, _ = self._inputs()
        partial = _verify_material(authorization_set, material)
        assert not isinstance(partial, VerifiedAuthorizationSetV1)

    def test_global_boundary_refuses_a_revoked_member(self) -> None:
        with pytest.raises(AuthorizationSetError, match="revoked"):
            self._verify(revoked=("auth-francais-v1",))

    def test_review_time_aggregates_cover_all_cryptographically_verified_bindings(
        self,
    ) -> None:
        first = _authorization()
        second_scope = _scope(collection="maths_seconde", matiere="maths")
        second = _authorization(
            authorization_id="auth-maths-v1",
            scope=second_scope,
            contents=(SHA_B,),
            profile_id="profile-maths-seconde",
            profile_fingerprint="5" * 64,
        )
        first_binding = _binding_bytes(
            first,
            submitted_at=NOW - timedelta(days=5),
            verified_at=NOW - timedelta(days=1),
            expires_at=NOW + timedelta(days=5),
        )
        second_binding = _binding_bytes(
            second,
            submitted_at=NOW - timedelta(days=4),
            verified_at=NOW - timedelta(days=3),
            expires_at=NOW + timedelta(days=3),
        )
        first_raw = first.canonical_bytes()
        second_raw = second.canonical_bytes()
        members = (
            _member(
                authorization_id=first.authorization_id,
                scope=first.scope,
                contents=first.allowed_content_sha256,
                authorization_digest=sha256(first_raw).hexdigest(),
                review_binding_digest=sha256(first_binding).hexdigest(),
            ),
            _member(
                authorization_id=second.authorization_id,
                scope=second.scope,
                contents=second.allowed_content_sha256,
                authorization_digest=sha256(second_raw).hexdigest(),
                review_binding_digest=sha256(second_binding).hexdigest(),
            ),
        )
        placement = _placement(
            _placement_entry(),
            _placement_entry(
                content_sha256=SHA_B,
                profile_id="profile-maths-seconde",
                profile_fingerprint="5" * 64,
                scope=second_scope,
            ),
        )
        authorization_set = AuthorizationSetV1.build(
            members=members,
            corpus_manifest_sha256="c" * 64,
            profile_manifest_digest="d" * 64,
            release_scope_placement_digest=placement.digest(),
            authority_required_content_sha256=(SHA_A, SHA_B),
        )
        material = {
            first.canonical_path(): first_raw,
            canonical_review_binding_path(first.authorization_id): first_binding,
            second.canonical_path(): second_raw,
            canonical_review_binding_path(second.authorization_id): second_binding,
        }
        result = verify_authorization_set(
            authorization_set,
            release_files=material,
            trust_anchor=_trust_anchor(),
            environment="test",
            now=NOW,
            expected_repository="cyranoaladin/RAG",
            accepted_reviewers=("abenrhouma",),
            release_scope_placement=placement,
            verified_profiles=(
                _profile_fact(),
                _profile_fact(
                    profile_id="profile-maths-seconde",
                    profile_fingerprint="5" * 64,
                    scope=second_scope,
                ),
            ),
            revocation_registry_raw=_revocations(),
            authority_required_content_sha256=(SHA_A, SHA_B),
        )
        assert result.earliest_review_submitted_at == NOW - timedelta(days=5)
        assert result.earliest_review_binding_verified_at == NOW - timedelta(days=3)
        assert result.earliest_review_binding_expires_at == NOW + timedelta(days=3)
        assert all(
            moment.tzinfo is not None
            for moment in (
                result.earliest_review_submitted_at,
                result.earliest_review_binding_verified_at,
                result.earliest_review_binding_expires_at,
            )
        )

    def test_member_validity_must_equal_the_individual_authorization(self) -> None:
        authorization_set, verified, placement, profiles = _verified_scope_inputs()
        changed_member = authorization_set.members[0].model_copy(
            update={"valid_from": NOW - timedelta(days=2)}
        )
        authorization_set = authorization_set.model_copy(
            update={
                "members": (changed_member,),
                "authorizations_effective_valid_from": changed_member.valid_from,
            }
        )
        with pytest.raises(AuthorizationSetError, match="valid_from"):
            _verify_authorization_set_scope_facts(
                authorization_set,
                verified_members=verified,
                release_scope_placement=placement,
                verified_profiles=profiles,
            )
