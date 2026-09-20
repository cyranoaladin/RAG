"""``NEXUS-STAGING-READINESS-V1`` — l'autorité d'une répétition, et d'elle seule.

**Pourquoi un protocole distinct plutôt qu'un mode de celui de production.**
``NEXUS-PRODUCTION-READINESS-V1`` répond à une question précise : *l'hôte
exécute-t-il exactement la release relue et promue ?* Ses vingt-six faits sont
des faits de déploiement — ``release_tag``, ``gate_result``, digest du compose
de production résolu, run du workflow de promotion, couverture H2-B. Il impose
d'ailleurs ``environment: "production"`` par littéral : une répétition qui
l'emprunterait devrait déclarer « production » pour ne rien déployer.

Une ingestion de release scellée en staging pose une autre question : *ai-je
le droit d'écrire ce corpus-là, avec ce code-là, dans ce plan de contrôle-là ?*
Répondre à la seconde avec le vocabulaire de la première obligerait à affirmer
deux douzaines de faits de déploiement pour une exécution qui ne déploie rien.
Ce protocole ne déclare donc que ce qui est vrai, et rien d'autre.

**Comment « rehearsal ≠ production » est rendu structurel, pas déclaratif.**
Trois barrières indépendantes, chacune suffisante :

1. ``protocol_version`` est un littéral qui lui est propre. Le fichier d'ancre
   de production porte ``NEXUS-PRODUCTION-READINESS-V1`` : présenté ici, il
   échoue au parsing. Pointer la variable d'ancre de répétition sur l'ancre
   gouvernée de production est donc refusé par le type, pas par une garde
   qu'on pourrait oublier ;
2. ``environment`` est le littéral ``"rehearsal"`` sur le manifeste **et** sur
   chaque clé de l'ancre. Une clé de production ne peut pas y figurer ;
3. rien dans ce module ne lit, n'écrit ni ne valide quoi que ce soit du
   protocole de production. Les deux chaînes ne se croisent nulle part.

**Ce que ce module refuse d'être.** Il ne contient aucune clé, ne produit
aucune ancre, et ``sign_staging_readiness_manifest`` exige une graine fournie
par l'appelant qu'il ne journalise ni ne rend. Les identifiants de clé
reconnaissables comme éphémères ou issus d'une fixture de test sont refusés
à la validation : une fixture peut légitimement signer dans un test, jamais
faire autorité sur un hôte.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal

from pydantic import AwareDatetime, Field, StrictStr, field_validator, model_validator

from nexus_contracts.document import StrictBaseModel

#: Le seul environnement que cette chaîne connaît. ``production`` n'est pas
#: une valeur possible ici — pas « déconseillée » : impossible.
REHEARSAL_ENVIRONMENT = "rehearsal"

STAGING_READINESS_PROTOCOL = "NEXUS-STAGING-READINESS-V1"

_HEX64 = r"^[0-9a-f]{64}$"
_GIT_SHA1 = r"^[0-9a-f]{40}$"
_SIGNATURE_HEX = r"^[0-9a-f]{128}$"
_KEY_ID = r"^[a-z0-9][a-z0-9._-]{0,63}$"
_REPOSITORY = r"^[A-Za-z0-9._-]+/[A-Za-z0-9._-]+$"
#: Une image est nommée par digest. Un tag désigne une cible mouvante : ce
#: n'est jamais une unité d'exécution.
_IMAGE_REF = r"^[a-z0-9][a-z0-9._/-]*@sha256:[0-9a-f]{64}$"
_RELEASE_ID = r"^[a-z0-9][a-z0-9._-]{0,127}$"

_CANONICAL_INDENT = 2

#: Marqueurs d'une identité de signature qui n'a pas vocation à faire
#: autorité. Ils visent les fabriques de fixture de ce dépôt
#: (``atomic_docker_v2_rehearsal_fixture.py`` : clés éphémères, relecteur
#: ``nexus-fixture-reviewer``) et tout ce qui s'en réclamerait.
_NON_AUTHORITATIVE_KEY_MARKERS = ("ephemeral", "fixture", "sample", "dummy", "example")


class StagingReadinessError(ValueError):
    """Refus de la chaîne de readiness de répétition. Jamais un avertissement."""


def _canonical_bytes(document: dict[str, Any]) -> bytes:
    return (
        json.dumps(document, sort_keys=True, indent=_CANONICAL_INDENT, ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def _canonical_moment(value: datetime) -> str:
    return value.astimezone(tz=value.tzinfo).isoformat().replace("+00:00", "Z")


def _require_authoritative_key_id(value: str) -> str:
    """Une identité de clé ne peut pas s'annoncer comme non autoritaire.

    Ce n'est pas de la cosmétique : la seule chaîne de répétition existante
    dans ce dépôt est une fabrique de fixture de test, dont les clés portent
    ``ephemeral`` dans leur identifiant. Les accepter ferait d'un matériel de
    test une autorité d'exécution."""
    lowered = value.lower()
    for marker in _NON_AUTHORITATIVE_KEY_MARKERS:
        if marker in lowered:
            raise ValueError(
                f"key_id {value!r} contains {marker!r} — a test fixture key never "
                "carries authority on a host; generate a real key held offline"
            )
    return value


class StagingReadinessManifestV1(StrictBaseModel):
    """Les faits qui autorisent — ou non — une ingestion de release en staging.

    Chaque champ est vérifiable contre quelque chose de réel : un commit, un
    digest d'image, un digest de manifeste de release. Aucun n'est une
    affirmation de confort."""

    protocol_version: Literal["NEXUS-STAGING-READINESS-V1"]
    #: Littéral. Ce manifeste ne peut pas déclarer « production », donc ne
    #: peut pas être présenté comme une autorisation de production.
    environment: Literal["rehearsal"]

    # — Le code réellement exécuté —
    repository: StrictStr = Field(pattern=_REPOSITORY)
    #: Le commit de ``main`` dont l'image worker a été construite. Lie
    #: l'exécution au code relu, pas à une branche.
    merge_sha: StrictStr = Field(pattern=_GIT_SHA1)
    #: L'image worker, épinglée par digest (lot CH6). Un tag serait une
    #: cible mouvante.
    worker_image: StrictStr = Field(pattern=_IMAGE_REF)

    # — Le corpus que cette autorisation couvre, et lui seul —
    allowed_release_id: StrictStr = Field(pattern=_RELEASE_ID)
    allowed_release_manifest_sha256: StrictStr = Field(pattern=_HEX64)

    # — L'invariant de cloisonnement, déclaré et vérifié à l'exécution —
    control_dsn_differs_from_product: Literal[True]

    # — Provenance et durée de vie —
    key_id: StrictStr = Field(pattern=_KEY_ID)
    issued_at: AwareDatetime
    #: Une autorisation de répétition expire. Sans borne, elle deviendrait
    #: une autorisation permanente que personne n'a décidé d'accorder.
    expires_at: AwareDatetime

    @field_validator("key_id")
    @classmethod
    def _key_id_is_authoritative(cls, value: str) -> str:
        return _require_authoritative_key_id(value)

    @model_validator(mode="after")
    def _validity_window_is_ordered(self) -> StagingReadinessManifestV1:
        if self.expires_at <= self.issued_at:
            raise ValueError(
                "expires_at must be strictly after issued_at — an authorisation "
                "that expires before it is issued authorises nothing"
            )
        return self

    def canonical_document(self) -> dict[str, Any]:
        return {
            "allowed_release_id": self.allowed_release_id,
            "allowed_release_manifest_sha256": self.allowed_release_manifest_sha256,
            "control_dsn_differs_from_product": self.control_dsn_differs_from_product,
            "environment": self.environment,
            "expires_at": _canonical_moment(self.expires_at),
            "issued_at": _canonical_moment(self.issued_at),
            "key_id": self.key_id,
            "merge_sha": self.merge_sha,
            "protocol_version": self.protocol_version,
            "repository": self.repository,
            "worker_image": self.worker_image,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())

    def digest(self) -> str:
        return sha256(self.canonical_bytes()).hexdigest()


class SignedStagingReadinessManifest(StrictBaseModel):
    """Le manifeste tel qu'il est déposé sur l'hôte : faits, digest, signature."""

    manifest: StagingReadinessManifestV1
    manifest_digest: StrictStr = Field(pattern=_HEX64)
    signature_algorithm: Literal["ed25519"]
    key_id: StrictStr = Field(pattern=_KEY_ID)
    signature: StrictStr = Field(pattern=_SIGNATURE_HEX)

    def canonical_document(self) -> dict[str, Any]:
        return {
            "key_id": self.key_id,
            "manifest": self.manifest.canonical_document(),
            "manifest_digest": self.manifest_digest,
            "signature": self.signature,
            "signature_algorithm": self.signature_algorithm,
        }

    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.canonical_document())


class StagingReadinessTrustAnchorKey(StrictBaseModel):
    key_id: StrictStr = Field(pattern=_KEY_ID)
    algorithm: Literal["ed25519"]
    public_key: StrictStr = Field(pattern=_HEX64)
    #: Littéral. Une clé de production ne peut pas figurer dans cette ancre,
    #: et une clé de cette ancre ne peut rien signer pour la production.
    environment: Literal["rehearsal"]
    comment: StrictStr = Field(default="", max_length=512)

    @field_validator("key_id")
    @classmethod
    def _key_id_is_authoritative(cls, value: str) -> str:
        return _require_authoritative_key_id(value)


class StagingReadinessTrustAnchor(StrictBaseModel):
    """Ancre **propre** à la répétition.

    Son ``protocol_version`` lui est propre : l'ancre gouvernée de production
    (``NEXUS-PRODUCTION-READINESS-V1``) ne peut pas être présentée ici, même
    en pointant la variable d'environnement sur son chemin."""

    protocol_version: Literal["NEXUS-STAGING-READINESS-V1"]
    keys: tuple[StagingReadinessTrustAnchorKey, ...] = Field(min_length=1)

    @field_validator("keys")
    @classmethod
    def _key_ids_are_unique(
        cls, values: tuple[StagingReadinessTrustAnchorKey, ...]
    ) -> tuple[StagingReadinessTrustAnchorKey, ...]:
        identifiers = [key.key_id for key in values]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("trust anchor key_id values must be unique")
        return values

    def key(self, key_id: str) -> StagingReadinessTrustAnchorKey:
        for candidate in self.keys:
            if candidate.key_id == key_id:
                return candidate
        raise StagingReadinessError(
            f"key_id {key_id!r} is not declared in the staging readiness trust "
            "anchor — an unapproved signer proves nothing"
        )


def parse_staging_readiness_trust_anchor(raw: bytes) -> StagingReadinessTrustAnchor:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingReadinessError(
            f"staging readiness trust anchor is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise StagingReadinessError(
            "staging readiness trust anchor must be a JSON object"
        )
    try:
        return StagingReadinessTrustAnchor.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing
        raise StagingReadinessError(
            f"staging readiness trust anchor failed strict validation: {exc}"
        ) from exc


def parse_signed_staging_readiness_manifest(raw: bytes) -> SignedStagingReadinessManifest:
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingReadinessError(
            f"signed staging readiness manifest is not valid UTF-8 JSON: {exc}"
        ) from exc
    if not isinstance(document, dict):
        raise StagingReadinessError(
            "signed staging readiness manifest must be a JSON object"
        )
    try:
        return SignedStagingReadinessManifest.model_validate(document)
    except Exception as exc:  # noqa: BLE001 - frontière de parsing
        raise StagingReadinessError(
            f"signed staging readiness manifest failed strict validation: {exc}"
        ) from exc


def sign_staging_readiness_manifest(
    manifest: StagingReadinessManifestV1,
    *,
    private_key_hex: str,
    key_id: str,
) -> SignedStagingReadinessManifest:
    """Signe les octets canoniques du manifeste.

    La graine vient de l'appelant — un fichier hors dépôt et hors hôte. Cette
    fonction ne la journalise pas, ne la rend pas, et ne la cite dans aucun
    message d'erreur."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    if not isinstance(manifest, StagingReadinessManifestV1):
        raise TypeError("manifest must be a StagingReadinessManifestV1")
    if not isinstance(private_key_hex, str) or (
        re.fullmatch(_HEX64, private_key_hex.strip()) is None
    ):
        # Le message ne cite jamais la valeur reçue.
        raise StagingReadinessError(
            "the staging readiness signing key must be 64 lowercase hex characters "
            "(an Ed25519 seed)"
        )
    if re.fullmatch(_KEY_ID, key_id) is None:
        raise StagingReadinessError(f"key_id {key_id!r} must match {_KEY_ID}")
    if manifest.key_id != key_id:
        raise StagingReadinessError(
            f"manifest declares key_id {manifest.key_id!r} but is being signed with "
            f"{key_id!r} — a manifest never names a signer other than its own"
        )

    private_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(private_key_hex.strip())
    )
    payload = manifest.canonical_bytes()
    return SignedStagingReadinessManifest(
        manifest=manifest,
        manifest_digest=sha256(payload).hexdigest(),
        signature_algorithm="ed25519",
        key_id=key_id,
        signature=private_key.sign(payload).hex(),
    )


def staging_public_key_hex(private_key_hex: str) -> str:
    """Clé publique d'une graine — sert à publier une ancre, jamais à signer."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    if not isinstance(private_key_hex, str) or (
        re.fullmatch(_HEX64, private_key_hex.strip()) is None
    ):
        raise StagingReadinessError(
            "the staging readiness signing key must be 64 lowercase hex characters"
        )
    private_key = Ed25519PrivateKey.from_private_bytes(
        bytes.fromhex(private_key_hex.strip())
    )
    return (
        private_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    )


def verify_staging_readiness_manifest(
    raw: bytes,
    *,
    trust_anchor: StagingReadinessTrustAnchor,
    now: datetime,
) -> StagingReadinessManifestV1:
    """Vérifie signature, ancre, environnement et fenêtre — hors ligne.

    Ordre délibéré : la signature d'abord. Un manifeste non vérifié n'a le
    droit de rien affirmer, pas même sur lui-même.

    ``now`` est un paramètre obligatoire et non un appel d'horloge interne :
    l'appelant possède déjà l'instant qu'il utilise pour ses autres gardes,
    et deux horloges divergentes dans une même décision seraient une faille."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    if not isinstance(trust_anchor, StagingReadinessTrustAnchor):
        raise TypeError(
            "trust_anchor must be a StagingReadinessTrustAnchor — the production "
            "readiness anchor is a different authority and is never accepted here"
        )
    signed = parse_signed_staging_readiness_manifest(raw)
    payload = signed.manifest.canonical_bytes()

    if signed.manifest_digest != sha256(payload).hexdigest():
        raise StagingReadinessError(
            "manifest_digest does not match the canonical manifest bytes"
        )
    if signed.key_id != signed.manifest.key_id:
        raise StagingReadinessError(
            "the signed envelope and the manifest name different key_id values"
        )

    key = trust_anchor.key(signed.key_id)
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key.public_key)).verify(
            bytes.fromhex(signed.signature), payload
        )
    except InvalidSignature as exc:
        raise StagingReadinessError(
            f"staging readiness manifest signature is invalid under key_id "
            f"{signed.key_id!r}"
        ) from exc

    if signed.manifest.environment != REHEARSAL_ENVIRONMENT:
        raise StagingReadinessError(
            f"staging readiness manifest declares environment "
            f"{signed.manifest.environment!r}, which this chain never accepts"
        )
    if now < signed.manifest.issued_at:
        raise StagingReadinessError(
            f"staging readiness manifest is not valid yet (issued_at="
            f"{signed.manifest.issued_at.isoformat()})"
        )
    if now >= signed.manifest.expires_at:
        raise StagingReadinessError(
            f"staging readiness manifest expired at "
            f"{signed.manifest.expires_at.isoformat()}"
        )
    return signed.manifest


__all__ = [
    "REHEARSAL_ENVIRONMENT",
    "STAGING_READINESS_PROTOCOL",
    "SignedStagingReadinessManifest",
    "StagingReadinessError",
    "StagingReadinessManifestV1",
    "StagingReadinessTrustAnchor",
    "StagingReadinessTrustAnchorKey",
    "parse_signed_staging_readiness_manifest",
    "parse_staging_readiness_trust_anchor",
    "sign_staging_readiness_manifest",
    "staging_public_key_hex",
    "verify_staging_readiness_manifest",
]
