"""Composition canonique des autorisations de scope d'une release.

Ce module est un contrat pur : aucune E/S, aucun import d'un service et
aucune découverte implicite. Les appelants fournissent les faits de release
qu'ils ont vérifiés ; le contrat les compare sans les réinterpréter.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Iterable, Literal, Mapping, Sequence

from pydantic import (
    AwareDatetime,
    Field,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from nexus_contracts.document import StrictBaseModel
from nexus_contracts.authority_artifacts import (
    ScopeAuthorizationArtifactV2,
    canonical_authorization_path,
    git_blob_sha1,
    parse_scope_authorization_artifact,
)
from nexus_contracts.authorization_revocations import parse_revoked_authorization_ids
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.review_binding import (
    SignedScopeAuthorizationReviewBinding,
    TrustAnchor,
    parse_signed_review_binding,
    require_challenge_is_bound,
    require_matches_authorization,
    verify_review_binding,
)

AUTHORIZATION_SET_PROTOCOL_VERSION = "NEXUS-AUTHORIZATION-SET-V1"
RELEASE_SCOPE_PLACEMENT_PROTOCOL_VERSION = "NEXUS-RELEASE-SCOPE-PLACEMENT-V1"

_HEX64 = r"^[0-9a-f]{64}$"


class AuthorizationSetError(ValueError):
    """La composition globale ne prouve pas une autorité exacte."""


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def _canonical_moment(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("moments must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonical_scope(scope: ResourceScope) -> dict[str, Any]:
    document = scope.model_dump(mode="json")
    document["audience"] = sorted(document["audience"])
    return document


def scope_digest(scope: ResourceScope) -> str:
    """Digest du ``ResourceScope`` canonique, audience comprise comme set."""
    return sha256(_canonical_bytes(_canonical_scope(scope))).hexdigest()


def content_set_digest(values: Iterable[str]) -> str:
    """Digest historique : SHA lowercase triés, un par ligne, LF final."""
    return sha256("".join(f"{value}\n" for value in sorted(values)).encode()).hexdigest()


class AuthorizationSetMemberV1(StrictBaseModel):
    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    authorization_digest: StrictStr = Field(pattern=_HEX64)
    review_binding_digest: StrictStr = Field(pattern=_HEX64)
    scope: ResourceScope
    scope_digest: StrictStr = Field(pattern=_HEX64)
    allowed_content_sha256: tuple[StrictStr, ...] = Field(min_length=1)
    allowed_content_count: StrictInt = Field(gt=0)
    allowed_content_set_sha256: StrictStr = Field(pattern=_HEX64)
    valid_from: AwareDatetime
    valid_until: AwareDatetime

    @field_validator("authorization_id")
    @classmethod
    def _authorization_id_is_canonical(cls, value: str) -> str:
        try:
            canonical_authorization_path(value)
        except ValueError as exc:
            raise ValueError(f"authorization_id is not canonical: {exc}") from exc
        return value

    @field_validator("allowed_content_sha256")
    @classmethod
    def _allowed_content_is_canonical(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        if any(re.fullmatch(_HEX64, value) is None for value in values):
            raise ValueError(
                "allowed_content_sha256 entries must be 64 lowercase hex characters"
            )
        if len(values) != len(set(values)):
            raise ValueError("allowed_content_sha256 contains duplicates")
        if values != tuple(sorted(values)):
            raise ValueError("allowed_content_sha256 must be sorted")
        return values

    @model_validator(mode="after")
    def _derived_facts_are_exact(self) -> AuthorizationSetMemberV1:
        if self.allowed_content_count != len(self.allowed_content_sha256):
            raise ValueError("allowed_content_count does not match the content list")
        if self.allowed_content_set_sha256 != content_set_digest(
            self.allowed_content_sha256
        ):
            raise ValueError(
                "allowed_content_set_sha256 does not match the content list"
            )
        if self.scope_digest != scope_digest(self.scope):
            raise ValueError("scope_digest does not match the canonical scope")
        if self.valid_until <= self.valid_from:
            raise ValueError("valid_until must be strictly after valid_from")
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "allowed_content_count": self.allowed_content_count,
            "allowed_content_set_sha256": self.allowed_content_set_sha256,
            "allowed_content_sha256": list(self.allowed_content_sha256),
            "authorization_digest": self.authorization_digest,
            "authorization_id": self.authorization_id,
            "review_binding_digest": self.review_binding_digest,
            "scope": _canonical_scope(self.scope),
            "scope_digest": self.scope_digest,
            "valid_from": _canonical_moment(self.valid_from),
            "valid_until": _canonical_moment(self.valid_until),
        }

    @property
    def authorization_path(self) -> str:
        return canonical_authorization_path(self.authorization_id)

    @property
    def review_binding_path(self) -> str:
        return canonical_review_binding_path(self.authorization_id)


class ReleaseScopePlacementEntryV1(StrictBaseModel):
    content_sha256: StrictStr = Field(pattern=_HEX64)
    profile_id: StrictStr = Field(min_length=1)
    profile_version: StrictStr = Field(min_length=1)
    profile_fingerprint: StrictStr = Field(pattern=_HEX64)
    scope: ResourceScope

    def canonical_document(self) -> dict[str, Any]:
        return {
            "content_sha256": self.content_sha256,
            "profile_fingerprint": self.profile_fingerprint,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "scope": _canonical_scope(self.scope),
        }


class VerifiedProfileFactV1(StrictBaseModel):
    """Fait de profil déjà vérifié par l'adaptateur du service appelant."""

    profile_id: StrictStr = Field(min_length=1)
    profile_version: StrictStr = Field(min_length=1)
    profile_fingerprint: StrictStr = Field(pattern=_HEX64)
    scope: ResourceScope


class ReleaseScopePlacementV1(StrictBaseModel):
    """Projection pure, indépendante du set et de ses autorisations."""

    protocol_version: Literal["NEXUS-RELEASE-SCOPE-PLACEMENT-V1"]
    profile_manifest_digest: StrictStr = Field(pattern=_HEX64)
    placements: tuple[ReleaseScopePlacementEntryV1, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _contents_are_unique(self) -> ReleaseScopePlacementV1:
        contents = [item.content_sha256 for item in self.placements]
        if len(contents) != len(set(contents)):
            raise ValueError("release scope placement repeats content_sha256")
        return self

    @classmethod
    def build(
        cls,
        *,
        placements: Sequence[ReleaseScopePlacementEntryV1],
        profile_manifest_digest: str,
    ) -> ReleaseScopePlacementV1:
        try:
            return cls.model_validate(
                {
                    "protocol_version": RELEASE_SCOPE_PLACEMENT_PROTOCOL_VERSION,
                    "profile_manifest_digest": profile_manifest_digest,
                    "placements": tuple(
                        sorted(placements, key=lambda item: item.content_sha256)
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - frontière de contrat
            raise AuthorizationSetError(
                f"release scope placement is invalid: {exc}"
            ) from exc

    def canonical_bytes(self) -> bytes:
        """JSONL canonique : une en-tête puis une ligne par contenu, LF final."""
        header = {
            "profile_manifest_digest": self.profile_manifest_digest,
            "protocol_version": self.protocol_version,
        }
        documents = [
            header,
            *(
                item.canonical_document()
                for item in sorted(self.placements, key=lambda value: value.content_sha256)
            ),
        ]
        return "".join(
            json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for document in documents
        ).encode("utf-8")

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


class AuthorizationSetV1(StrictBaseModel):
    protocol_version: Literal["NEXUS-AUTHORIZATION-SET-V1"]
    members: tuple[AuthorizationSetMemberV1, ...] = Field(min_length=1)
    authorization_count: StrictInt = Field(gt=0)
    corpus_manifest_sha256: StrictStr = Field(pattern=_HEX64)
    profile_manifest_digest: StrictStr = Field(pattern=_HEX64)
    release_scope_placement_digest: StrictStr = Field(pattern=_HEX64)
    authority_required_count: StrictInt = Field(gt=0)
    authority_required_set_sha256: StrictStr = Field(pattern=_HEX64)
    union_content_count: StrictInt = Field(gt=0)
    union_content_sha256_digest: StrictStr = Field(pattern=_HEX64)
    authorizations_effective_valid_from: AwareDatetime
    authorizations_effective_valid_until: AwareDatetime

    @model_validator(mode="after")
    def _intrinsic_semantics_are_exact(self) -> AuthorizationSetV1:
        dimensions: tuple[tuple[str, list[str]], ...] = (
            ("authorization_id", [item.authorization_id for item in self.members]),
            (
                "authorization_digest",
                [item.authorization_digest for item in self.members],
            ),
            (
                "review_binding_digest",
                [item.review_binding_digest for item in self.members],
            ),
            ("scope", [scope_digest(item.scope) for item in self.members]),
        )
        for name, values in dimensions:
            if len(values) != len(set(values)):
                raise ValueError(f"members repeat {name}")

        if self.authorization_count != len(self.members):
            raise ValueError("authorization_count does not match members")
        effective_from = max(item.valid_from for item in self.members)
        effective_until = min(item.valid_until for item in self.members)
        if self.authorizations_effective_valid_from != effective_from:
            raise ValueError("authorizations_effective_valid_from does not match members")
        if self.authorizations_effective_valid_until != effective_until:
            raise ValueError("authorizations_effective_valid_until does not match members")

        owners: dict[str, str] = {}
        for member in self.members:
            for content in member.allowed_content_sha256:
                previous = owners.get(content)
                if previous is not None:
                    raise ValueError(
                        f"authorization overlap for content {content!r}: "
                        f"{previous!r} and {member.authorization_id!r}"
                    )
                owners[content] = member.authorization_id
        union = tuple(sorted(owners))
        union_digest = content_set_digest(union)
        if self.union_content_count != len(union):
            raise ValueError("union_content_count does not match member union")
        if self.union_content_sha256_digest != union_digest:
            raise ValueError(
                "union_content_sha256_digest does not match member union"
            )
        if self.authority_required_count != self.union_content_count:
            raise ValueError(
                "authority_required_count does not equal union_content_count"
            )
        if self.authority_required_set_sha256 != self.union_content_sha256_digest:
            raise ValueError(
                "authority_required_set_sha256 does not equal "
                "union_content_sha256_digest"
            )
        return self

    @classmethod
    def build(
        cls,
        *,
        members: Sequence[AuthorizationSetMemberV1],
        corpus_manifest_sha256: str,
        profile_manifest_digest: str,
        release_scope_placement_digest: str,
        authority_required_content_sha256: Sequence[str],
    ) -> AuthorizationSetV1:
        if not members:
            raise AuthorizationSetError("authorization set requires at least one member")
        ordered = tuple(sorted(members, key=lambda item: item.authorization_id))
        union = tuple(
            sorted(content for member in ordered for content in member.allowed_content_sha256)
        )
        required = tuple(sorted(authority_required_content_sha256))
        try:
            return cls.model_validate(
                {
                    "protocol_version": AUTHORIZATION_SET_PROTOCOL_VERSION,
                    "members": ordered,
                    "authorization_count": len(ordered),
                    "corpus_manifest_sha256": corpus_manifest_sha256,
                    "profile_manifest_digest": profile_manifest_digest,
                    "release_scope_placement_digest": release_scope_placement_digest,
                    "authority_required_count": len(required),
                    "authority_required_set_sha256": content_set_digest(required),
                    "union_content_count": len(union),
                    "union_content_sha256_digest": content_set_digest(union),
                    "authorizations_effective_valid_from": max(
                        item.valid_from for item in ordered
                    ),
                    "authorizations_effective_valid_until": min(
                        item.valid_until for item in ordered
                    ),
                }
            )
        except Exception as exc:  # noqa: BLE001 - frontière de contrat
            raise AuthorizationSetError(f"authorization set is invalid: {exc}") from exc

    def canonical_document(self) -> dict[str, Any]:
        return {
            "authorization_count": self.authorization_count,
            "authorizations_effective_valid_from": _canonical_moment(
                self.authorizations_effective_valid_from
            ),
            "authorizations_effective_valid_until": _canonical_moment(
                self.authorizations_effective_valid_until
            ),
            "authority_required_count": self.authority_required_count,
            "authority_required_set_sha256": self.authority_required_set_sha256,
            "corpus_manifest_sha256": self.corpus_manifest_sha256,
            "members": [
                member.canonical_document()
                for member in sorted(self.members, key=lambda item: item.authorization_id)
            ],
            "profile_manifest_digest": self.profile_manifest_digest,
            "protocol_version": self.protocol_version,
            "release_scope_placement_digest": self.release_scope_placement_digest,
            "union_content_count": self.union_content_count,
            "union_content_sha256_digest": self.union_content_sha256_digest,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


def parse_authorization_set(raw: bytes) -> AuthorizationSetV1:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorizationSetError(f"authorization set is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise AuthorizationSetError("authorization set must be a JSON object")
    if document.get("protocol_version") != AUTHORIZATION_SET_PROTOCOL_VERSION:
        raise AuthorizationSetError(
            "authorization set declares an unsupported protocol_version"
        )
    try:
        parsed = AuthorizationSetV1.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing stricte
        raise AuthorizationSetError(f"authorization set failed strict validation: {exc}") from exc
    if parsed.canonical_bytes() != raw:
        raise AuthorizationSetError("authorization set bytes are not in canonical form")
    return parsed


def parse_release_scope_placement(raw: bytes) -> ReleaseScopePlacementV1:
    """Parse strict du JSONL de projection, avec égalité octet à octet."""
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise AuthorizationSetError(
            "release scope placement bytes are not in canonical form"
        )
    try:
        text = raw[:-1].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AuthorizationSetError(
            f"release scope placement is not valid UTF-8: {exc}"
        ) from exc
    documents: list[Any] = []
    for line_number, line in enumerate(text.split("\n"), start=1):
        try:
            documents.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise AuthorizationSetError(
                f"release scope placement line {line_number} is not valid JSON: {exc}"
            ) from exc
    if not documents or not isinstance(documents[0], dict):
        raise AuthorizationSetError("release scope placement must start with a JSON header")
    header = documents[0]
    if set(header) != {"profile_manifest_digest", "protocol_version"}:
        raise AuthorizationSetError("release scope placement header has unexpected fields")
    if header.get("protocol_version") != RELEASE_SCOPE_PLACEMENT_PROTOCOL_VERSION:
        raise AuthorizationSetError(
            "release scope placement declares an unsupported protocol_version"
        )
    if any(not isinstance(document, dict) for document in documents[1:]):
        raise AuthorizationSetError("release scope placement rows must be JSON objects")
    try:
        placement = ReleaseScopePlacementV1.model_validate(
            {
                "protocol_version": header["protocol_version"],
                "profile_manifest_digest": header["profile_manifest_digest"],
                "placements": documents[1:],
            }
        )
    except Exception as exc:  # noqa: BLE001 - frontière de parsing stricte
        raise AuthorizationSetError(
            f"release scope placement failed strict validation: {exc}"
        ) from exc
    if placement.canonical_bytes() != raw:
        raise AuthorizationSetError(
            "release scope placement bytes are not in canonical form"
        )
    return placement


def canonical_review_binding_path(authorization_id: str) -> str:
    """Chemin du reçu dérivé du même ID canonique que l'autorisation."""
    canonical_authorization_path(authorization_id)
    return f"governance/review-bindings/{authorization_id}.json"


def _expected_material_paths(authorization_set: AuthorizationSetV1) -> frozenset[str]:
    return frozenset(
        path
        for member in authorization_set.members
        for path in (member.authorization_path, member.review_binding_path)
    )


def resolve_authorization_set_material(
    authorization_set: AuthorizationSetV1,
    *,
    governed_files: Mapping[str, bytes],
) -> dict[str, bytes]:
    """Résout seulement le bundle nommé par le set depuis une racine historique.

    Les fichiers historiques ne deviennent pas des membres de release par leur
    simple coexistence. Un chemin requis absent reste en revanche un refus.
    """
    expected = _expected_material_paths(authorization_set)
    missing = sorted(expected - governed_files.keys())
    if missing:
        raise AuthorizationSetError(f"missing release material: {missing!r}")
    return {path: governed_files[path] for path in sorted(expected)}


@dataclass(frozen=True)
class _ResolvedAuthorizationSetMemberV1:
    descriptor: AuthorizationSetMemberV1
    authorization: ScopeAuthorizationArtifactV2
    review_binding: SignedScopeAuthorizationReviewBinding


@dataclass(frozen=True)
class VerifiedAuthorizationSetV1:
    """Résultat du seul boundary qui exerce toutes les preuves du set."""

    authorization_set_bytes: bytes
    authorization_set_digest: str
    authorization_ids: tuple[str, ...]
    content_authorization_ids: tuple[tuple[str, str], ...]
    scope_authorization_ids: tuple[tuple[str, str], ...]
    authorizations_effective_valid_from: datetime
    authorizations_effective_valid_until: datetime
    earliest_review_submitted_at: datetime
    earliest_review_binding_verified_at: datetime
    earliest_review_binding_expires_at: datetime
    verified_at: datetime


def _verify_authorization_set_material(
    authorization_set: AuthorizationSetV1,
    *,
    release_files: Mapping[str, bytes],
    trust_anchor: TrustAnchor,
    environment: Literal["production", "test"],
    now: datetime,
    expected_repository: str,
    accepted_reviewers: tuple[str, ...] | None = None,
) -> dict[str, _ResolvedAuthorizationSetMemberV1]:
    """Vérifie le matériau *de release* exact, sans faire de découverte.

    Chaque binding est vérifié cryptographiquement avec l'ancre explicite,
    puis lié aux octets, au chemin, au dépôt, au reviewer et au challenge de
    l'autorisation exacte. Un SHA de fichier seul n'est jamais une preuve.
    """
    if environment == "production" and not accepted_reviewers:
        raise AuthorizationSetError(
            "production verification requires a non-empty accepted reviewers allowlist"
        )
    expected = _expected_material_paths(authorization_set)
    actual = frozenset(release_files)
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    if missing:
        raise AuthorizationSetError(f"missing release material: {missing!r}")
    if extra:
        raise AuthorizationSetError(f"extra release material: {extra!r}")

    verified: dict[str, _ResolvedAuthorizationSetMemberV1] = {}
    for member in authorization_set.members:
        authorization_raw = release_files[member.authorization_path]
        binding_raw = release_files[member.review_binding_path]
        actual_authorization_digest = sha256(authorization_raw).hexdigest()
        if actual_authorization_digest != member.authorization_digest:
            raise AuthorizationSetError(
                f"authorization_digest mismatch for {member.authorization_id!r}"
            )
        actual_binding_digest = sha256(binding_raw).hexdigest()
        if actual_binding_digest != member.review_binding_digest:
            raise AuthorizationSetError(
                f"review_binding_digest mismatch for {member.authorization_id!r}"
            )
        try:
            parsed_authorization = parse_scope_authorization_artifact(authorization_raw)
            parsed_binding = parse_signed_review_binding(binding_raw)
            verified_binding = verify_review_binding(
                binding_raw,
                trust_anchor=trust_anchor,
                environment=environment,
                now=now,
            )
            require_matches_authorization(
                verified_binding,
                authorization_id=member.authorization_id,
                authorization_bytes=authorization_raw,
                authorization_git_blob_sha1=git_blob_sha1(authorization_raw),
                expected_repository=expected_repository,
                accepted_reviewers=accepted_reviewers,
            )
            require_challenge_is_bound(verified_binding)
        except ValueError as exc:
            raise AuthorizationSetError(
                f"member material is invalid for {member.authorization_id!r}: {exc}"
            ) from exc
        if not isinstance(parsed_authorization, ScopeAuthorizationArtifactV2):
            raise AuthorizationSetError(
                f"authorization {member.authorization_id!r} must use LOT41A-V2"
            )
        if parsed_authorization.authorization_id != member.authorization_id:
            raise AuthorizationSetError(
                f"authorization_id mismatch for {member.authorization_id!r}"
            )
        verified[member.authorization_id] = _ResolvedAuthorizationSetMemberV1(
            descriptor=member,
            authorization=parsed_authorization,
            review_binding=parsed_binding,
        )
    return verified


def _verify_authorization_set_scope_facts(
    authorization_set: AuthorizationSetV1,
    *,
    verified_members: Mapping[str, _ResolvedAuthorizationSetMemberV1],
    release_scope_placement: ReleaseScopePlacementV1,
    verified_profiles: Sequence[VerifiedProfileFactV1],
) -> None:
    """Compare les quatre branches de la preuve contenu → scope.

    ``verified_profiles`` est volontairement une suite de faits purs : le
    package partagé ne lit et n'importe aucun registre de service.
    """
    if release_scope_placement.digest() != authorization_set.release_scope_placement_digest:
        raise AuthorizationSetError("release scope placement digest mismatch")
    if (
        release_scope_placement.profile_manifest_digest
        != authorization_set.profile_manifest_digest
    ):
        raise AuthorizationSetError("profile manifest digest mismatch")

    expected_member_ids = {member.authorization_id for member in authorization_set.members}
    if set(verified_members) != expected_member_ids:
        raise AuthorizationSetError("verified member identities do not match the set")

    placement_by_content = {
        item.content_sha256: item for item in release_scope_placement.placements
    }
    set_contents = {
        content
        for member in authorization_set.members
        for content in member.allowed_content_sha256
    }
    if set(placement_by_content) != set_contents:
        raise AuthorizationSetError("placement content mapping does not match the set")

    profiles_by_identity: dict[tuple[str, str], VerifiedProfileFactV1] = {}
    for profile_fact in verified_profiles:
        identity = (profile_fact.profile_id, profile_fact.profile_version)
        if identity in profiles_by_identity:
            raise AuthorizationSetError(f"verified profile identity is duplicated: {identity!r}")
        profiles_by_identity[identity] = profile_fact

    for member in authorization_set.members:
        resolved = verified_members[member.authorization_id]
        authorization = resolved.authorization
        if member.scope_digest != scope_digest(member.scope):
            raise AuthorizationSetError(
                f"scope_digest mismatch for {member.authorization_id!r}"
            )
        if scope_digest(authorization.scope) != scope_digest(member.scope):
            raise AuthorizationSetError(
                f"authorization scope differs from set member {member.authorization_id!r}"
            )
        if authorization.allowed_content_sha256 != member.allowed_content_sha256:
            raise AuthorizationSetError(
                f"authorization content differs from set member {member.authorization_id!r}"
            )
        if authorization.valid_from != member.valid_from:
            raise AuthorizationSetError(
                f"authorization valid_from differs from set member "
                f"{member.authorization_id!r}"
            )
        if authorization.valid_until != member.valid_until:
            raise AuthorizationSetError(
                f"authorization valid_until differs from set member "
                f"{member.authorization_id!r}"
            )
        if authorization.manifest_digest != authorization_set.profile_manifest_digest:
            raise AuthorizationSetError(
                f"profile manifest digest mismatch for {member.authorization_id!r}"
            )

        for content in member.allowed_content_sha256:
            placement = placement_by_content[content]
            if placement.profile_id != authorization.profile_id:
                raise AuthorizationSetError(f"profile_id mismatch for content {content!r}")
            if placement.profile_version != authorization.profile_version:
                raise AuthorizationSetError(
                    f"profile_version mismatch for content {content!r}"
                )
            if placement.profile_fingerprint != authorization.profile_fingerprint:
                raise AuthorizationSetError(
                    f"profile_fingerprint mismatch for content {content!r}"
                )
            if scope_digest(placement.scope) != scope_digest(authorization.scope):
                raise AuthorizationSetError(f"scope mismatch for content {content!r}")

        profile_identity = (authorization.profile_id, authorization.profile_version)
        selected_profile = profiles_by_identity.get(profile_identity)
        if selected_profile is None:
            raise AuthorizationSetError(
                f"verified profile is missing for {profile_identity!r}"
            )
        if selected_profile.profile_fingerprint != authorization.profile_fingerprint:
            raise AuthorizationSetError(
                f"verified profile_fingerprint mismatch for {member.authorization_id!r}"
            )
        if scope_digest(selected_profile.scope) != scope_digest(authorization.scope):
            raise AuthorizationSetError(
                f"verified profile scope mismatch for {member.authorization_id!r}"
            )


def _verify_authorization_set_invariants(
    authorization_set: AuthorizationSetV1,
    *,
    revocation_registry_raw: bytes,
    now: datetime,
    authority_required_content_sha256: Sequence[str],
) -> tuple[datetime, datetime]:
    """Vérifie révocation, temps, anti-overlap et union exacte.

    La fenêtre est demi-ouverte pour chaque membre :
    ``valid_from <= now < valid_until``.
    """
    if now.tzinfo is None:
        raise AuthorizationSetError("now must be timezone-aware")
    try:
        revoked = parse_revoked_authorization_ids(revocation_registry_raw)
    except ValueError as exc:
        raise AuthorizationSetError(str(exc)) from exc

    if authorization_set.authorization_count != len(authorization_set.members):
        raise AuthorizationSetError("authorization_count does not match members")

    owners: dict[str, str] = {}
    valid_froms: list[datetime] = []
    valid_untils: list[datetime] = []
    for member in authorization_set.members:
        if member.authorization_id in revoked:
            raise AuthorizationSetError(
                f"authorization {member.authorization_id!r} is revoked"
            )
        if member.valid_until <= member.valid_from:
            raise AuthorizationSetError(
                f"invalid validity window for {member.authorization_id!r}"
            )
        if now < member.valid_from:
            raise AuthorizationSetError(
                f"authorization {member.authorization_id!r} is not valid yet"
            )
        if now >= member.valid_until:
            raise AuthorizationSetError(
                f"authorization {member.authorization_id!r} is expired"
            )
        valid_froms.append(member.valid_from)
        valid_untils.append(member.valid_until)

        contents = member.allowed_content_sha256
        if len(contents) != len(set(contents)):
            raise AuthorizationSetError(
                f"duplicate content inside authorization {member.authorization_id!r}"
            )
        if tuple(sorted(contents)) != contents:
            raise AuthorizationSetError(
                f"allowed content is not canonical for {member.authorization_id!r}"
            )
        if any(re.fullmatch(_HEX64, content) is None for content in contents):
            raise AuthorizationSetError(
                f"invalid content SHA for {member.authorization_id!r}"
            )
        if member.allowed_content_count != len(contents):
            raise AuthorizationSetError(
                f"allowed_content_count mismatch for {member.authorization_id!r}"
            )
        if member.allowed_content_set_sha256 != content_set_digest(contents):
            raise AuthorizationSetError(
                f"allowed_content_set_sha256 mismatch for {member.authorization_id!r}"
            )
        for content in contents:
            previous = owners.get(content)
            if previous is not None:
                raise AuthorizationSetError(
                    f"authorization overlap for content {content!r}: "
                    f"{previous!r} and {member.authorization_id!r}"
                )
            owners[content] = member.authorization_id

    required = tuple(authority_required_content_sha256)
    if len(required) != len(set(required)):
        raise AuthorizationSetError("authority-required set repeats content")
    if any(re.fullmatch(_HEX64, content) is None for content in required):
        raise AuthorizationSetError("authority-required set contains an invalid SHA")
    required_set = set(required)
    union_set = set(owners)
    gap = sorted(required_set - union_set)
    extra = sorted(union_set - required_set)
    if gap:
        raise AuthorizationSetError(f"authorization union has a gap: {gap!r}")
    if extra:
        raise AuthorizationSetError(f"authorization union has extra content: {extra!r}")

    expected_union = tuple(sorted(union_set))
    expected_required = tuple(sorted(required_set))
    if authorization_set.authority_required_count != len(expected_required):
        raise AuthorizationSetError("authority_required_count mismatch")
    if (
        authorization_set.authority_required_set_sha256
        != content_set_digest(expected_required)
    ):
        raise AuthorizationSetError("authority_required_set_sha256 mismatch")
    if authorization_set.union_content_count != len(expected_union):
        raise AuthorizationSetError("union_content_count mismatch")
    if (
        authorization_set.union_content_sha256_digest
        != content_set_digest(expected_union)
    ):
        raise AuthorizationSetError("union_content_sha256_digest mismatch")

    effective_from = max(valid_froms)
    effective_until = min(valid_untils)
    if authorization_set.authorizations_effective_valid_from != effective_from:
        raise AuthorizationSetError("authorizations_effective_valid_from mismatch")
    if authorization_set.authorizations_effective_valid_until != effective_until:
        raise AuthorizationSetError("authorizations_effective_valid_until mismatch")
    return effective_from, effective_until


def verify_authorization_set(
    authorization_set: AuthorizationSetV1,
    *,
    release_files: Mapping[str, bytes],
    trust_anchor: TrustAnchor,
    environment: Literal["production", "test"],
    now: datetime,
    expected_repository: str,
    accepted_reviewers: tuple[str, ...] | None,
    release_scope_placement: ReleaseScopePlacementV1,
    verified_profiles: Sequence[VerifiedProfileFactV1],
    revocation_registry_raw: bytes,
    authority_required_content_sha256: Sequence[str],
) -> VerifiedAuthorizationSetV1:
    """Boundary fail-closed : toutes les preuves, ou aucun résultat vérifié."""
    validated_set = parse_authorization_set(authorization_set.canonical_bytes())
    resolved = _verify_authorization_set_material(
        validated_set,
        release_files=release_files,
        trust_anchor=trust_anchor,
        environment=environment,
        now=now,
        expected_repository=expected_repository,
        accepted_reviewers=accepted_reviewers,
    )
    for member in validated_set.members:
        binding = resolved[member.authorization_id].review_binding.binding
        if binding.submitted_at > binding.verified_at:
            raise AuthorizationSetError(
                f"review binding {member.authorization_id!r} has submitted_at "
                "after verified_at"
            )
        if binding.verified_at > now:
            raise AuthorizationSetError(
                f"review binding {member.authorization_id!r} has verified_at "
                "in the future"
            )
    _verify_authorization_set_scope_facts(
        validated_set,
        verified_members=resolved,
        release_scope_placement=release_scope_placement,
        verified_profiles=verified_profiles,
    )
    effective_from, effective_until = _verify_authorization_set_invariants(
        validated_set,
        revocation_registry_raw=revocation_registry_raw,
        now=now,
        authority_required_content_sha256=authority_required_content_sha256,
    )
    content_authorization_ids = tuple(
        sorted(
            (content, member.authorization_id)
            for member in validated_set.members
            for content in member.allowed_content_sha256
        )
    )
    scope_authorization_ids = tuple(
        sorted(
            (member.scope_digest, member.authorization_id)
            for member in validated_set.members
        )
    )
    verified_bindings = tuple(
        resolved[member.authorization_id].review_binding.binding
        for member in validated_set.members
    )
    authorization_set_bytes = validated_set.canonical_bytes()
    return VerifiedAuthorizationSetV1(
        authorization_set_bytes=authorization_set_bytes,
        authorization_set_digest=sha256(authorization_set_bytes).hexdigest(),
        authorization_ids=tuple(
            member.authorization_id for member in validated_set.members
        ),
        content_authorization_ids=content_authorization_ids,
        scope_authorization_ids=scope_authorization_ids,
        authorizations_effective_valid_from=effective_from,
        authorizations_effective_valid_until=effective_until,
        earliest_review_submitted_at=min(
            binding.submitted_at for binding in verified_bindings
        ),
        earliest_review_binding_verified_at=min(
            binding.verified_at for binding in verified_bindings
        ),
        earliest_review_binding_expires_at=min(
            binding.expires_at for binding in verified_bindings
        ),
        verified_at=now,
    )


__all__ = [
    "AUTHORIZATION_SET_PROTOCOL_VERSION",
    "RELEASE_SCOPE_PLACEMENT_PROTOCOL_VERSION",
    "AuthorizationSetError",
    "AuthorizationSetMemberV1",
    "AuthorizationSetV1",
    "ReleaseScopePlacementEntryV1",
    "ReleaseScopePlacementV1",
    "VerifiedProfileFactV1",
    "VerifiedAuthorizationSetV1",
    "canonical_review_binding_path",
    "content_set_digest",
    "parse_authorization_set",
    "parse_release_scope_placement",
    "resolve_authorization_set_material",
    "scope_digest",
    "verify_authorization_set",
]
