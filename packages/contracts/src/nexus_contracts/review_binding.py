"""Liaison de revue scellée d'une autorisation de scope (ADR-0035).

**Le problème résolu ici.** Un artefact ``ScopeAuthorizationArtifactV2``,
même parfaitement canonique, ne porte aucune trace de sa revue. Un
vérificateur hors ligne pouvait donc valider intégralement sa structure et
sa sémantique — protocole, décision, scope, allowlist, fenêtre de validité,
digest — sur un fichier fabriqué localement que personne n'avait jamais
relu. Le gate final devenait vert sans qu'aucune autorité humaine ne soit
démontrée.

Ce module transporte, hors ligne et de façon infalsifiable, le résultat
d'une vérification en ligne déjà effectuée par le vérificateur canonique
d'ADR-0025 :

    review GitHub vivante
      -> vérificateur en ligne (ADR-0025, plan de données)
      -> reçu canonique signé Ed25519  <-- ce module
      -> vérificateur hors ligne (plan de contrôle pédagogique)

**Pourquoi une signature asymétrique.** ``profile_auth`` signe en HMAC des
jetons de profil élève : un secret partagé. Ici le vérificateur et le
producteur sont deux acteurs distincts ; un secret partagé permettrait au
vérificateur de forger exactement ce qu'il vérifie. Seule la clé publique
traverse la frontière.

**Aucune primitive artisanale.** La canonicalisation est celle
d'``authority_artifacts`` (JSON trié, séparateurs compacts, UTF-8) ; la
signature est Ed25519 de ``cryptography``. Ce module n'invente aucun
mécanisme cryptographique.

Ce module ne fait **aucune** E/S réseau et ne lit aucun fichier : il reçoit
des octets et rend des verdicts.
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import AwareDatetime, Field, StrictInt, StrictStr, field_validator

from nexus_contracts.authority_artifacts import (
    CanonicalArtifactError,
    canonical_authorization_path,
)
from nexus_contracts.document import StrictBaseModel

#: Protocole du reçu. Versionné : un futur format ne peut jamais être relu
#: comme celui-ci par accident.
REVIEW_BINDING_PROTOCOL_VERSION = "NEXUS-REVIEW-BINDING-V1"

#: Protocole de challenge d'ADR-0025 — nommé, jamais réinventé ici.
TRUSTED_REVIEW_PROTOCOL = "NEXUS-TRUSTED-REVIEW-V1"

#: Le seul algorithme de signature accepté. Une valeur inconnue est un refus,
#: jamais un repli.
SIGNATURE_ALGORITHM = "ed25519"

#: Permissions GitHub qui valent habilitation à approuver — même ensemble
#: que ``trusted_human_review._WRITE_PERMISSIONS``, dupliqué ici parce que
#: ``packages/contracts`` ne peut pas importer ``scripts/``.
ACCEPTED_REVIEWER_PERMISSIONS = ("admin", "write")

_HEX64 = r"^[0-9a-f]{64}$"
_HEX40 = r"^[0-9a-f]{40}$"
_HEX_ED25519 = r"^[0-9a-f]{64}$"
_SIGNATURE_HEX = r"^[0-9a-f]{128}$"
_LOGIN = r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?(?:\[bot\])?$"
_KEY_ID = r"^[a-z0-9][a-z0-9._-]{0,63}$"


class ReviewBindingError(ValueError):
    """Le reçu de liaison de revue ne prouve rien — fail-closed.

    Une seule exception pour tous les refus : structure, canonicité,
    signature, ancre de confiance, expiration, ou divergence avec
    l'autorisation confrontée. Un appelant n'a jamais à distinguer « mal
    formé » de « invalide » pour décider : les deux sont un refus."""


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    """Octets canoniques — même discipline qu'``authority_artifacts``."""
    return (
        json.dumps(
            document,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _canonical_moment(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("moments must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class ScopeAuthorizationReviewBindingV1(StrictBaseModel):
    """Les faits de revue, sans leur signature.

    C'est ce document — et lui seul — qui est signé. Toute valeur dont
    dépend la validité de la preuve y figure : rien n'est laissé à
    l'enveloppe, qui ne porte que l'algorithme, l'identifiant de clé et la
    signature elle-même.
    """

    protocol_version: Literal["NEXUS-REVIEW-BINDING-V1"]

    # --- Où la revue a eu lieu -------------------------------------------
    repository: StrictStr = Field(min_length=1, max_length=140)
    pull_request: StrictInt = Field(gt=0)
    base_ref: StrictStr = Field(min_length=1, max_length=255)
    base_sha: StrictStr = Field(pattern=_HEX40)
    head_sha: StrictStr = Field(pattern=_HEX40)

    # --- Ce qui a été relu ------------------------------------------------
    authorization_artifact_path: StrictStr = Field(min_length=1, max_length=512)
    authorization_artifact_sha256: StrictStr = Field(pattern=_HEX64)
    authorization_artifact_git_blob_sha1: StrictStr = Field(pattern=_HEX40)
    authorization_id: StrictStr = Field(min_length=1, max_length=128)
    authorization_decision: Literal["AUTHORIZE_INGESTION_SCOPE"]

    # --- Qui a relu -------------------------------------------------------
    review_id: StrictInt = Field(gt=0)
    reviewer_login: StrictStr = Field(pattern=_LOGIN)
    reviewer_permission: Literal["admin", "write"]
    author_login: StrictStr = Field(pattern=_LOGIN)
    submitted_at: AwareDatetime

    # --- Liaison au challenge d'ADR-0025 ----------------------------------
    challenge_protocol: Literal["NEXUS-TRUSTED-REVIEW-V1"]
    challenge_digest: StrictStr = Field(pattern=_HEX64)

    # --- Qui a produit ce reçu, et pour combien de temps -------------------
    verified_at: AwareDatetime
    verifier_version: StrictStr = Field(min_length=1, max_length=128)
    expires_at: AwareDatetime

    @field_validator("authorization_artifact_path")
    @classmethod
    def _path_stays_inside_governance(cls, value: str) -> str:
        """Le chemin ne peut désigner que le répertoire d'autorisations.
        Vérifié aussi par égalité au chemin dérivé de l'identifiant
        (``require_matches_authorization``) — deux barrières, parce qu'un
        chemin est le seul champ qu'un producteur pourrait vouloir
        élargir."""
        if ".." in value or value.startswith("/"):
            raise ValueError("authorization_artifact_path must be a repository path")
        if not value.startswith("governance/authorizations/"):
            raise ValueError(
                "authorization_artifact_path must live under governance/authorizations/"
            )
        return value

    def canonical_document(self) -> dict[str, Any]:
        return {
            "author_login": self.author_login,
            "authorization_artifact_git_blob_sha1": self.authorization_artifact_git_blob_sha1,
            "authorization_artifact_path": self.authorization_artifact_path,
            "authorization_artifact_sha256": self.authorization_artifact_sha256,
            "authorization_decision": self.authorization_decision,
            "authorization_id": self.authorization_id,
            "base_ref": self.base_ref,
            "base_sha": self.base_sha,
            "challenge_digest": self.challenge_digest,
            "challenge_protocol": self.challenge_protocol,
            "expires_at": _canonical_moment(self.expires_at),
            "head_sha": self.head_sha,
            "protocol_version": self.protocol_version,
            "pull_request": self.pull_request,
            "repository": self.repository,
            "review_id": self.review_id,
            "reviewer_login": self.reviewer_login,
            "reviewer_permission": self.reviewer_permission,
            "submitted_at": _canonical_moment(self.submitted_at),
            "verified_at": _canonical_moment(self.verified_at),
            "verifier_version": self.verifier_version,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()

    @property
    def challenge(self) -> str:
        """Le challenge tel qu'il apparaît dans le corps de la review."""
        return f"{self.challenge_protocol}:{self.challenge_digest}"


class SignedScopeAuthorizationReviewBinding(StrictBaseModel):
    """Le reçu tel qu'il est commité : faits + digest + signature."""

    binding: ScopeAuthorizationReviewBindingV1
    binding_digest: StrictStr = Field(pattern=_HEX64)
    signature_algorithm: Literal["ed25519"]
    key_id: StrictStr = Field(pattern=_KEY_ID)
    signature: StrictStr = Field(pattern=_SIGNATURE_HEX)

    def canonical_document(self) -> dict[str, Any]:
        return {
            "binding": self.binding.canonical_document(),
            "binding_digest": self.binding_digest,
            "key_id": self.key_id,
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())


class TrustAnchorKey(StrictBaseModel):
    """Une clé publique déclarée, avec son environnement.

    ``environment`` n'est pas décoratif : le mode ``production`` refuse
    toute clé ``test`` et réciproquement. Une clé de fixture ne peut donc
    jamais valider un gate final, même si son fichier est fourni par
    erreur."""

    key_id: StrictStr = Field(pattern=_KEY_ID)
    algorithm: Literal["ed25519"]
    public_key: StrictStr = Field(pattern=_HEX_ED25519)
    environment: Literal["production", "test"]
    comment: StrictStr = Field(default="", max_length=512)


class TrustAnchor(StrictBaseModel):
    """L'ensemble versionné des clés reconnues."""

    protocol_version: Literal["NEXUS-REVIEW-BINDING-V1"]
    keys: tuple[TrustAnchorKey, ...] = Field(min_length=1)

    @field_validator("keys")
    @classmethod
    def _key_ids_are_unique(cls, values: tuple[TrustAnchorKey, ...]) -> tuple[TrustAnchorKey, ...]:
        identifiers = [key.key_id for key in values]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("trust anchor key_id values must be unique")
        return values

    def key(self, key_id: str, *, environment: str) -> TrustAnchorKey:
        for candidate in self.keys:
            if candidate.key_id == key_id:
                if candidate.environment != environment:
                    raise ReviewBindingError(
                        f"key_id {key_id!r} is declared for the "
                        f"{candidate.environment!r} environment and can never be "
                        f"accepted in {environment!r} mode — a fixture key never "
                        "validates a production gate, and a production key is "
                        "never exercised by a rehearsal"
                    )
                return candidate
        raise ReviewBindingError(
            f"key_id {key_id!r} is not declared in the trust anchor — an "
            "unapproved signer proves nothing"
        )


def parse_trust_anchor(raw: bytes) -> TrustAnchor:
    """Parse strict d'un fichier d'ancre de confiance."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewBindingError(f"trust anchor is not valid UTF-8 JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise ReviewBindingError("trust anchor must be a JSON object")
    try:
        return TrustAnchor.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing, jamais silencieuse
        raise ReviewBindingError(f"trust anchor failed strict validation: {exc}") from exc


def sign_review_binding(
    binding: ScopeAuthorizationReviewBindingV1,
    *,
    private_key_hex: str,
    key_id: str,
) -> SignedScopeAuthorizationReviewBinding:
    """Signe les octets canoniques du reçu.

    ``private_key_hex`` vient d'un secret d'exécution, jamais d'un fichier
    du dépôt. Cette fonction ne le journalise ni ne le rend."""
    if not isinstance(binding, ScopeAuthorizationReviewBindingV1):
        raise TypeError("binding must be a ScopeAuthorizationReviewBindingV1")
    if not isinstance(private_key_hex, str) or re.fullmatch(
        _HEX_ED25519, private_key_hex.strip()
    ) is None:
        # Le message ne cite jamais la valeur reçue — un secret mal formé
        # reste un secret.
        raise ReviewBindingError(
            "the Ed25519 signing key must be exactly 64 lowercase hexadecimal "
            "characters (32 bytes of seed)"
        )
    if re.fullmatch(_KEY_ID, key_id) is None:
        raise ReviewBindingError(f"key_id {key_id!r} is not a canonical identifier")

    private_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(private_key_hex.strip())
    )
    payload = binding.canonical_bytes()
    return SignedScopeAuthorizationReviewBinding(
        binding=binding,
        binding_digest=sha256(payload).hexdigest(),
        signature_algorithm=SIGNATURE_ALGORITHM,
        key_id=key_id,
        signature=private_key.sign(payload).hex(),
    )


def public_key_hex(private_key_hex: str) -> str:
    """Clé publique correspondante — pour publier une ancre sans jamais
    manipuler la clé privée ailleurs que dans le producteur."""
    private_key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(private_key_hex))
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
    )

    return private_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    ).hex()


def parse_signed_review_binding(raw: bytes) -> SignedScopeAuthorizationReviewBinding:
    """Parse strict **et** exigence de canonicité octet à octet.

    L'égalité octet à octet est ce qui empêche deux fichiers différents
    (ordre des clés, indentation, espaces) de porter la même signature
    logique : les octets signés sont exactement ceux qu'un humain peut
    relire dans le dépôt."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReviewBindingError(
            f"review binding receipt is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise ReviewBindingError("review binding receipt must be a JSON object")
    try:
        signed = SignedScopeAuthorizationReviewBinding.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing
        raise ReviewBindingError(
            f"review binding receipt failed strict validation: {exc}"
        ) from exc
    if signed.canonical_bytes() != raw:
        raise ReviewBindingError(
            "review binding receipt bytes are not in canonical form — the signed "
            "bytes and their canonical re-serialization differ, so the signature "
            "cannot be bound to this file. Commit the canonical form."
        )
    return signed


def verify_review_binding(
    raw: bytes,
    *,
    trust_anchor: TrustAnchor,
    environment: Literal["production", "test"],
    now: datetime,
) -> ScopeAuthorizationReviewBindingV1:
    """Vérifie un reçu **entièrement hors ligne**.

    Ordre délibéré : canonicité, puis digest, puis ancre de confiance, puis
    signature, puis fenêtre temporelle. Un reçu dont la signature n'a pas
    encore été vérifiée n'a le droit de rien décider — pas même sa propre
    expiration."""
    signed = parse_signed_review_binding(raw)

    payload = signed.binding.canonical_bytes()
    recomputed = sha256(payload).hexdigest()
    if signed.binding_digest != recomputed:
        raise ReviewBindingError(
            f"binding_digest does not describe the receipt it accompanies "
            f"(declared={signed.binding_digest}, recomputed={recomputed})"
        )

    key = trust_anchor.key(signed.key_id, environment=environment)
    if key.algorithm != signed.signature_algorithm:
        raise ReviewBindingError(
            f"key {signed.key_id!r} signs {key.algorithm!r}, but the receipt "
            f"declares {signed.signature_algorithm!r}"
        )
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key.public_key)).verify(
            bytes.fromhex(signed.signature), payload
        )
    except InvalidSignature as exc:
        raise ReviewBindingError(
            f"the receipt signature does not verify against key {signed.key_id!r} "
            "— these bytes were not sealed by an approved signer"
        ) from exc

    if now.tzinfo is None:
        raise ReviewBindingError("now must be timezone-aware")
    if now >= signed.binding.expires_at:
        raise ReviewBindingError(
            f"review binding receipt expired at "
            f"{_canonical_moment(signed.binding.expires_at)} (now="
            f"{_canonical_moment(now)}) — a proof of review ages, and a stale "
            "one never authorizes a publication"
        )
    if now < signed.binding.verified_at:
        raise ReviewBindingError(
            "review binding receipt claims to have been verified in the future"
        )
    return signed.binding


def require_matches_authorization(
    binding: ScopeAuthorizationReviewBindingV1,
    *,
    authorization_id: str,
    authorization_bytes: bytes,
    authorization_git_blob_sha1: str,
    expected_repository: str,
    accepted_reviewers: tuple[str, ...] | None = None,
) -> None:
    """Confronte le reçu à l'autorisation qu'il prétend couvrir.

    Une signature valide prouve seulement *qui* a émis le reçu. Cette
    fonction prouve *sur quoi* il porte : sans elle, un reçu authentique
    émis pour une autre autorisation validerait n'importe quel corpus.
    """
    if binding.repository != expected_repository:
        raise ReviewBindingError(
            f"receipt covers repository {binding.repository!r}, not "
            f"{expected_repository!r} — a review in another repository "
            "authorizes nothing here"
        )
    if binding.authorization_id != authorization_id:
        raise ReviewBindingError(
            f"receipt covers authorization {binding.authorization_id!r}, not "
            f"{authorization_id!r}"
        )

    try:
        expected_path = canonical_authorization_path(authorization_id)
    except ValueError as exc:
        raise ReviewBindingError(str(exc)) from exc
    if binding.authorization_artifact_path != expected_path:
        raise ReviewBindingError(
            f"receipt names path {binding.authorization_artifact_path!r}, but the "
            f"canonical path of {authorization_id!r} is {expected_path!r}"
        )

    actual_sha256 = sha256(authorization_bytes).hexdigest()
    if binding.authorization_artifact_sha256 != actual_sha256:
        raise ReviewBindingError(
            "receipt was issued for different authorization bytes "
            f"(receipt={binding.authorization_artifact_sha256[:16]}..., "
            f"local={actual_sha256[:16]}...)"
        )
    if binding.authorization_artifact_git_blob_sha1 != authorization_git_blob_sha1:
        raise ReviewBindingError(
            "receipt Git blob SHA-1 does not match the local authorization bytes "
            f"(receipt={binding.authorization_artifact_git_blob_sha1}, "
            f"local={authorization_git_blob_sha1})"
        )

    if binding.reviewer_login == binding.author_login:
        raise ReviewBindingError(
            f"reviewer {binding.reviewer_login!r} is the author of the "
            "authorization pull request — self-approval is never a human review"
        )
    if binding.reviewer_permission not in ACCEPTED_REVIEWER_PERMISSIONS:
        raise ReviewBindingError(  # pragma: no cover - déjà borné par le Literal
            f"reviewer permission {binding.reviewer_permission!r} is not among "
            f"{list(ACCEPTED_REVIEWER_PERMISSIONS)!r}"
        )
    if accepted_reviewers is not None and binding.reviewer_login not in accepted_reviewers:
        raise ReviewBindingError(
            f"reviewer {binding.reviewer_login!r} is not among the trusted "
            f"reviewers {list(accepted_reviewers)!r}"
        )
    if binding.challenge_protocol != TRUSTED_REVIEW_PROTOCOL:
        raise ReviewBindingError(  # pragma: no cover - borné par le Literal
            f"challenge protocol {binding.challenge_protocol!r} is unsupported"
        )


def expected_challenge_digest(
    *,
    repository: str,
    pull_request: int,
    base_ref: str,
    base_sha: str,
    head_sha: str,
    author: str,
    reviewer: str,
) -> str:
    """Recalcule le digest de challenge d'ADR-0025 depuis ses sept
    dimensions.

    Dupliqué depuis ``scripts/github/trusted_human_review.build_challenge``
    parce que ``packages/contracts`` ne peut pas importer ``scripts/`` —
    l'égalité des deux implémentations est mesurée par un test dédié, pas
    supposée. C'est cette dérivation qui rend un challenge inutilisable
    pour un autre HEAD : les sept dimensions y entrent."""
    document = {
        "author": author,
        "base_ref": base_ref,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "protocol": TRUSTED_REVIEW_PROTOCOL,
        "pull_request": pull_request,
        "repository": repository,
        "reviewer": reviewer,
    }
    canonical = json.dumps(
        document, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def require_challenge_is_bound(binding: ScopeAuthorizationReviewBindingV1) -> None:
    """Le challenge du reçu doit être celui que ses propres dimensions
    produisent.

    Sans ce contrôle, ``challenge_digest`` serait un champ décoratif : un
    producteur compromis pourrait recopier le challenge d'une autre PR. Ici
    il est recalculé depuis le dépôt, la PR, la base, le HEAD, l'auteur et
    le relecteur que le reçu nomme lui-même."""
    expected = expected_challenge_digest(
        repository=binding.repository,
        pull_request=binding.pull_request,
        base_ref=binding.base_ref,
        base_sha=binding.base_sha,
        head_sha=binding.head_sha,
        author=binding.author_login,
        reviewer=binding.reviewer_login,
    )
    if binding.challenge_digest != expected:
        raise ReviewBindingError(
            "the receipt challenge is not the one its own dimensions produce "
            f"(receipt={binding.challenge_digest[:16]}..., "
            f"recomputed={expected[:16]}...) — a challenge recycled from another "
            "review binds nothing"
        )


__all__ = [
    "ACCEPTED_REVIEWER_PERMISSIONS",
    "REVIEW_BINDING_PROTOCOL_VERSION",
    "SIGNATURE_ALGORITHM",
    "TRUSTED_REVIEW_PROTOCOL",
    "CanonicalArtifactError",
    "ReviewBindingError",
    "ScopeAuthorizationReviewBindingV1",
    "SignedScopeAuthorizationReviewBinding",
    "TrustAnchor",
    "TrustAnchorKey",
    "expected_challenge_digest",
    "parse_signed_review_binding",
    "parse_trust_anchor",
    "public_key_hex",
    "require_challenge_is_bound",
    "require_matches_authorization",
    "sign_review_binding",
    "verify_review_binding",
]
