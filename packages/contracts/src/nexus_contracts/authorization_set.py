"""Ensemble gouverné de N autorisations de scope — `NEXUS-AUTHORIZATION-SET-V1`
(ADR-0044).

**Le problème résolu ici.** Le set authority-required réel d'une release
couvre plusieurs `ResourceScope` distincts (au moins 22-23 couples réels
niveau/matière pour la release `prerentree_2026_2027`). Chaque
``ScopeAuthorizationArtifactV2`` reste volontairement mono-scope — sa
revue humaine porte sur un `ResourceScope` précis, jamais élargi. Mais
rien, avant ce module, ne permettait de prouver qu'un ensemble
d'autorisations mono-scope, prises ensemble, couvre *exactement* le set
authority-required complet, sans recouvrement ni omission, sans jamais
laisser une seule revue humaine approuver plusieurs scopes à la fois.

**Ce que ce module ne fait pas.** Il ne vérifie ni révocation ni
expiration — ces deux contrôles restent **par autorisation**, jamais une
fois pour l'ensemble (ADR-0044 §4.4) : les effectuer ici, sur des
autorisations qui peuvent être chargées loin dans le temps de leur
vérification effective, masquerait une autorisation individuellement
invalide derrière un ensemble globalement construit. Ce module ne fait
que composer, canonicaliser et prouver la cohérence interne (tri,
absence de recouvrement, exactitude de l'union) de N autorisations déjà
individuellement valides au moment de la construction — la vérification
en direct (révocation, expiration, review binding) reste dans
l'orchestration appelante, comme pour chaque autre artefact d'autorité de
ce paquet (ADR-0001).

Même discipline de canonicalisation que le reste de ce paquet : clés
triées, indentation fixe, UTF-8, saut de ligne final, ``extra="forbid"``.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from hashlib import sha256
from typing import Any, Literal

from pydantic import Field, StrictInt, StrictStr, field_validator, model_validator

from nexus_contracts.authority_artifacts import ScopeAuthorizationArtifactV2
from nexus_contracts.document import StrictBaseModel
from nexus_contracts.ingestion import ResourceScope
from nexus_contracts.review_binding import (
    ReviewBindingError,
    SignedScopeAuthorizationReviewBinding,
    require_matches_authorization,
)

#: Version de protocole. Absente ou inconnue, l'ensemble n'est pas parsé.
AUTHORIZATION_SET_PROTOCOL_VERSION = "NEXUS-AUTHORIZATION-SET-V1"

#: Racine canonique des ensembles, versionnée dans Git. Adressée par
#: digest (comme les revues de publication LOT42) : un ensemble modifié ne
#: peut jamais réutiliser le chemin d'un ensemble déjà construit.
AUTHORIZATION_SETS_DIR = "governance/authorization-sets"

_HEX64 = r"^[0-9a-f]{64}$"
_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_CANONICAL_INDENT = 2


class AuthorizationSetError(ValueError):
    """L'ensemble d'autorisations ne prouve pas ce qu'il prétend — refus
    explicite, jamais une correction silencieuse."""


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, sort_keys=True, indent=_CANONICAL_INDENT, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _canonical_scope(scope: ResourceScope) -> dict[str, Any]:
    """Même forme que ``authority_artifacts._canonical_scope`` — dupliquée
    ici par le choix de conception déjà établi dans ce paquet (chaque
    module de contrat porte sa propre discipline canonique, jamais un
    import d'un helper privé d'un autre module)."""
    return {
        "audience": sorted(a.value for a in scope.audience),
        "candidat": scope.candidat.value,
        "collection": scope.collection,
        "matiere": scope.matiere,
        "niveau": scope.niveau.value,
        "programme_version": scope.programme_version,
        "school_year": scope.school_year,
        "tenant": scope.tenant,
        "visibility": scope.visibility,
        "voie": scope.voie.value,
    }


def _scope_digest(scope: ResourceScope) -> str:
    return sha256(_canonical_bytes(_canonical_scope(scope))).hexdigest()


def _union_content_sha256(members: Sequence["AuthorizationSetMemberV1"]) -> tuple[str, ...]:
    seen: set[str] = set()
    for member in members:
        seen.update(member.allowed_content_sha256)
    return tuple(sorted(seen))


def _union_digest(content: Sequence[str]) -> str:
    return sha256(_canonical_bytes({"content_sha256": list(content)})).hexdigest()


class AuthorizationSetMemberV1(StrictBaseModel):
    """Une autorisation, telle qu'elle entre dans l'ensemble.

    Chaque champ est un digest **recalculé depuis l'objet réel** au moment
    de la construction (voir ``build_authorization_set``), jamais une
    valeur affirmée par un appelant — un membre falsifié qui prétendrait
    couvrir des octets qu'il ne couvre pas serait détecté à la
    construction, pas seulement à la vérification.
    """

    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    #: ``sha256`` des octets canoniques du fichier
    #: ``ScopeAuthorizationArtifactV2`` de cette autorisation — même
    #: définition que ``ScopeAuthorizationArtifactV2.digest()``.
    authorization_digest: StrictStr = Field(pattern=_HEX64)
    #: ``sha256`` des octets canoniques de l'enveloppe signée
    #: ``SignedScopeAuthorizationReviewBinding`` de cette autorisation —
    #: même définition que celle déjà utilisée par le signer de readiness
    #: (``sign_production_readiness_manifest_cli.py:643``,
    #: ``sha256(review_binding_raw)`` sur les octets bruts du fichier).
    review_binding_digest: StrictStr = Field(pattern=_HEX64)
    #: ``sha256`` du JSON canonique des dix dimensions ``ResourceScope`` de
    #: cette autorisation — jamais recalculé depuis un chemin, toujours
    #: depuis l'objet ``ResourceScope`` réel de l'autorisation.
    scope_digest: StrictStr = Field(pattern=_HEX64)
    #: Le manifeste scellé que CETTE autorisation déclare — vérifié
    #: individuellement contre ``AuthorizationSetV1.manifest_digest``
    #: (ADR-0044 §4.4), jamais supposé identique.
    manifest_digest: StrictStr = Field(pattern=_HEX64)
    #: Copie exacte de ``ScopeAuthorizationArtifactV2.allowed_content_sha256``
    #: — jamais recalculée depuis autre chose que l'autorisation elle-même.
    allowed_content_sha256: tuple[StrictStr, ...] = Field(min_length=1)

    @field_validator("authorization_id")
    @classmethod
    def _identifier_is_canonical(cls, value: str) -> str:
        if not _IDENTIFIER_PATTERN.fullmatch(value):
            raise ValueError(
                f"authorization_id {value!r} must match {_IDENTIFIER_PATTERN.pattern}"
            )
        return value

    @field_validator("allowed_content_sha256")
    @classmethod
    def _content_allowlist_is_canonical(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            if not re.fullmatch(_HEX64[1:-1], value):
                raise ValueError(
                    "allowed_content_sha256 entries must be exactly 64 lowercase "
                    "hexadecimal characters"
                )
        if len(set(values)) != len(values):
            raise ValueError("allowed_content_sha256 must not contain duplicates")
        expected = sorted(values)
        if list(values) != expected:
            raise ValueError(
                "allowed_content_sha256 must be committed sorted; "
                f"expected {expected!r}, got {list(values)!r}"
            )
        return values

    def canonical_document(self) -> dict[str, Any]:
        return {
            "allowed_content_sha256": list(self.allowed_content_sha256),
            "authorization_digest": self.authorization_digest,
            "authorization_id": self.authorization_id,
            "manifest_digest": self.manifest_digest,
            "review_binding_digest": self.review_binding_digest,
            "scope_digest": self.scope_digest,
        }


class AuthorizationSetV1(StrictBaseModel):
    """L'ensemble canonique de N autorisations qui, ensemble, couvrent un
    set authority-required.

    ``authorization_set_digest``, ``union_content_sha256_digest`` et
    ``union_content_count`` sont tous trois **recalculés et confrontés**
    aux membres réels par un validateur — jamais des champs de confiance
    affirmés indépendamment (même discipline que ``H2CoverageEvidenceV1``
    pour ``coverage_complete``, ADR-0042 round 2).
    """

    protocol_version: Literal["NEXUS-AUTHORIZATION-SET-V1"]
    #: Attendu identique sur CHAQUE membre — vérifié ci-dessous, jamais
    #: supposé (ADR-0044 §4.4).
    manifest_digest: StrictStr = Field(pattern=_HEX64)
    members: tuple[AuthorizationSetMemberV1, ...] = Field(min_length=1)
    authorization_count: StrictInt = Field(ge=1)
    authorization_set_digest: StrictStr = Field(pattern=_HEX64)
    union_content_sha256_digest: StrictStr = Field(pattern=_HEX64)
    union_content_count: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def _members_are_committed_sorted_by_id(self) -> "AuthorizationSetV1":
        """Anti-permutation (ADR-0044 §4.1) : les membres sont exigés déjà
        triés par ``authorization_id`` dans leur forme committée — jamais
        réordonnés en silence, exactement la même discipline que
        ``ScopeAuthorizationArtifactV2.allowed_content_sha256``. Deux
        ingénieurs construisant le même ensemble dans un ordre d'entrée
        différent doivent explicitement trier avant de committer ; le
        digest, lui, est alors garanti identique."""
        ids = [member.authorization_id for member in self.members]
        if len(set(ids)) != len(ids):
            raise ValueError(
                f"members must not contain a duplicate authorization_id, got {ids!r}"
            )
        if ids != sorted(ids):
            raise ValueError(
                "members must be committed sorted by authorization_id; "
                f"expected order {sorted(ids)!r}, got {ids!r}"
            )
        return self

    @model_validator(mode="after")
    def _no_content_overlap_between_members(self) -> "AuthorizationSetV1":
        """Anti-overlap (ADR-0044 §4.2) : aucun ``content_sha256`` ne peut
        être revendiqué par deux autorisations à la fois — sauf
        multiplicité explicitement autorisée par un futur protocole, non
        prévue par ce V1."""
        owners: dict[str, str] = {}
        collisions: dict[str, list[str]] = {}
        for member in self.members:
            for content_sha256 in member.allowed_content_sha256:
                if content_sha256 in owners and owners[content_sha256] != member.authorization_id:
                    collisions.setdefault(content_sha256, [owners[content_sha256]]).append(
                        member.authorization_id
                    )
                else:
                    owners[content_sha256] = member.authorization_id
        if collisions:
            details = ", ".join(
                f"{content!r} claimed by {sorted(set(ids))!r}"
                for content, ids in sorted(collisions.items())
            )
            raise ValueError(
                f"authorization set members overlap on content_sha256: {details} — "
                "each content is authorized by exactly one member, never a "
                "silently-resolved multiplicity"
            )
        return self

    @model_validator(mode="after")
    def _every_member_manifest_matches_the_set(self) -> "AuthorizationSetV1":
        """Vérification stricte par membre (ADR-0044 §4.4) : une
        autorisation construite contre un ancien manifeste ne peut pas se
        cacher dans un ensemble construit contre le manifeste actuel."""
        disagreeing = [
            member.authorization_id
            for member in self.members
            if member.manifest_digest != self.manifest_digest
        ]
        if disagreeing:
            raise ValueError(
                f"member(s) {sorted(disagreeing)!r} declare a manifest_digest "
                f"different from the set's own ({self.manifest_digest}) — an "
                "authorization built against a stale manifest can never hide "
                "inside a set built against the current one"
            )
        return self

    @model_validator(mode="after")
    def _authorization_count_matches_members(self) -> "AuthorizationSetV1":
        if self.authorization_count != len(self.members):
            raise ValueError(
                f"authorization_count={self.authorization_count} does not match "
                f"the real member count ({len(self.members)})"
            )
        return self

    @model_validator(mode="after")
    def _union_fields_are_recomputed_and_match(self) -> "AuthorizationSetV1":
        """Jamais une valeur de confiance affirmée : ``union_content_sha256_digest``
        et ``union_content_count`` sont recalculés depuis les membres réels
        et confrontés, exactement comme ``H2CoverageEvidenceV1`` recalcule
        la cohérence de ``h2_coverage_gate_pass`` plutôt que de faire
        confiance à ``coverage_complete`` seul."""
        union = _union_content_sha256(self.members)
        expected_count = len(union)
        expected_digest = _union_digest(union)
        if self.union_content_count != expected_count:
            raise ValueError(
                f"union_content_count={self.union_content_count} does not match "
                f"the real union of member allowlists ({expected_count})"
            )
        if self.union_content_sha256_digest != expected_digest:
            raise ValueError(
                "union_content_sha256_digest does not match the digest recomputed "
                "from the real union of member allowlists "
                f"(declared={self.union_content_sha256_digest}, "
                f"recomputed={expected_digest})"
            )
        return self

    @model_validator(mode="after")
    def _set_digest_is_recomputed_and_matches(self) -> "AuthorizationSetV1":
        expected = sha256(self._members_canonical_bytes()).hexdigest()
        if self.authorization_set_digest != expected:
            raise ValueError(
                "authorization_set_digest does not match the digest recomputed "
                f"from the canonical members (declared={self.authorization_set_digest}, "
                f"recomputed={expected})"
            )
        return self

    def _members_canonical_bytes(self) -> bytes:
        """Forme canonique sur laquelle ``authorization_set_digest`` est
        calculé : la seule liste des membres, triés par construction
        (``_members_are_committed_sorted_by_id``), jamais le document
        complet — ``manifest_digest``/``union_*`` sont eux-mêmes dérivés
        des membres et n'ajoutent aucune information indépendante au
        digest d'identité de l'ensemble."""
        return _canonical_bytes(
            {"members": [member.canonical_document() for member in self.members]}
        )

    def canonical_document(self) -> dict[str, Any]:
        return {
            "authorization_count": self.authorization_count,
            "authorization_set_digest": self.authorization_set_digest,
            "manifest_digest": self.manifest_digest,
            "members": [member.canonical_document() for member in self.members],
            "protocol_version": self.protocol_version,
            "union_content_count": self.union_content_count,
            "union_content_sha256_digest": self.union_content_sha256_digest,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()

    def canonical_path(self) -> str:
        return canonical_authorization_set_path(self.authorization_set_digest)


def canonical_authorization_set_path(authorization_set_digest: str) -> str:
    """Chemin Git canonique, adressé par digest — comme les revues de
    publication LOT42 (``canonical_publication_review_path``), un ensemble
    modifié ne peut jamais réutiliser le chemin d'un ensemble déjà
    construit."""
    if not re.fullmatch(_HEX64[1:-1], authorization_set_digest):
        raise ValueError(
            f"authorization_set_digest {authorization_set_digest!r} must be 64 "
            "lowercase hexadecimal characters"
        )
    return f"{AUTHORIZATION_SETS_DIR}/{authorization_set_digest}.json"


def build_authorization_set(
    authorizations: Sequence[ScopeAuthorizationArtifactV2],
    review_bindings: Mapping[str, SignedScopeAuthorizationReviewBinding],
    *,
    manifest_digest: str,
    expected_repository: str,
    accepted_reviewers: tuple[str, ...] | None = None,
) -> AuthorizationSetV1:
    """Construit l'ensemble canonique depuis les objets réels.

    Vérifie, **individuellement pour chaque autorisation** (jamais une
    fois pour l'ensemble, ADR-0044 §4.4) : que son propre reçu de revue
    existe, que sa signature est structurellement cohérente avec elle
    (``require_matches_authorization``), et recalcule chaque digest de
    membre depuis les octets canoniques réels plutôt que d'accepter une
    valeur affirmée. Ne vérifie ni révocation ni expiration — voir la
    note de portée en tête de module ; c'est à l'appelant de les avoir
    déjà vérifiées (ou de les vérifier ensuite, par membre) contre l'état
    en direct."""
    if not authorizations:
        raise AuthorizationSetError(
            "build_authorization_set requires at least one authorization"
        )
    ids = [authorization.authorization_id for authorization in authorizations]
    if len(set(ids)) != len(ids):
        raise AuthorizationSetError(
            f"authorizations must not contain a duplicate authorization_id, got {ids!r}"
        )
    missing_bindings = sorted(set(ids) - set(review_bindings))
    if missing_bindings:
        raise AuthorizationSetError(
            f"no review binding was provided for authorization_id(s) {missing_bindings!r} "
            "— an authorization set member always names its own individually "
            "verified review binding, never a shared or missing one"
        )

    members: list[AuthorizationSetMemberV1] = []
    for authorization in sorted(authorizations, key=lambda item: item.authorization_id):
        if authorization.manifest_digest != manifest_digest:
            raise AuthorizationSetError(
                f"authorization {authorization.authorization_id!r} declares "
                f"manifest_digest {authorization.manifest_digest!r}, expected "
                f"{manifest_digest!r} — an authorization built against a stale "
                "manifest is refused before it ever reaches the set"
            )
        signed_binding = review_bindings[authorization.authorization_id]
        authorization_bytes = authorization.canonical_bytes()
        try:
            require_matches_authorization(
                signed_binding.binding,
                authorization_id=authorization.authorization_id,
                authorization_bytes=authorization_bytes,
                authorization_git_blob_sha1=_git_blob_sha1(authorization_bytes),
                expected_repository=expected_repository,
                accepted_reviewers=accepted_reviewers,
            )
        except ReviewBindingError as exc:
            raise AuthorizationSetError(
                f"review binding for authorization {authorization.authorization_id!r} "
                f"does not match it: {exc}"
            ) from exc

        members.append(
            AuthorizationSetMemberV1(
                authorization_id=authorization.authorization_id,
                authorization_digest=authorization.digest(),
                review_binding_digest=sha256(signed_binding.canonical_bytes()).hexdigest(),
                scope_digest=_scope_digest(authorization.scope),
                manifest_digest=authorization.manifest_digest,
                allowed_content_sha256=authorization.allowed_content_sha256,
            )
        )

    union = _union_content_sha256(members)
    members_bytes = _canonical_bytes({"members": [m.canonical_document() for m in members]})
    return AuthorizationSetV1(
        protocol_version="NEXUS-AUTHORIZATION-SET-V1",
        manifest_digest=manifest_digest,
        members=tuple(members),
        authorization_count=len(members),
        authorization_set_digest=sha256(members_bytes).hexdigest(),
        union_content_sha256_digest=_union_digest(union),
        union_content_count=len(union),
    )


def _git_blob_sha1(raw: bytes) -> str:
    from hashlib import sha1

    header = f"blob {len(raw)}\0".encode()
    return sha1(header + raw, usedforsecurity=False).hexdigest()  # noqa: S324


def parse_authorization_set(raw: bytes) -> AuthorizationSetV1:
    """Parse strict + exigence de canonicité **octet à octet** — même
    discipline que ``authority_artifacts.parse_scope_authorization_artifact``."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise AuthorizationSetError(f"authorization set bytes are not valid UTF-8: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise AuthorizationSetError(f"authorization set bytes are not valid JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise AuthorizationSetError("authorization set must be a JSON object")
    if document.get("protocol_version") != AUTHORIZATION_SET_PROTOCOL_VERSION:
        raise AuthorizationSetError(
            f"authorization set protocol_version is not {AUTHORIZATION_SET_PROTOCOL_VERSION!r}"
        )
    try:
        parsed = AuthorizationSetV1.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing, jamais silencieuse
        raise AuthorizationSetError(f"authorization set failed strict validation: {exc}") from exc
    reserialized = parsed.canonical_bytes()
    if reserialized != raw:
        raise AuthorizationSetError(
            "authorization set bytes are not in canonical form — the reviewed "
            "bytes and their canonical re-serialization differ. Commit the "
            "canonical form."
        )
    return parsed


__all__ = [
    "AUTHORIZATION_SETS_DIR",
    "AUTHORIZATION_SET_PROTOCOL_VERSION",
    "AuthorizationSetError",
    "AuthorizationSetMemberV1",
    "AuthorizationSetV1",
    "build_authorization_set",
    "canonical_authorization_set_path",
    "parse_authorization_set",
]
